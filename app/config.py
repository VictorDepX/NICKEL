from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    google_client_id: str | None
    google_client_secret: str | None
    google_redirect_uri: str | None
    google_scopes: tuple[str, ...]
    oauth_token_key: str | None


DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)


def get_settings() -> Settings:
    scopes = tuple(
        scope.strip()
        for scope in os.getenv("GOOGLE_SCOPES", "").split(",")
        if scope.strip()
    )
    return Settings(
        google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI"),
        google_scopes=scopes or DEFAULT_SCOPES,
        oauth_token_key=os.getenv("OAUTH_TOKEN_KEY"),
    )
