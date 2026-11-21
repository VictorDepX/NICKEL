"""Container de dependências. Os testes montam `Services` com dublês."""

from __future__ import annotations

import asyncio
import importlib.util
import time
from dataclasses import dataclass, field
from typing import Any

from nickel.config import Settings
from nickel.core.db import Database
from nickel.core.llm import LLMClient, make_cloud_llm, make_llm
from nickel.core.stores import (
    AuditLog,
    ConversationStore,
    InboundDedup,
    MemoryStore,
    PendingActionStore,
    StateStore,
    TokenStore,
)
from nickel.core.workspaces import Workspace, WorkspaceManager


VOICE_OFF = "voz indisponível"


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


@dataclass
class Services:
    settings: Settings
    db: Database
    conversations: ConversationStore
    pending: PendingActionStore
    audit: AuditLog
    memory: MemoryStore
    tokens: TokenStore
    dedup: InboundDedup
    llm: LLMClient
    state: StateStore | None = None
    workspaces: WorkspaceManager | None = None
    llm_cloud: LLMClient | None = None
    google: Any = None
    gmail: Any = None
    calendar: Any = None
    spotify: Any = None
    music: Any = None
    obsidian: Any = None
    stt: Any = None
    tts: Any = None
    recorder: Any = None
    whatsapp: Any = None
    outbound: Any = None
    reminders: Any = None
    tts_provider: str | None = None  # "voicestudio" | "piper" | None (preenchido por build_services)
    _tts_cache: tuple[float, dict[str, Any]] | None = field(default=None, init=False, repr=False)
    _speech: asyncio.Task | None = field(default=None, init=False, repr=False)
    _speech_gen: int = field(default=0, init=False, repr=False)

    @classmethod
    def core(cls, settings: Settings, llm: LLMClient, db: Database | None = None) -> "Services":
        """Só o essencial (banco + LLM). Integrações ficam None até serem atribuídas."""
        db = db or Database(settings.db_path)
        state = StateStore(db)
        return cls(
            settings=settings,
            db=db,
            conversations=ConversationStore(db),
            pending=PendingActionStore(db),
            audit=AuditLog(db),
            memory=MemoryStore(db),
            tokens=TokenStore(db, settings.oauth_token_key),
            dedup=InboundDedup(db),
            llm=llm,
            state=state,
            workspaces=WorkspaceManager.from_settings(settings, state),
        )

    async def tts_status(self, *, ttl: float = 30.0, timeout: float = 2.0) -> dict[str, Any]:
        """Estado da voz de saída para `/api/state`: cache de `ttl` s e nunca espera mais que `timeout` s."""
        provider = self.tts_provider if self.tts is not None else None
        if self.tts is not None and provider is None:
            provider = resolve_tts_provider(self.settings)
        if self.tts is None or provider is None:
            return {"provider": None, "ok": False, "detail": "voz desligada"}
        if provider == "piper":
            path = self.settings.tts_voice_path
            return {"provider": "piper", "ok": bool(path and path.exists()), "detail": path.name if path else ""}
        now = time.monotonic()
        if self._tts_cache and now - self._tts_cache[0] < ttl:
            return {"provider": provider, **self._tts_cache[1]}
        try:
            health = await asyncio.wait_for(self.tts.health(), timeout)
            result = {"ok": bool(health.get("ok")), "detail": str(health.get("detail", ""))}
        except asyncio.TimeoutError:
            result = {"ok": False, "detail": f"sem resposta em {timeout:g} s"}
        except Exception as exc:
            result = {"ok": False, "detail": str(exc) or type(exc).__name__}
        self._tts_cache = (now, result)
        return {"provider": provider, **result}

    async def speak(self, text: str, *, source: str) -> str | None:
        """Fala `text` com auditoria (`tts/start` → `tts/done` | `tts/error`). Nunca levanta.

        Devolve a mensagem de erro, ou None (falou, foi interrompida ou substituída).
        Só uma síntese fica ativa: cada chamada pega uma geração nova; a fala anterior é
        cancelada e registra o fim antes de a nova começar, e quem foi substituído (ou
        parado por `stop_speaking`) enquanto esperava não chega a falar. A síntese roda
        numa tarefa própria: cancelá-la não derruba quem chamou (ex.: a sessão de voz).
        """
        if self.tts is None:
            self.audit.record("tts", "tts", "error", {"source": source, "detail": VOICE_OFF})
            return VOICE_OFF
        self._speech_gen += 1
        gen = self._speech_gen
        self.tts.stop()
        while self._speech is not None and not self._speech.done():
            previous = self._speech
            previous.cancel()
            await asyncio.wait({previous})
            if self._speech_gen != gen:
                return None  # outra fala chegou depois, ou "Parar" foi pedido
        if self._speech_gen != gen:
            return None
        task = asyncio.create_task(self._speak_now(text, source))
        self._speech = task
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            task.cancel()
            raise
        return None if task.cancelled() else task.result()

    async def _speak_now(self, text: str, source: str) -> str | None:
        provider = self.tts_provider or resolve_tts_provider(self.settings) or "tts"
        if provider == "voicestudio":
            voice = self.settings.voicestudio_voice
        else:
            voice = self.settings.tts_voice_path.name if self.settings.tts_voice_path else ""
        chars = len(text)
        # Registrado antes da síntese: no VoiceStudio ela pode levar minutos, e a fase já é "Falando".
        self.audit.record("tts", provider, "start", {"source": source, "chars": chars, "provider": provider, "voice": voice})
        started = time.monotonic()

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            await self.tts.speak(text)
        except asyncio.CancelledError:
            self.audit.record("tts", provider, "done", {"chars": chars, "interrupted": True}, duration_ms=elapsed())
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self.audit.record("tts", provider, "error", {"source": source, "detail": message}, duration_ms=elapsed())
            return message
        else:
            self.audit.record("tts", provider, "done", {"chars": chars}, duration_ms=elapsed())
        return None

    def stop_speaking(self) -> None:
        """Para a reprodução, cancela a síntese em curso (que registra `tts/done` interrompido)
        e invalida falas que ainda esperavam a vez."""
        self._speech_gen += 1
        if self.tts is not None:
            self.tts.stop()
        if self._speech is not None and not self._speech.done():
            self._speech.cancel()

    async def shutdown_speech(self, timeout: float = 2.0) -> None:
        """`stop_speaking` e espera (até `timeout` s) a fala registrar o fim. Usado no desligamento."""
        self.stop_speaking()
        task = self._speech
        if task is not None and not task.done():
            await asyncio.wait({task}, timeout=timeout)

    def llm_for(self, workspace: Workspace | None) -> LLMClient:
        """Backend do workspace. Sem `llm_cloud` configurado, `backend: cloud` cai no modelo local."""
        if workspace is not None and workspace.backend == "cloud" and self.llm_cloud is not None:
            return self.llm_cloud
        return self.llm

    def active_conversation(self) -> str:
        return self.workspaces.active().conversation if self.workspaces else "main"

    def google_ready(self) -> bool:
        return self.google is not None and self.google.status().get("status") == "ready"

    def google_configured(self) -> bool:
        return self.google is not None and not self.google.missing_config()

    def spotify_configured(self) -> bool:
        return self.spotify is not None and not self.spotify.missing_config()


def resolve_tts_provider(settings: Settings) -> str | None:
    """`auto` prefere o VoiceStudio (se há URL) e cai no Piper (se há voz); `none` desliga."""
    choice = (settings.tts_provider or "auto").lower()
    if choice == "none":
        return None
    if choice == "voicestudio":
        return "voicestudio"
    if choice == "piper":
        return "piper" if settings.tts_voice_path else None
    if settings.voicestudio_url:
        return "voicestudio"
    return "piper" if settings.tts_voice_path else None


def build_services(settings: Settings, llm: LLMClient | None = None) -> Services:
    from nickel.channels.whatsapp import WhatsAppClient
    from nickel.core.outbound import Outbound
    from nickel.integrations.google import CalendarService, GmailService, GoogleAuth
    from nickel.integrations.music import MusicFinder
    from nickel.integrations.obsidian import ObsidianVault
    from nickel.integrations.spotify import SpotifyClient
    from nickel.skills.reminders import ReminderService

    services = Services.core(settings, llm or make_llm(settings))
    services.llm_cloud = make_cloud_llm(settings)

    services.google = GoogleAuth(settings, services.tokens)
    services.gmail = GmailService(services.google)
    services.calendar = CalendarService(services.google, settings.google_calendar_id, settings.timezone)
    services.spotify = SpotifyClient(settings, services.tokens)
    if module_available("shazamio"):
        services.music = MusicFinder(services.spotify)
    services.obsidian = ObsidianVault(settings.obsidian_vault_path, settings.obsidian_notes_dir)

    if module_available("faster_whisper"):
        from nickel.speech.stt import WhisperTranscriber

        services.stt = WhisperTranscriber(settings)
    provider = resolve_tts_provider(settings)
    if provider == "voicestudio":
        from nickel.speech.voicestudio import VoiceStudioSpeaker

        services.tts = VoiceStudioSpeaker(settings, settings.data_dir / "tmp")
    elif provider == "piper" and module_available("piper"):
        from nickel.speech.tts import PiperSpeaker

        services.tts = PiperSpeaker(settings.tts_voice_path, settings.data_dir / "tmp")
    if services.tts is not None:
        services.tts_provider = provider
    if settings.voice_enabled and module_available("sounddevice"):
        from nickel.speech.recorder import MicRecorder

        services.recorder = MicRecorder(settings.data_dir / "tmp")

    if settings.bridge_token:
        services.whatsapp = WhatsAppClient(settings)
    services.outbound = Outbound(services)
    services.reminders = ReminderService(services)
    return services
