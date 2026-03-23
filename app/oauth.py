from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import Settings


@dataclass
class OAuthSession:
    state: str
    authorization_url: str


@dataclass
class GoogleConnectionCheck:
    status: str
    authorization_url: str | None = None
    state: str | None = None
    missing_config: list[str] | None = None
    missing_scopes: list[str] | None = None
    credentials: Credentials | None = None

    def to_response(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("credentials", None)
        return payload


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



def _missing_google_config(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not settings.google_client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not settings.google_client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not settings.google_redirect_uri:
        missing.append("GOOGLE_REDIRECT_URI")
    if not settings.oauth_token_key:
        missing.append("OAUTH_TOKEN_KEY")
    return missing



def build_flow(settings: Settings, scopes: tuple[str, ...] | list[str] | None = None) -> Flow:
    missing_config = _missing_google_config(settings)
    if missing_config:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "oauth_not_configured",
                    "message": "Google OAuth credentials are missing.",
                    "missing_config": missing_config,
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
    flow = Flow.from_client_config(
        client_config,
        scopes=list(scopes or settings.google_scopes),
    )
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
        storage_path = Path(settings.token_store_path) if settings.token_store_path else None
        _token_store = TokenStore(settings.oauth_token_key, storage_path)
    return _token_store



def start_oauth(settings: Settings, scopes: tuple[str, ...] | list[str] | None = None) -> OAuthSession:
    flow = build_flow(settings, scopes=scopes) if scopes is not None else build_flow(settings)
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
            "expiry": flow.credentials.expiry.isoformat() if flow.credentials.expiry else None,
            "scopes": list(flow.credentials.scopes or []),
        },
    )
    return {"status": "connected"}



def _build_credentials(settings: Settings, token: dict[str, Any]) -> Credentials:
    expiry_value = token.get("expiry")
    expiry = datetime.fromisoformat(expiry_value) if expiry_value else None
    if expiry and expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    return Credentials(
        token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=token.get("scopes"),
        expiry=expiry,
    )



def check_google_connection(
    settings: Settings,
    required_scopes: tuple[str, ...] | list[str],
) -> GoogleConnectionCheck:
    required = list(dict.fromkeys(required_scopes))
    missing_config = _missing_google_config(settings)
    if missing_config:
        return GoogleConnectionCheck(
            status="needs_configuration",
            missing_config=missing_config,
            missing_scopes=required or None,
        )

    token_store = get_token_store(settings)
    token = token_store.get("default")
    if not token:
        session = start_oauth(settings, scopes=required)
        return GoogleConnectionCheck(
            status="needs_connection",
            authorization_url=session.authorization_url,
            state=session.state,
            missing_scopes=required or None,
        )

    credentials = _build_credentials(settings, token)
    if credentials.expired:
        if not credentials.refresh_token:
            session = start_oauth(settings, scopes=required)
            return GoogleConnectionCheck(
                status="needs_reauth",
                authorization_url=session.authorization_url,
                state=session.state,
                missing_scopes=required or None,
            )
        try:
            credentials.refresh(Request())
        except Exception:
            session = start_oauth(settings, scopes=required)
            return GoogleConnectionCheck(
                status="needs_reauth",
                authorization_url=session.authorization_url,
                state=session.state,
                missing_scopes=required or None,
            )
        token_store.store(
            "default",
            {
                "access_token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
                "scopes": list(credentials.scopes or token.get("scopes") or []),
            },
        )

    token_scopes = set(credentials.scopes or token.get("scopes") or [])
    missing_scopes = [scope for scope in required if scope not in token_scopes]
    if missing_scopes:
        requested_scopes = tuple(dict.fromkeys([*settings.google_scopes, *required]))
        session = start_oauth(settings, scopes=requested_scopes)
        return GoogleConnectionCheck(
            status="missing_scopes",
            authorization_url=session.authorization_url,
            state=session.state,
            missing_scopes=missing_scopes,
        )

    return GoogleConnectionCheck(status="ready", credentials=credentials)



def require_google_connection(
    settings: Settings,
    required_scopes: tuple[str, ...] | list[str],
) -> Credentials:
    check = check_google_connection(settings, required_scopes)
    if check.status == "ready" and check.credentials is not None:
        return check.credentials
    raise HTTPException(
        status_code=401 if check.status != "needs_configuration" else 500,
        detail={
            "error": {
                "code": check.status,
                "message": "Google Workspace connection is not ready.",
                **check.to_response(),
            }
        },
    )



def get_credentials(settings: Settings) -> Credentials:
    return require_google_connection(settings, settings.google_scopes)
