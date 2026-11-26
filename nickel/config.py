"""Configuração lida de variáveis de ambiente (e de um `.env`, se existir)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

_TRUE = {"1", "true", "yes", "on", "sim"}


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    return int(raw) if raw not in (None, "") else default


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    return float(raw) if raw not in (None, "") else default


def _str(env: Mapping[str, str], key: str, default: str | None = None) -> str | None:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


@dataclass(frozen=True)
class Settings:
    # Geral
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    timezone: str = "America/Sao_Paulo"

    # LLM: "ollama" (GPU local), "llamacpp" (llama-server local), "openai" (RunPod Serverless / vLLM / outro compatível)
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_api_key: str | None = None
    llm_model: str = "qwen3.6:27b"
    llm_num_ctx: int = 16384
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.3
    llm_think: bool = False
    llm_stream: bool = True
    llm_timeout_seconds: float = 180.0
    llm_retries: int = 2
    llm_keep_alive: str = "30m"
    agent_max_steps: int = 6
    agent_history_messages: int = 16

    # Backend "cloud" opcional (RunPod), usado por workspaces com `backend: cloud`
    llm_cloud_base_url: str | None = None
    llm_cloud_api_key: str | None = None
    llm_cloud_model: str | None = None
    llm_cloud_timeout_seconds: float = 300.0

    # Workspaces (perfis de trabalho sobre o mesmo modelo)
    workspaces_dir: Path = Path("workspaces")
    workspace_default: str = "geral"
    workspace_auto_route: bool = False
    workspace_auto_threshold: int = 2

    # Segredos
    oauth_token_key: str | None = None
    bridge_token: str | None = None

    # Google
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    google_calendar_id: str = "primary"

    # Spotify
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    spotify_redirect_uri: str = "http://127.0.0.1:8000/auth/spotify/callback"
    spotify_device_name: str | None = None
    spotify_market: str = "BR"

    # WhatsApp
    wa_bridge_url: str = "http://127.0.0.1:8002"
    wa_voice_replies: bool = False
    wa_slow_notice_seconds: float = 8.0

    # Obsidian
    obsidian_vault_path: Path | None = None
    obsidian_notes_dir: str = "06 Pensamentos"

    # Voz
    voice_enabled: bool = True
    stt_model: str = "large-v3-turbo"
    stt_device: str = "cuda"
    stt_compute_type: str = "int8_float16"
    stt_language: str = "pt"
    tts_voice_path: Path | None = None
    tts_provider: str = "auto"  # auto | edge | voicestudio | piper | none
    edge_tts_voice: str = "pt-BR-AntonioNeural"
    edge_tts_rate: str = "+0%"
    voicestudio_url: str = ""
    voicestudio_api_key: str = ""
    voicestudio_model: str = "omnivoice"
    voicestudio_voice: str = "default"
    voicestudio_timeout_seconds: float = 900.0  # renders medidos de 3 a 10 min numa GPU intermediária
    voice_max_seconds: int = 30
    voice_silence_seconds: float = 1.5
    voice_notify: bool = True
    voice_open_links: bool = True

    # Música
    music_auto_detect: bool = True
    music_record_seconds: int = 10

    # Lembretes
    reminders_use_calendar: bool = True
    reminder_late_grace_hours: int = 12
    reminder_poll_seconds: int = 15

    extra: dict[str, str] = field(default_factory=dict, compare=False, repr=False)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nickel.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    def with_overrides(self, **changes: object) -> "Settings":
        return replace(self, **changes)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        vault = _str(env, "OBSIDIAN_VAULT_PATH")
        voice = _str(env, "TTS_VOICE_PATH")
        return cls(
            host=_str(env, "NICKEL_HOST", cls.host),
            port=_int(env, "NICKEL_PORT", cls.port),
            data_dir=Path(_str(env, "NICKEL_DATA_DIR", "data")),
            timezone=_str(env, "NICKEL_TIMEZONE", cls.timezone),
            llm_provider=_str(env, "LLM_PROVIDER", cls.llm_provider),
            llm_base_url=_str(env, "LLM_BASE_URL", cls.llm_base_url),
            llm_api_key=_str(env, "LLM_API_KEY"),
            llm_model=_str(env, "LLM_MODEL", cls.llm_model),
            llm_num_ctx=_int(env, "LLM_NUM_CTX", cls.llm_num_ctx),
            llm_max_tokens=_int(env, "LLM_MAX_TOKENS", cls.llm_max_tokens),
            llm_temperature=_float(env, "LLM_TEMPERATURE", cls.llm_temperature),
            llm_think=_bool(env, "LLM_THINK", cls.llm_think),
            llm_stream=_bool(env, "LLM_STREAM", cls.llm_stream),
            llm_timeout_seconds=_float(env, "LLM_TIMEOUT_SECONDS", cls.llm_timeout_seconds),
            llm_retries=_int(env, "LLM_RETRIES", cls.llm_retries),
            llm_keep_alive=_str(env, "LLM_KEEP_ALIVE", cls.llm_keep_alive),
            agent_max_steps=_int(env, "AGENT_MAX_STEPS", cls.agent_max_steps),
            agent_history_messages=_int(env, "AGENT_HISTORY_MESSAGES", cls.agent_history_messages),
            llm_cloud_base_url=_str(env, "LLM_CLOUD_BASE_URL"),
            llm_cloud_api_key=_str(env, "LLM_CLOUD_API_KEY"),
            llm_cloud_model=_str(env, "LLM_CLOUD_MODEL"),
            llm_cloud_timeout_seconds=_float(env, "LLM_CLOUD_TIMEOUT_SECONDS", cls.llm_cloud_timeout_seconds),
            workspaces_dir=Path(_str(env, "WORKSPACES_DIR", "workspaces")).expanduser(),
            workspace_default=_str(env, "WORKSPACE_DEFAULT", cls.workspace_default),
            workspace_auto_route=_bool(env, "WORKSPACE_AUTO_ROUTE", cls.workspace_auto_route),
            workspace_auto_threshold=_int(env, "WORKSPACE_AUTO_THRESHOLD", cls.workspace_auto_threshold),
            oauth_token_key=_str(env, "OAUTH_TOKEN_KEY"),
            bridge_token=_str(env, "BRIDGE_TOKEN"),
            google_client_id=_str(env, "GOOGLE_CLIENT_ID"),
            google_client_secret=_str(env, "GOOGLE_CLIENT_SECRET"),
            google_redirect_uri=_str(env, "GOOGLE_REDIRECT_URI", cls.google_redirect_uri),
            google_calendar_id=_str(env, "GOOGLE_CALENDAR_ID", cls.google_calendar_id),
            spotify_client_id=_str(env, "SPOTIFY_CLIENT_ID"),
            spotify_client_secret=_str(env, "SPOTIFY_CLIENT_SECRET"),
            spotify_redirect_uri=_str(env, "SPOTIFY_REDIRECT_URI", cls.spotify_redirect_uri),
            spotify_device_name=_str(env, "SPOTIFY_DEVICE_NAME"),
            spotify_market=_str(env, "SPOTIFY_MARKET", cls.spotify_market),
            wa_bridge_url=_str(env, "WA_BRIDGE_URL", cls.wa_bridge_url),
            wa_voice_replies=_bool(env, "WA_VOICE_REPLIES", cls.wa_voice_replies),
            wa_slow_notice_seconds=_float(env, "WA_SLOW_NOTICE_SECONDS", cls.wa_slow_notice_seconds),
            obsidian_vault_path=Path(vault).expanduser() if vault else None,
            obsidian_notes_dir=_str(env, "OBSIDIAN_NOTES_DIR", cls.obsidian_notes_dir),
            voice_enabled=_bool(env, "VOICE_ENABLED", cls.voice_enabled),
            stt_model=_str(env, "STT_MODEL", cls.stt_model),
            stt_device=_str(env, "STT_DEVICE", cls.stt_device),
            stt_compute_type=_str(env, "STT_COMPUTE_TYPE", cls.stt_compute_type),
            stt_language=_str(env, "STT_LANGUAGE", cls.stt_language),
            tts_voice_path=Path(voice).expanduser() if voice else None,
            tts_provider=_str(env, "TTS_PROVIDER", cls.tts_provider).lower(),
            edge_tts_voice=_str(env, "EDGE_TTS_VOICE", cls.edge_tts_voice),
            edge_tts_rate=_str(env, "EDGE_TTS_RATE", cls.edge_tts_rate),
            voicestudio_url=_str(env, "VOICESTUDIO_URL", cls.voicestudio_url),
            voicestudio_api_key=_str(env, "VOICESTUDIO_API_KEY", cls.voicestudio_api_key),
            voicestudio_model=_str(env, "VOICESTUDIO_MODEL", cls.voicestudio_model),
            voicestudio_voice=_str(env, "VOICESTUDIO_VOICE", cls.voicestudio_voice),
            voicestudio_timeout_seconds=_float(
                env, "VOICESTUDIO_TIMEOUT_SECONDS", cls.voicestudio_timeout_seconds
            ),
            voice_max_seconds=_int(env, "VOICE_MAX_SECONDS", cls.voice_max_seconds),
            voice_silence_seconds=_float(env, "VOICE_SILENCE_SECONDS", cls.voice_silence_seconds),
            voice_notify=_bool(env, "VOICE_NOTIFY", cls.voice_notify),
            voice_open_links=_bool(env, "VOICE_OPEN_LINKS", cls.voice_open_links),
            music_auto_detect=_bool(env, "MUSIC_AUTO_DETECT", cls.music_auto_detect),
            music_record_seconds=_int(env, "MUSIC_RECORD_SECONDS", cls.music_record_seconds),
            reminders_use_calendar=_bool(env, "REMINDERS_USE_CALENDAR", cls.reminders_use_calendar),
            reminder_late_grace_hours=_int(env, "REMINDER_LATE_GRACE_HOURS", cls.reminder_late_grace_hours),
            reminder_poll_seconds=_int(env, "REMINDER_POLL_SECONDS", cls.reminder_poll_seconds),
        )


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Carrega o `.env` (sem sobrescrever variáveis já definidas) e lê as configurações."""
    if env_file and Path(env_file).exists():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    return Settings.from_env()
