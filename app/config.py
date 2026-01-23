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
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    llm_timeout_seconds: float
    token_store_path: str | None
    pending_actions_path: str | None
    notes_store_path: str | None
    spotify_access_token: str | None
    spotify_device_id: str | None
    spotify_base_url: str | None


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
        llm_base_url=os.getenv("LLM_BASE_URL"),
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL"),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        token_store_path=os.getenv("TOKEN_STORE_PATH"),
        pending_actions_path=os.getenv("PENDING_ACTIONS_PATH"),
        notes_store_path=os.getenv("NOTES_STORE_PATH"),
        spotify_access_token=os.getenv("SPOTIFY_ACCESS_TOKEN"),
        spotify_device_id=os.getenv("SPOTIFY_DEVICE_ID"),
        spotify_base_url=os.getenv("SPOTIFY_BASE_URL"),
    )
