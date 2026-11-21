"""Reprodução de WAV multiplataforma: winsound no Windows, pw-play/paplay/aplay nos demais."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)


class TTSError(RuntimeError):
    """Falha ao sintetizar ou reproduzir fala."""


_PLAYERS = (["pw-play"], ["paplay"], ["aplay", "-q"])

_process: asyncio.subprocess.Process | None = None


async def play_wav(path: Path) -> None:
    """Toca o WAV e só retorna quando termina (ou é interrompido)."""
    global _process
    if sys.platform == "win32":
        import winsound

        try:
            await asyncio.to_thread(winsound.PlaySound, str(path), winsound.SND_FILENAME)
        except asyncio.CancelledError:
            stop_playback()
            raise
        except (RuntimeError, OSError) as exc:
            raise TTSError(f"Falha ao reproduzir o áudio no Windows: {exc}") from exc
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
            finally:
                if _process is process:
                    _process = None
            return
    raise TTSError("Nenhum player de áudio encontrado (pw-play, paplay, aplay).")


def stop_playback() -> None:
    """Interrompe a reprodução em andamento, se houver."""
    if sys.platform == "win32":
        import winsound

        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except (RuntimeError, OSError):
            log.warning("Não foi possível interromper o áudio.")
        return
    if _process is not None and _process.returncode is None:
        _process.terminate()
