"""Canal de voz push-to-talk: o atalho chama `nickel listen`, que alterna gravar/parar."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import TYPE_CHECKING

from nickel.core.agent import Agent, Turn
from nickel.core.outbound import desktop_notify
from nickel.core.trace import new_run_id, run_scope

if TYPE_CHECKING:  # pragma: no cover
    from nickel.services import Services

log = logging.getLogger(__name__)


class VoiceController:
    def __init__(self, services: "Services", agent: Agent) -> None:
        self.services = services
        self.agent = agent
        self.state = "idle"
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def available(self) -> bool:
        s = self.services
        return bool(s.settings.voice_enabled and s.recorder and s.stt)

    def status(self) -> dict[str, object]:
        return {
            "available": self.available,
            "state": self.state,
            "stt": self.services.stt is not None,
            "tts": self.services.tts is not None,
            "microphone": self.services.recorder is not None,
        }

    async def toggle(self) -> str:
        if not self.available:
            return "unavailable"
        if self.state == "idle":
            self._stop = asyncio.Event()
            self.state = "listening"
            self._task = asyncio.create_task(self._session())
            return "listening"
        if self.state == "listening":
            self._stop.set()
            return "processing"
        if self.state == "speaking" and self.services.tts is not None:
            self.services.tts.stop()
            return "stopped"
        return self.state

    async def _notify(self, body: str) -> None:
        if self.services.settings.voice_notify:
            await desktop_notify("NICKEL", body)

    def _set_state(self, state: str, detail: dict[str, object] | None = None) -> None:
        self.state = state
        self.services.audit.record("voice", state, state, detail)

    async def _session(self) -> None:
        with run_scope(new_run_id()):
            await self._run_session()

    async def _run_session(self) -> None:
        settings = self.services.settings
        try:
            self._set_state("listening")
            await self._notify("Ouvindo…")
            audio = await self.services.recorder.record(
                self._stop, settings.voice_max_seconds, settings.voice_silence_seconds
            )
            self._set_state("transcribing")
            text = (await self.services.stt.transcribe(audio)).strip()
            audio.unlink(missing_ok=True)
            if not text:
                await self._notify("Não entendi.")
                return
            self._set_state("thinking", {"chars": len(text)})
            reply = await self.agent.handle(Turn(channel="voice", text=text))
            self._set_state("speaking")
            await self._notify(reply.text)
            if settings.voice_open_links and reply.links and shutil.which("xdg-open"):
                await asyncio.create_subprocess_exec("xdg-open", reply.links[0])
            if self.services.tts is not None:
                await self.services.tts.speak(reply.text)
        except Exception as exc:
            log.exception("Sessão de voz falhou")
            self.services.audit.record("voice", "error", "error", {"detail": str(exc)})
            await self._notify(f"Erro na voz: {exc}")
        finally:
            self._set_state("idle")
