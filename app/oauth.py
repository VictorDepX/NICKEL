from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import Settings


@dataclass
class OAuthSession:
    state: str
    authorization_url: str


class TokenStore:
    def __init__(self, key: str, storage_path: Path | None) -> None:
        self._fernet = Fernet(key.encode("utf-8"))
        self._tokens: dict[str, bytes] = {}
        self._storage_path = storage_path
        self._load()

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._tokens = {
                user_id: bytes.fromhex(value) for user_id, value in data.items()
            }
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "token_store_corrupt",
                        "message": "Stored token cannot be loaded.",
                    }
                },
            ) from exc

    def _persist(self) -> None:
        if not self._storage_path:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = {user_id: token.hex() for user_id, token in self._tokens.items()}
        self._storage_path.write_text(json.dumps(encoded), encoding="utf-8")

    def store(self, user_id: str, token: dict[str, Any]) -> None:
        encoded = json.dumps(token).encode("utf-8")
        self._tokens[user_id] = self._fernet.encrypt(encoded)
        self._persist()

    def get(self, user_id: str) -> dict[str, Any] | None:
        encrypted = self._tokens.get(user_id)
        if not encrypted:
            return None
        try:
            decoded = self._fernet.decrypt(encrypted)
        except InvalidToken:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "token_store_corrupt",
                        "message": "Stored token cannot be decrypted.",
                    }
                },
            )
        return json.loads(decoded.decode("utf-8"))


class StateStore:
    def __init__(self) -> None:
        self._states: set[str] = set()

    def add(self, state: str) -> None:
        self._states.add(state)

    def consume(self, state: str) -> bool:
        if state in self._states:
            self._states.remove(state)
            return True
        return False


_token_store: TokenStore | None = None
state_store = StateStore()


def build_flow(settings: Settings) -> Flow:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "oauth_not_configured",
                    "message": "Google OAuth credentials are missing.",
                }
            },
        )
    if not settings.google_redirect_uri:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "oauth_not_configured",
                    "message": "GOOGLE_REDIRECT_URI is missing.",
                }
            },
        )

    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uris": [settings.google_redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=list(settings.google_scopes))
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def get_token_store(settings: Settings) -> TokenStore:
    if not settings.oauth_token_key:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "oauth_not_configured",
                    "message": "OAUTH_TOKEN_KEY is missing.",
                }
            },
        )
    global _token_store
    if _token_store is None:
        storage_path = (
            Path(settings.token_store_path)
            if settings.token_store_path
            else None
        )
        _token_store = TokenStore(settings.oauth_token_key, storage_path)
    return _token_store


def start_oauth(settings: Settings) -> OAuthSession:
    flow = build_flow(settings)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    state_store.add(state)
    return OAuthSession(state=state, authorization_url=authorization_url)


def exchange_code(settings: Settings, code: str, state: str) -> dict[str, Any]:
    if not state_store.consume(state):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "invalid_state",
                    "message": "Invalid OAuth state.",
                }
            },
        )
    flow = build_flow(settings)
    flow.fetch_token(code=code)
    token_store = get_token_store(settings)
    token_store.store(
        "default",
        {
            "access_token": flow.credentials.token,
            "refresh_token": flow.credentials.refresh_token,
            "expiry": flow.credentials.expiry.isoformat()
            if flow.credentials.expiry
            else None,
            "scopes": list(flow.credentials.scopes or []),
        },
    )
    return {"status": "connected"}


def get_credentials(settings: Settings) -> Credentials:
    token_store = get_token_store(settings)
    token = token_store.get("default")
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "not_connected",
                    "message": "OAuth tokens not found.",
                }
            },
        )
    expiry_value = token.get("expiry")
    expiry = datetime.fromisoformat(expiry_value) if expiry_value else None
    if expiry and expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    credentials = Credentials(
        token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=token.get("scopes"),
        expiry=expiry,
    )
    if credentials.expired:
        if not credentials.refresh_token:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "code": "token_expired",
                        "message": "Access token expired and no refresh token is available.",
                    }
                },
            )
        try:
            credentials.refresh(Request())
        except Exception as exc:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "code": "token_expired",
                        "message": "Failed to refresh access token.",
                    }
                },
            ) from exc
        token_store.store(
            "default",
            {
                "access_token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "expiry": credentials.expiry.isoformat()
                if credentials.expiry
                else None,
                "scopes": list(credentials.scopes or []),
            },
        )
    return credentials
