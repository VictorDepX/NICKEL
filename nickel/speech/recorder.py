"""Gravação do microfone (16 kHz mono) com parada por silêncio, por comando ou por tempo."""

from __future__ import annotations

import asyncio
import tempfile
import time
import wave
from pathlib import Path
from typing import Protocol

SAMPLE_RATE = 16000
BLOCK = 1600  # 100 ms


class Recorder(Protocol):
    async def record(self, stop: asyncio.Event, max_seconds: float, silence_seconds: float) -> Path: ...
    async def record_fixed(self, seconds: float) -> Path: ...


class MicRecorder:
    def __init__(self, work_dir: Path, min_voice_rms: float = 500.0) -> None:
        self.work_dir = work_dir
        self.min_voice_rms = min_voice_rms

    def _write(self, frames: list[bytes]) -> Path:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(suffix=".wav", dir=self.work_dir, delete=False)
        handle.close()
        with wave.open(handle.name, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(b"".join(frames))
        return Path(handle.name)

    async def record(self, stop: asyncio.Event, max_seconds: float, silence_seconds: float) -> Path:
        import numpy as np
        import sounddevice as sd

        frames: list[bytes] = []
        levels: list[float] = []

        def callback(indata, _frames, _time, _status) -> None:
            frames.append(indata.tobytes())
            levels.append(float(np.sqrt(np.mean(indata.astype(np.float32) ** 2))))

        started = time.monotonic()
        speech_started = False
        last_voice = started
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK, callback=callback):
            while not stop.is_set():
                await asyncio.sleep(0.1)
                now = time.monotonic()
                if now - started >= max_seconds:
                    break
                if len(levels) < 5:
                    continue
                noise_floor = sorted(levels[:5])[2]
                threshold = max(self.min_voice_rms, min(noise_floor * 3, self.min_voice_rms * 4))
                if levels[-1] > threshold:
                    speech_started = True
                    last_voice = now
                elif speech_started and now - last_voice >= silence_seconds:
                    break
        return self._write(frames)

    async def record_fixed(self, seconds: float) -> Path:
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(seconds, stop.set)
        return await self.record(stop, max_seconds=seconds + 1, silence_seconds=10_000)
