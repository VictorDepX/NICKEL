"""Reprodução de WAV multiplataforma: winsound no Windows, pw-play/paplay/aplay nos demais."""

from __future__ import annotations

import asyncio
import logging
import shutil
import struct
import sys
import wave
from pathlib import Path

log = logging.getLogger(__name__)


class TTSError(RuntimeError):
    """Falha ao sintetizar ou reproduzir fala."""


_PLAYERS = (["pw-play"], ["paplay"], ["aplay", "-q"])

# Folga depois da duração do WAV: o PlaySound assíncrono leva um instante para começar.
_WINDOWS_TAIL_SECONDS = 0.15

_process: asyncio.subprocess.Process | None = None


def is_riff_wave(data: bytes) -> bool:
    """Cabeçalho `RIFF....WAVE`, qualquer que seja o formato das amostras (PCM, float, extensível)."""
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _riff_duration(data: bytes) -> float:
    """Duração lida dos chunks `fmt ` (taxa de bytes) e `data` (tamanho). Serve para WAV float."""
    if not is_riff_wave(data):
        raise TTSError("arquivo não é WAV (cabeçalho RIFF/WAVE ausente)")
    byte_rate = None
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset:offset + 4]
        (size,) = struct.unpack("<I", data[offset + 4:offset + 8])
        body = offset + 8
        if chunk_id == b"fmt " and size >= 12:
            (byte_rate,) = struct.unpack("<I", data[body + 8:body + 12])
        elif chunk_id == b"data":
            if not byte_rate:
                break
            return min(size, len(data) - body) / byte_rate
        offset = body + size + (size & 1)
    raise TTSError("WAV sem chunks `fmt `/`data` legíveis")


def wav_duration(path: Path) -> float:
    """Duração em segundos: `wave` (quadros/taxa); WAV que ele recusa cai na leitura do cabeçalho."""
    try:
        with wave.open(str(path), "rb") as reader:
            return reader.getnframes() / reader.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        try:
            return _riff_duration(Path(path).read_bytes())
        except TTSError as fallback:
            raise TTSError(f"não foi possível ler a duração do WAV: {exc}; {fallback}") from exc
    except OSError as exc:
        raise TTSError(f"não foi possível abrir o WAV: {exc}") from exc


def discard(path: Path) -> None:
    """Apaga um temporário; arquivo travado (Windows) não troca o resultado nem o cancelamento."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        log.debug("Não foi possível apagar %s: %s", path, exc)


def _windows_stop() -> None:
    import winsound

    try:
        winsound.PlaySound(None, 0)
    except (RuntimeError, OSError):
        log.warning("Não foi possível interromper o áudio.")


async def play_wav(path: Path) -> None:
    """Toca o WAV e só retorna quando termina (ou é interrompido)."""
    global _process
    if sys.platform == "win32":
        import winsound

        duration = wav_duration(path)
        flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        try:
            winsound.PlaySound(str(path), flags)
        except (RuntimeError, OSError) as exc:
            raise TTSError(f"Falha ao reproduzir o áudio no Windows: {exc}") from exc
        try:
            await asyncio.sleep(duration + _WINDOWS_TAIL_SECONDS)
        except asyncio.CancelledError:
            _windows_stop()
            raise
        return
    for player in _PLAYERS:
        if shutil.which(player[0]):
            try:
                process = await asyncio.create_subprocess_exec(*player, str(path))
            except OSError as exc:
                raise TTSError(f"Falha ao iniciar o player de áudio ({player[0]}): {exc}") from exc
            _process = process
            try:
                await process.wait()
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.terminate()
                raise
            finally:
                if _process is process:
                    _process = None
            return
    raise TTSError("Nenhum player de áudio encontrado (pw-play, paplay, aplay).")


def stop_playback() -> None:
    """Interrompe a reprodução em andamento, se houver."""
    if sys.platform == "win32":
        _windows_stop()
        return
    if _process is not None and _process.returncode is None:
        _process.terminate()
