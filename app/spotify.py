from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.config import Settings


def _require_spotify_config(settings: Settings) -> tuple[str, str | None]:
    if not settings.spotify_access_token:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "spotify_not_configured",
                    "message": "SPOTIFY_ACCESS_TOKEN is missing.",
                }
            },
    )
    base_url = settings.spotify_base_url or "https://api.spotify.com/v1"
    return base_url, settings.spotify_device_id


def _fetch_devices(settings: Settings, base_url: str) -> list[dict[str, Any]]:
    try:
        response = httpx.request(
            "GET",
            f"{base_url.rstrip('/')}/me/player/devices",
            headers={"Authorization": f"Bearer {settings.spotify_access_token}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "spotify_request_failed",
                    "message": "Failed to call Spotify API.",
                }
            },
        ) from exc
    return payload.get("devices", [])


def _select_device_id(devices: list[dict[str, Any]]) -> str | None:
    smartphone_active = next(
        (
            device
            for device in devices
            if device.get("is_active")
            and str(device.get("type", "")).lower() == "smartphone"
        ),
        None,
    )
    if smartphone_active:
        return smartphone_active.get("id")
    active_device = next((device for device in devices if device.get("is_active")), None)
    if active_device:
        return active_device.get("id")
    smartphone_device = next(
        (
            device
            for device in devices
            if str(device.get("type", "")).lower() == "smartphone"
        ),
        None,
    )
    if smartphone_device:
        return smartphone_device.get("id")
    if devices:
        return devices[0].get("id")
    return None


def _spotify_request(
    settings: Settings,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    allow_device_lookup: bool = True,
) -> None:
    base_url, device_id = _require_spotify_config(settings)
    if allow_device_lookup and not device_id:
        devices = _fetch_devices(settings, base_url)
        device_id = _select_device_id(devices)
    params: dict[str, str] = {}
    if device_id:
        params["device_id"] = device_id
    try:
        response = httpx.request(
            method,
            f"{base_url.rstrip('/')}{path}",
            headers={"Authorization": f"Bearer {settings.spotify_access_token}"},
            params=params or None,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "spotify_request_failed",
                    "message": "Failed to call Spotify API.",
                }
            },
        ) from exc


def play(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for key in ("context_uri", "uris", "offset", "position_ms"):
        if key in payload:
            body[key] = payload[key]
    _spotify_request(settings, "PUT", "/me/player/play", payload=body or None)
    return {"status": "ok"}


def pause(settings: Settings, _payload: dict[str, Any]) -> dict[str, Any]:
    _spotify_request(settings, "PUT", "/me/player/pause")
    return {"status": "ok"}


def skip(settings: Settings, _payload: dict[str, Any]) -> dict[str, Any]:
    _spotify_request(settings, "POST", "/me/player/next")
    return {"status": "ok"}
