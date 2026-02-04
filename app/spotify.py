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


def _spotify_request(
    settings: Settings, method: str, path: str, payload: dict[str, Any] | None = None
) -> None:
    base_url, device_id = _require_spotify_config(settings)
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
