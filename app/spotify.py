from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.spotify_oauth import ensure_spotify_ready


@dataclass
class SpotifyPlaybackTargetCheck:
    status: str
    access_token: str | None = None
    base_url: str | None = None
    device_id: str | None = None
    devices: list[dict[str, Any]] | None = None
    service: str = "spotify"
    code: str | None = None
    message: str | None = None
    authorization_url: str | None = None
    state: str | None = None

    def to_response(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "service": self.service,
            "code": self.code,
            "message": self.message,
            "authorization_url": self.authorization_url,
            "state": self.state,
            "device_id": self.device_id,
            "devices": self.devices,
        }


def _base_url(settings: Settings) -> str:
    return settings.spotify_base_url or "https://api.spotify.com/v1"


def _raise_spotify_http_error(exc: httpx.HTTPError, *, default_code: str, default_message: str) -> None:
    response = exc.response if isinstance(exc, httpx.HTTPStatusError) else None
    if response is not None:
        status_code = response.status_code
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = default_message
        code = default_code
        error_payload = payload.get("error") if isinstance(payload, dict) else None
        reason = error_payload.get("reason") if isinstance(error_payload, dict) else None
        api_message = error_payload.get("message") if isinstance(error_payload, dict) else None
        if status_code == 401:
            code = "spotify_token_expired"
            message = "Spotify access token expired or is invalid."
        elif status_code == 403:
            code = "spotify_playback_unavailable"
            message = str(api_message or "Spotify playback is unavailable for this account or device.")
        elif status_code == 404 or reason == "NO_ACTIVE_DEVICE":
            code = "spotify_no_active_device"
            message = str(api_message or "No active Spotify playback device is available.")
        raise HTTPException(status_code=status_code, detail={"error": {"code": code, "message": message}}) from exc
    raise HTTPException(
        status_code=502,
        detail={"error": {"code": default_code, "message": default_message}},
    ) from exc


def _fetch_devices(access_token: str, base_url: str) -> list[dict[str, Any]]:
    try:
        response = httpx.request(
            "GET",
            f"{base_url.rstrip('/')}/me/player/devices",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        _raise_spotify_http_error(
            exc,
            default_code="spotify_devices_request_failed",
            default_message="Failed to list Spotify playback devices.",
        )
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
        (device for device in devices if str(device.get("type", "")).lower() == "smartphone"),
        None,
    )
    if smartphone_device:
        return smartphone_device.get("id")
    if devices:
        return devices[0].get("id")
    return None


def ensure_spotify_playback_ready(settings: Settings) -> SpotifyPlaybackTargetCheck:
    connection = ensure_spotify_ready(settings)
    if connection.status != "ready" or not connection.access_token:
        return SpotifyPlaybackTargetCheck(
            status=connection.status,
            access_token=None,
            base_url=_base_url(settings),
            code=connection.code,
            message=connection.message,
            authorization_url=connection.authorization_url,
            state=connection.state,
        )

    base_url = _base_url(settings)
    if settings.spotify_device_id:
        devices = _fetch_devices(connection.access_token, base_url)
        configured = next((device for device in devices if device.get("id") == settings.spotify_device_id), None)
        if configured is None:
            return SpotifyPlaybackTargetCheck(
                status="needs_device",
                access_token=connection.access_token,
                base_url=base_url,
                code="spotify_device_not_configured",
                message="The configured Spotify device was not found. Open Spotify on the target device and try again.",
                devices=devices,
            )
        return SpotifyPlaybackTargetCheck(
            status="ready",
            access_token=connection.access_token,
            base_url=base_url,
            device_id=settings.spotify_device_id,
            devices=devices,
            code="ready",
            message="Spotify playback is ready.",
        )

    devices = _fetch_devices(connection.access_token, base_url)
    if not devices:
        return SpotifyPlaybackTargetCheck(
            status="needs_device",
            access_token=connection.access_token,
            base_url=base_url,
            code="spotify_no_active_device",
            message="No Spotify playback device is available. Open Spotify on a device and try again.",
            devices=[],
        )
    device_id = _select_device_id(devices)
    if not device_id:
        return SpotifyPlaybackTargetCheck(
            status="needs_device",
            access_token=connection.access_token,
            base_url=base_url,
            code="spotify_no_active_device",
            message="Spotify found devices but none is ready for playback yet.",
            devices=devices,
        )
    return SpotifyPlaybackTargetCheck(
        status="ready",
        access_token=connection.access_token,
        base_url=base_url,
        device_id=device_id,
        devices=devices,
        code="ready",
        message="Spotify playback is ready.",
    )


def check_spotify_playback_target(settings: Settings) -> SpotifyPlaybackTargetCheck:
    return ensure_spotify_playback_ready(settings)


def _spotify_request(
    access_token: str,
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    device_id: str | None = None,
) -> None:
    params: dict[str, str] = {}
    if device_id:
        params["device_id"] = device_id
    try:
        response = httpx.request(
            method,
            f"{base_url.rstrip('/')}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or None,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        _raise_spotify_http_error(
            exc,
            default_code="spotify_request_failed",
            default_message="Failed to call Spotify API.",
        )


def play(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    target = ensure_spotify_playback_ready(settings)
    if target.status != "ready" or not target.access_token or not target.base_url:
        return target.to_response()
    body: dict[str, Any] = {}
    for key in ("context_uri", "uris", "offset", "position_ms"):
        if key in payload:
            body[key] = payload[key]
    _spotify_request(
        target.access_token,
        target.base_url,
        "PUT",
        "/me/player/play",
        payload=body or None,
        device_id=target.device_id,
    )
    return {"status": "ok"}


def pause(settings: Settings, _payload: dict[str, Any]) -> dict[str, Any]:
    target = ensure_spotify_playback_ready(settings)
    if target.status != "ready" or not target.access_token or not target.base_url:
        return target.to_response()
    _spotify_request(
        target.access_token,
        target.base_url,
        "PUT",
        "/me/player/pause",
        device_id=target.device_id,
    )
    return {"status": "ok"}


def skip(settings: Settings, _payload: dict[str, Any]) -> dict[str, Any]:
    target = ensure_spotify_playback_ready(settings)
    if target.status != "ready" or not target.access_token or not target.base_url:
        return target.to_response()
    _spotify_request(
        target.access_token,
        target.base_url,
        "POST",
        "/me/player/next",
        device_id=target.device_id,
    )
    return {"status": "ok"}
