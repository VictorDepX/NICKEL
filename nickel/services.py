"""Container de dependências. Os testes montam `Services` com dublês."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from nickel.config import Settings
from nickel.core.db import Database
from nickel.core.llm import LLMClient, make_llm
from nickel.core.stores import (
    AuditLog,
    ConversationStore,
    InboundDedup,
    MemoryStore,
    PendingActionStore,
    TokenStore,
)


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

    @classmethod
    def core(cls, settings: Settings, llm: LLMClient, db: Database | None = None) -> "Services":
        """Só o essencial (banco + LLM). Integrações ficam None até serem atribuídas."""
        db = db or Database(settings.db_path)
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
        )

    def google_ready(self) -> bool:
        return self.google is not None and self.google.status().get("status") == "ready"

    def google_configured(self) -> bool:
        return self.google is not None and not self.google.missing_config()

    def spotify_configured(self) -> bool:
        return self.spotify is not None and not self.spotify.missing_config()


def build_services(settings: Settings, llm: LLMClient | None = None) -> Services:
    from nickel.channels.whatsapp import WhatsAppClient
    from nickel.core.outbound import Outbound
    from nickel.integrations.google import CalendarService, GmailService, GoogleAuth
    from nickel.integrations.music import MusicFinder
    from nickel.integrations.obsidian import ObsidianVault
    from nickel.integrations.spotify import SpotifyClient
    from nickel.skills.reminders import ReminderService

    services = Services.core(settings, llm or make_llm(settings))

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
    if settings.tts_voice_path and module_available("piper"):
        from nickel.speech.tts import PiperSpeaker

        services.tts = PiperSpeaker(settings.tts_voice_path, settings.data_dir / "tmp")
    if settings.voice_enabled and module_available("sounddevice"):
        from nickel.speech.recorder import MicRecorder

        services.recorder = MicRecorder(settings.data_dir / "tmp")

    if settings.bridge_token:
        services.whatsapp = WhatsAppClient(settings)
    services.outbound = Outbound(services)
    services.reminders = ReminderService(services)
    return services
