"""Informações do host usadas pelo `nickel doctor`."""

from __future__ import annotations

from pathlib import Path

_ASSET_TAG = Path("/sys/class/dmi/id/chassis_asset_tag")
_MEMINFO = Path("/proc/meminfo")


def is_oracle_cloud(asset_tag_path: Path = _ASSET_TAG) -> bool:
    try:
        return "oraclecloud" in asset_tag_path.read_text().strip().lower()
    except OSError:
        return False


def memory_used_percent(meminfo: str | None = None) -> float | None:
    """Uso de memória como a maioria dos monitores calcula: (total - disponível) / total."""
    if meminfo is None:
        try:
            meminfo = _MEMINFO.read_text()
        except OSError:
            return None
    values: dict[str, int] = {}
    for line in meminfo.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key.strip()] = int(parts[0])
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    if not total or available is None:
        return None
    return 100.0 * (total - available) / total
