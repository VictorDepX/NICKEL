"""Memória do sistema para o Monitor: amostra a RAM a cada poucos segundos e guarda uma janela curta.

Usa `psutil` quando instalado; sem ele, o painel some (`available=False`) em vez de mostrar dado inventado.
Processos acompanhados: o llama-server (modelo local) e o próprio NICKEL.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Any, Callable

SAMPLE_SECONDS = 5.0
WINDOW = 360  # 30 min a cada 5 s

# Processos com nome de executável que contém um destes trechos (minúsculas).
WATCHED = {"llama": ("llama-server",)}


def _psutil():
    try:
        import psutil
    except ImportError:
        return None
    return psutil


def read_memory(psutil_module: Any = None) -> dict[str, Any] | None:
    """Uma amostra: RAM total/usada/livre do sistema e RSS do llama-server e do NICKEL, em bytes."""
    ps = psutil_module or _psutil()
    if ps is None:
        return None
    vm = ps.virtual_memory()
    llama = 0
    for proc in ps.process_iter(["name", "memory_info"]):
        info = proc.info
        name = str(info.get("name") or "").lower()
        mem = info.get("memory_info")
        if mem is not None and any(part in name for part in WATCHED["llama"]):
            llama += int(mem.rss)
    try:
        nickel = int(ps.Process(os.getpid()).memory_info().rss)
    except Exception:
        nickel = 0
    return {
        "t": time.time(),
        "total": int(vm.total),
        "used": int(vm.total - vm.available),
        "available": int(vm.available),
        "llama": llama,
        "nickel": nickel,
    }


class MemorySampler:
    def __init__(self, reader: Callable[[], dict[str, Any] | None] = read_memory, window: int = WINDOW) -> None:
        self._reader = reader
        self.samples: deque[dict[str, Any]] = deque(maxlen=window)

    def sample(self) -> dict[str, Any] | None:
        try:
            point = self._reader()
        except Exception:
            point = None
        if point is not None:
            self.samples.append(point)
        return point

    def snapshot(self) -> dict[str, Any]:
        if not self.samples and self.sample() is None:
            return {"available": False, "samples": [], "interval_s": SAMPLE_SECONDS}
        return {"available": True, "samples": list(self.samples), "interval_s": SAMPLE_SECONDS}

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.to_thread(self.sample)
            try:
                await asyncio.wait_for(stop.wait(), SAMPLE_SECONDS)
            except asyncio.TimeoutError:
                pass
