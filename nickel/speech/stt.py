"""Speech-to-text com faster-whisper (carregado sob demanda e mantido em memória)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from nickel.config import Settings

log = logging.getLogger(__name__)


class Transcriber(Protocol):
    async def transcribe(self, path: Path) -> str: ...


class WhisperTranscriber:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._lock = asyncio.Lock()

    def _load(self):
        from faster_whisper import WhisperModel

        log.info("Carregando faster-whisper %s em %s", self.settings.stt_model, self.settings.stt_device)
        return WhisperModel(
            self.settings.stt_model,
            device=self.settings.stt_device,
            compute_type=self.settings.stt_compute_type,
        )

    def _run(self, path: Path) -> str:
        if self._model is None:
            self._model = self._load()
        segments, _info = self._model.transcribe(
            str(path),
            language=self.settings.stt_language or None,
            vad_filter=True,
            beam_size=1,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    async def transcribe(self, path: Path) -> str:
        async with self._lock:  # um modelo, uma transcrição por vez
            return await asyncio.to_thread(self._run, path)

    async def warm_up(self) -> None:
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)
