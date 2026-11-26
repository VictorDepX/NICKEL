"""Voz de saída pelo Microsoft Edge TTS (`edge-tts`): voz neural fixa, rápida, precisa de internet.

O Edge entrega MP3; o ffmpeg converte para WAV, que é o formato que `playback` toca
e que `wav_to_ogg_opus` transforma em nota de voz do WhatsApp.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

from nickel.config import Settings
from nickel.speech import playback
from nickel.speech.tts import TTSError, split_for_tts

__all__ = ["EdgeSpeaker"]

_CHUNK_LIMIT = 2000  # o serviço aceita mais, mas blocos menores começam a tocar antes


def _module_ok() -> bool:
    import importlib.util

    return importlib.util.find_spec("edge_tts") is not None


class EdgeSpeaker:
    def __init__(self, settings: Settings, work_dir: Path, communicate: Any = None) -> None:
        self.settings = settings
        self.work_dir = work_dir
        self._communicate = communicate  # injetável nos testes
        self._gen = 0

    def _factory(self) -> Any:
        if self._communicate is not None:
            return self._communicate
        try:
            import edge_tts
        except ImportError as exc:
            raise TTSError("edge-tts não instalado (pip install edge-tts).") from exc
        return edge_tts.Communicate

    async def _mp3(self, text: str) -> bytes:
        communicate = self._factory()(
            text, self.settings.edge_tts_voice, rate=self.settings.edge_tts_rate
        )
        audio = bytearray()
        try:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    audio.extend(chunk.get("data") or b"")
        except Exception as exc:  # rede, serviço fora, voz inválida
            raise TTSError(f"Edge TTS falhou: {type(exc).__name__}: {exc}") from exc
        if not audio:
            raise TTSError("Edge TTS não devolveu áudio (voz inválida ou sem internet?).")
        return bytes(audio)

    async def _to_wav(self, mp3: bytes, target: Path) -> None:
        if not shutil.which("ffmpeg"):
            raise TTSError("ffmpeg não encontrado (necessário para o Edge TTS).")
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", "-f", "mp3", "-i", "pipe:0",
            "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(target),
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await process.communicate(mp3)
        if process.returncode != 0:
            raise TTSError(f"ffmpeg falhou ao converter o áudio do Edge: {err.decode(errors='replace')[:200]}")

    async def synthesize(self, text: str) -> Path:
        pieces = split_for_tts(text, 100_000)
        if not pieces:
            raise TTSError("Nada para falar depois da limpeza do texto.")
        mp3 = await self._mp3(" ".join(pieces))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(suffix=".wav", dir=self.work_dir, delete=False)
        handle.close()
        target = Path(handle.name)
        try:
            await self._to_wav(mp3, target)
        except BaseException:
            playback.discard(target)
            raise
        return target

    async def speak(self, text: str) -> None:
        pieces = split_for_tts(text, _CHUNK_LIMIT)
        if not pieces:
            return
        self.stop()  # uma nova fala interrompe a anterior
        gen = self._gen
        for piece in pieces:
            if self._gen != gen:
                return
            wav = await self.synthesize(piece)
            try:
                if self._gen != gen:
                    return
                await playback.play_wav(wav)
            finally:
                playback.discard(wav)

    def stop(self) -> None:
        self._gen += 1
        playback.stop_playback()

    async def health(self) -> dict:
        """Só checagens locais (pacote e ffmpeg); a internet é testada na primeira fala."""
        if not _module_ok() and self._communicate is None:
            return {"ok": False, "detail": "pip install edge-tts"}
        if not shutil.which("ffmpeg"):
            return {"ok": False, "detail": "ffmpeg ausente"}
        return {"ok": True, "detail": self.settings.edge_tts_voice}

    async def aclose(self) -> None:
        return None
