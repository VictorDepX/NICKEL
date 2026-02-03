from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import Settings


_SYSTEM_PROMPT_PATH = Path("docs/Nickel/system_prompt_text.md")


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are Nickel, an adult, pragmatic personal assistant."


def _build_messages(user_message: str, forced_tool: str | None) -> list[dict[str, str]]:
    system_prompt = _load_system_prompt()
    tool_instructions = (
        "Tools available:\n"
        "- email.search (read): payload {query, max_results, user_id}\n"
        "- email.read (read): payload {message_id, user_id}\n"
        "- email.draft (write, no confirmation): payload {raw_base64, user_id}\n"
        "- email.send (write, confirmation): payload {raw_base64, user_id}\n"
        "- calendar.list_events (read): payload {calendar_id, max_results, time_min, time_max}\n"
        "- calendar.create_event (write, confirmation): payload {calendar_id, event}\n"
        "- calendar.modify_event (write, confirmation): payload {calendar_id, event_id, event}\n"
        "- notes.create (write, confirmation): payload {title, body}\n"
        "- tasks.create (write, confirmation): payload {title, notes}\n"
        "- tasks.list (read): payload {}\n"
        "- spotify.play (write): payload {context_uri, uris, offset, position_ms}\n"
        "- spotify.pause (write): payload {}\n"
        "- spotify.skip (write): payload {}\n"
        "Return ONLY valid JSON with keys: response (string), action (object or null).\n"
        "If action is used, include tool and payload fields.\n"
        "Do not include markdown or commentary outside JSON."
    )
    if forced_tool:
        tool_instructions = (
            f"{tool_instructions}\nUse tool: {forced_tool}. "
            "Do not choose a different tool."
        )
    return [
        {"role": "system", "content": f"{system_prompt}\n\n{tool_instructions}"},
        {"role": "user", "content": user_message},
    ]


def _require_llm_settings(settings: Settings) -> tuple[str, str, str]:
    if not settings.llm_base_url:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "llm_not_configured",
                    "message": "LLM_BASE_URL is missing.",
                }
            },
        )
    if not settings.llm_api_key:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "llm_not_configured",
                    "message": "LLM_API_KEY is missing.",
                }
            },
        )
    if not settings.llm_model:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "llm_not_configured",
                    "message": "LLM_MODEL is missing.",
                }
            },
        )
    return settings.llm_base_url, settings.llm_api_key, settings.llm_model


def generate_response(
    settings: Settings, message: str, forced_tool: str | None = None
) -> dict[str, Any]:
    base_url, api_key, model = _require_llm_settings(settings)
    payload = {
        "model": model,
        "messages": _build_messages(message, forced_tool),
        "temperature": 0.2,
    }
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=settings.llm_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "llm_request_failed",
                    "message": "Failed to call LLM.",
                }
            },
        ) from exc

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        decoded = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "llm_bad_response",
                    "message": "LLM response was not valid JSON.",
                }
            },
        ) from exc
    return decoded
