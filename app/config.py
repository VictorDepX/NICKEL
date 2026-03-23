from __future__ import annotations

import os
from dataclasses import dataclass, field


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
    llm_max_tokens: int
    llm_temperature: float
    llm_retry_count: int
    llm_retry_backoff_ms: int
    llm_enable_native_tools: bool
    token_store_path: str | None
    pending_actions_path: str | None
    notes_store_path: str | None
    tasks_store_path: str | None
    memory_store_path: str | None
    audit_store_path: str | None
    spotify_access_token: str | None = None
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    spotify_redirect_uri: str | None = None
    spotify_scopes: tuple[str, ...] = field(default_factory=tuple)
    spotify_device_id: str | None = None
    spotify_base_url: str | None = None


DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)

DEFAULT_SPOTIFY_SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
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
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", "llama-3.1-8b-instant"),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "512")),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        llm_retry_count=int(os.getenv("LLM_RETRY_COUNT", "2")),
        llm_retry_backoff_ms=int(os.getenv("LLM_RETRY_BACKOFF_MS", "250")),
        llm_enable_native_tools=(
            os.getenv("LLM_ENABLE_NATIVE_TOOLS", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        ),
        token_store_path=os.getenv("TOKEN_STORE_PATH"),
        pending_actions_path=os.getenv("PENDING_ACTIONS_PATH"),
        notes_store_path=os.getenv("NOTES_STORE_PATH"),
        tasks_store_path=os.getenv("TASKS_STORE_PATH"),
        memory_store_path=os.getenv("MEMORY_STORE_PATH"),
        audit_store_path=os.getenv("AUDIT_STORE_PATH"),
        spotify_access_token=os.getenv("SPOTIFY_ACCESS_TOKEN"),
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        spotify_redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        spotify_scopes=tuple(
            scope.strip()
            for scope in os.getenv("SPOTIFY_SCOPES", "").split(",")
            if scope.strip()
        )
        or DEFAULT_SPOTIFY_SCOPES,
        spotify_device_id=os.getenv("SPOTIFY_DEVICE_ID"),
        spotify_base_url=os.getenv("SPOTIFY_BASE_URL"),
    )
