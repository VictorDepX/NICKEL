"""Text-to-speech com Piper, reprodução local e conversão para nota de voz do WhatsApp."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
import wave
from pathlib import Path
from typing import Protocol

from nickel.speech import playback
from nickel.speech.playback import TTSError

__all__ = ["PiperSpeaker", "Speaker", "TTSError", "clean_for_speech", "split_for_tts", "wav_to_ogg_opus"]

log = logging.getLogger(__name__)



class Speaker(Protocol):
    async def synthesize(self, text: str) -> Path: ...
    async def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...


def clean_for_speech(text: str) -> str:
    """Remove markdown, URLs e símbolos que o TTS leria em voz alta."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>\[\]]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def _cut_long(sentence: str, limit: int) -> list[str]:
    """Corta uma frase maior que o limite no último espaço antes dele."""
    parts: list[str] = []
    while len(sentence) > limit:
        cut = sentence.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        parts.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    if sentence:
        parts.append(sentence)
    return parts


def split_for_tts(text: str, limit: int = 4000) -> list[str]:
    """Limpa o texto e divide em blocos de até `limit` caracteres, em fim de frase."""
    cleaned = clean_for_speech(text)
    if not cleaned:
        return []
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(cleaned):
        pieces = [sentence] if len(sentence) <= limit else _cut_long(sentence, limit)
        for piece in pieces:
            if current and len(current) + 1 + len(piece) <= limit:
                current = f"{current} {piece}"
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


class PiperSpeaker:
    def __init__(self, voice_path: Path, work_dir: Path) -> None:
        self.voice_path = voice_path
        self.work_dir = work_dir
        self._voice = None

    def _synthesize_sync(self, text: str, target: Path) -> None:
        if self._voice is None:
            from piper import PiperVoice

            self._voice = PiperVoice.load(str(self.voice_path))
        with wave.open(str(target), "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file)

    async def synthesize(self, text: str) -> Path:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(suffix=".wav", dir=self.work_dir, delete=False)
        handle.close()
        target = Path(handle.name)
        await asyncio.to_thread(self._synthesize_sync, clean_for_speech(text), target)
        return target

    async def speak(self, text: str) -> None:
        spoken = clean_for_speech(text)
        if not spoken:
            return
        wav = await self.synthesize(spoken)
        try:
            await self.play(wav)
        finally:
            wav.unlink(missing_ok=True)

    async def play(self, wav: Path) -> None:
        await playback.play_wav(wav)

    def stop(self) -> None:
        playback.stop_playback()


async def wav_to_ogg_opus(wav: Path) -> bytes:
    """Converte WAV em OGG/Opus (formato de nota de voz do WhatsApp). Requer ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg não encontrado.")
    target = wav.with_suffix(".ogg")
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
        "-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-ar", "48000", str(target),
    )
    if await process.wait() != 0:
        raise RuntimeError("ffmpeg falhou ao converter o áudio.")
    try:
        return target.read_bytes()
    finally:
        target.unlink(missing_ok=True)
