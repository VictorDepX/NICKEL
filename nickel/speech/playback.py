"""Reprodução de WAV multiplataforma: winsound no Windows, pw-play/paplay/aplay nos demais."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_PLAYERS = (["pw-play"], ["paplay"], ["aplay", "-q"])

_process: asyncio.subprocess.Process | None = None


async def play_wav(path: Path) -> None:
    """Toca o WAV e só retorna quando termina (ou é interrompido)."""
    global _process
    if sys.platform == "win32":
        import winsound

        await asyncio.to_thread(winsound.PlaySound, str(path), winsound.SND_FILENAME)
        return
    for player in _PLAYERS:
        if shutil.which(player[0]):
            process = await asyncio.create_subprocess_exec(*player, str(path))
            _process = process
            try:
                await process.wait()
            finally:
                if _process is process:
                    _process = None
            return
    log.warning("Nenhum player de áudio encontrado (pw-play, paplay, aplay).")


def stop_playback() -> None:
    """Interrompe a reprodução em andamento, se houver."""
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
        return
    if _process is not None and _process.returncode is None:
        _process.terminate()
