from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.oauth import get_token_store

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_TOKEN_STORE_KEY = "spotify_default"


@dataclass
class SpotifyOAuthSession:
    state: str
    authorization_url: str


class SpotifyStateStore:
    def __init__(self) -> None:
        self._states: set[str] = set()

    def add(self, state: str) -> None:
        self._states.add(state)

    def consume(self, state: str) -> bool:
        if state in self._states:
            self._states.remove(state)
            return True
        return False


spotify_state_store = SpotifyStateStore()


def _require_spotify_oauth_config(settings: Settings) -> None:
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "spotify_oauth_not_configured",
                    "message": "Spotify OAuth client credentials are missing.",
                }
            },
        )
    if not settings.spotify_redirect_uri:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "spotify_oauth_not_configured",
                    "message": "SPOTIFY_REDIRECT_URI is missing.",
                }
            },
        )


def _parse_expiry(token_payload: dict[str, Any]) -> datetime | None:
    expires_in = token_payload.get("expires_in")
    if not isinstance(expires_in, int):
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def _store_spotify_token(settings: Settings, token_payload: dict[str, Any]) -> None:
    token_store = get_token_store(settings)
    scopes_raw = token_payload.get("scope", "")
    scopes = [scope for scope in str(scopes_raw).split(" ") if scope]
    expiry = _parse_expiry(token_payload)
    existing = token_store.get(SPOTIFY_TOKEN_STORE_KEY) or {}
    token_store.store(
        SPOTIFY_TOKEN_STORE_KEY,
        {
            "access_token": token_payload.get("access_token"),
            "refresh_token": token_payload.get("refresh_token") or existing.get("refresh_token"),
            "expiry": expiry.isoformat() if expiry else None,
            "scopes": scopes or existing.get("scopes") or list(settings.spotify_scopes),
        },
    )


def start_spotify_oauth(settings: Settings) -> SpotifyOAuthSession:
    _require_spotify_oauth_config(settings)
    state = token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": settings.spotify_client_id,
        "scope": " ".join(settings.spotify_scopes),
        "redirect_uri": settings.spotify_redirect_uri,
        "state": state,
        "show_dialog": "true",
    }
    spotify_state_store.add(state)
    return SpotifyOAuthSession(
        state=state,
        authorization_url=f"{SPOTIFY_AUTH_URL}?{urlencode(params)}",
    )


def exchange_spotify_code(settings: Settings, code: str, state: str) -> dict[str, str]:
    _require_spotify_oauth_config(settings)
    if not spotify_state_store.consume(state):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "invalid_state", "message": "Invalid OAuth state."}},
        )
    try:
        response = httpx.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
            },
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "spotify_oauth_failed",
                    "message": "Failed to exchange Spotify OAuth code.",
                }
            },
        ) from exc
    _store_spotify_token(settings, payload)
    return {"status": "connected"}


def _is_expired(expiry_iso: str | None) -> bool:
    if not expiry_iso:
        return True
    expiry = datetime.fromisoformat(expiry_iso)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= datetime.now(timezone.utc) + timedelta(seconds=60)


def get_spotify_access_token(settings: Settings) -> str:
    if settings.spotify_access_token:
        return settings.spotify_access_token

    try:
        token_store = get_token_store(settings)
    except HTTPException as exc:
        if exc.status_code == 500 and exc.detail["error"]["code"] == "oauth_not_configured":
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "spotify_not_configured",
                        "message": "SPOTIFY_ACCESS_TOKEN is missing.",
                    }
                },
            ) from exc
        raise

    token = token_store.get(SPOTIFY_TOKEN_STORE_KEY)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "spotify_not_connected",
                    "message": "Spotify OAuth tokens not found.",
                }
            },
        )

    if _is_expired(token.get("expiry")):
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "code": "spotify_token_expired",
                        "message": "Spotify access token expired and no refresh token is available.",
                    }
                },
            )
        _require_spotify_oauth_config(settings)
        try:
            response = httpx.post(
                SPOTIFY_TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                auth=(settings.spotify_client_id, settings.spotify_client_secret),
                timeout=10,
            )
            response.raise_for_status()
            refreshed = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "code": "spotify_token_expired",
                        "message": "Failed to refresh Spotify access token.",
                    }
                },
            ) from exc
        _store_spotify_token(settings, refreshed)
        token = token_store.get(SPOTIFY_TOKEN_STORE_KEY) or {}

    access_token = token.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "spotify_not_connected",
                    "message": "Spotify access token is unavailable.",
                }
            },
        )
    return str(access_token)
