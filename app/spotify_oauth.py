from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.oauth import get_token_store

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_TOKEN_STORE_KEY = "spotify_default"
SpotifyConnectionStatus = Literal[
    "ready", "needs_configuration", "needs_connection", "token_expired"
]


@dataclass
class SpotifyOAuthSession:
    state: str
    authorization_url: str


@dataclass
class SpotifyConnectionCheck:
    status: SpotifyConnectionStatus
    service: str = "spotify"
    access_token: str | None = None
    authorization_url: str | None = None
    state: str | None = None
    code: str | None = None
    message: str | None = None
    missing_config: list[str] | None = None

    def to_response(self) -> dict[str, Any]:
        return asdict(self)


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


def _missing_spotify_config(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not settings.oauth_token_key and not settings.spotify_access_token:
        missing.append("OAUTH_TOKEN_KEY")
    if not settings.spotify_client_id and not settings.spotify_access_token:
        missing.append("SPOTIFY_CLIENT_ID")
    if not settings.spotify_client_secret and not settings.spotify_access_token:
        missing.append("SPOTIFY_CLIENT_SECRET")
    if not settings.spotify_redirect_uri and not settings.spotify_access_token:
        missing.append("SPOTIFY_REDIRECT_URI")
    return missing


def _has_oauth_client_config(settings: Settings) -> bool:
    return bool(
        settings.spotify_client_id
        and settings.spotify_client_secret
        and settings.spotify_redirect_uri
    )


def _build_spotify_oauth_session(settings: Settings) -> SpotifyOAuthSession:
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


def _authorization_details(settings: Settings) -> dict[str, str] | None:
    if not _has_oauth_client_config(settings):
        return None
    session = _build_spotify_oauth_session(settings)
    return {
        "authorization_url": session.authorization_url,
        "state": session.state,
    }


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
    return _build_spotify_oauth_session(settings)


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


def _refresh_spotify_token(settings: Settings, refresh_token: str) -> dict[str, Any]:
    _require_spotify_oauth_config(settings)
    response = httpx.post(
        SPOTIFY_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(settings.spotify_client_id, settings.spotify_client_secret),
        timeout=10,
    )
    response.raise_for_status()
    refreshed = response.json()
    _store_spotify_token(settings, refreshed)
    token_store = get_token_store(settings)
    return token_store.get(SPOTIFY_TOKEN_STORE_KEY) or {}


def ensure_spotify_ready(settings: Settings) -> SpotifyConnectionCheck:
    if settings.spotify_access_token:
        return SpotifyConnectionCheck(
            status="ready",
            code="ready",
            message="Spotify connection is ready.",
            access_token=settings.spotify_access_token,
        )

    authorization_details = _authorization_details(settings)
    token: dict[str, Any] | None = None
    if settings.oauth_token_key:
        token_store = get_token_store(settings)
        token = token_store.get(SPOTIFY_TOKEN_STORE_KEY)

    missing_config = _missing_spotify_config(settings)
    if not token and missing_config:
        return SpotifyConnectionCheck(
            status="needs_configuration",
            code="spotify_not_configured",
            message="Spotify credentials are missing on the server.",
            missing_config=missing_config,
            authorization_url=authorization_details and authorization_details["authorization_url"],
            state=authorization_details and authorization_details["state"],
        )

    if not token:
        return SpotifyConnectionCheck(
            status="needs_connection",
            code="spotify_not_connected",
            message="Connect your Spotify account to continue.",
            authorization_url=authorization_details and authorization_details["authorization_url"],
            state=authorization_details and authorization_details["state"],
        )

    if _is_expired(token.get("expiry")):
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            return SpotifyConnectionCheck(
                status="token_expired",
                code="spotify_token_expired",
                message="Spotify token expired and no refresh token is available.",
                authorization_url=authorization_details and authorization_details["authorization_url"],
                state=authorization_details and authorization_details["state"],
            )
        if not _has_oauth_client_config(settings):
            return SpotifyConnectionCheck(
                status="needs_configuration",
                code="spotify_oauth_not_configured",
                message="Spotify OAuth client credentials are missing for token refresh.",
                missing_config=[
                    name
                    for name, value in (
                        ("SPOTIFY_CLIENT_ID", settings.spotify_client_id),
                        ("SPOTIFY_CLIENT_SECRET", settings.spotify_client_secret),
                        ("SPOTIFY_REDIRECT_URI", settings.spotify_redirect_uri),
                    )
                    if not value
                ],
            )
        try:
            token = _refresh_spotify_token(settings, str(refresh_token))
        except (httpx.HTTPError, ValueError):
            return SpotifyConnectionCheck(
                status="token_expired",
                code="spotify_token_expired",
                message="Failed to refresh Spotify access token.",
                authorization_url=authorization_details and authorization_details["authorization_url"],
                state=authorization_details and authorization_details["state"],
            )

    access_token = token.get("access_token")
    if not access_token:
        return SpotifyConnectionCheck(
            status="needs_connection",
            code="spotify_not_connected",
            message="Spotify access token is unavailable.",
            authorization_url=authorization_details and authorization_details["authorization_url"],
            state=authorization_details and authorization_details["state"],
        )
    return SpotifyConnectionCheck(
        status="ready",
        code="ready",
        message="Spotify connection is ready.",
        access_token=str(access_token),
    )


def check_spotify_connection(settings: Settings) -> SpotifyConnectionCheck:
    return ensure_spotify_ready(settings)


def get_spotify_access_token(settings: Settings) -> str:
    connection = ensure_spotify_ready(settings)
    if connection.status == "ready" and connection.access_token:
        return connection.access_token

    status_code = 500 if connection.status == "needs_configuration" else 401
    raise HTTPException(status_code=status_code, detail={"error": connection.to_response()})
