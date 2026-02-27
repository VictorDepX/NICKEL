from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from app.audit import record_llm_event
from app.config import Settings


_SYSTEM_PROMPT_PATH = Path("docs/Nickel/system_prompt_text.md")
_MAX_HISTORY_MESSAGES = 12


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are Nickel, an adult, pragmatic personal assistant."


def _normalize_history(history: Any) -> list[dict[str, str]]:
    if not isinstance(history, list):
        return []

    normalized: list[dict[str, str]] = []
    for entry in history[-_MAX_HISTORY_MESSAGES:]:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        normalized.append({"role": role, "content": content.strip()})
    return normalized


def _build_messages(
    user_message: str,
    forced_tool: str | None,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
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
        "If no tool is required, action must be null and provide a natural conversational response.\n"
        "Do not include markdown or commentary outside JSON.\n"
        "Do not wrap JSON in markdown fences."
    )
    if forced_tool:
        tool_instructions = (
            f"{tool_instructions}\nUse tool: {forced_tool}. "
            "Do not choose a different tool."
        )

    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{tool_instructions}"},
        *_normalize_history(history),
        {"role": "user", "content": user_message},
    ]
    return messages


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


def _summarize_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    if len(message) > 180:
        return f"{message[:177]}..."
    return message or exc.__class__.__name__


def _should_retry_http_error(exc: httpx.HTTPStatusError) -> bool:
    status_code = exc.response.status_code
    return status_code == 429 or status_code >= 500


def generate_response(
    settings: Settings,
    message: str,
    forced_tool: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    base_url, api_key, model = _require_llm_settings(settings)
    payload = {
        "model": model,
        "messages": _build_messages(message, forced_tool, history=history),
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "response_format": {"type": "json_object"},
    }
    retry_count = max(0, settings.llm_retry_count)
    backoff_ms = max(0, settings.llm_retry_backoff_ms)

    start_time = time.perf_counter()
    response: httpx.Response | None = None

    for attempt in range(retry_count + 1):
        try:
            response = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            break
        except httpx.HTTPStatusError as exc:
            if attempt < retry_count and _should_retry_http_error(exc):
                sleep_ms = backoff_ms * (2**attempt)
                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000)
                continue
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            record_llm_event(
                model=model,
                duration_ms=duration_ms,
                status="error",
                error_summary=f"HTTP {exc.response.status_code}: {_summarize_error(exc)}",
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "error": {
                        "code": "llm_request_failed",
                        "message": "Failed to call LLM.",
                    }
                },
            ) from exc
        except httpx.HTTPError as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            record_llm_event(
                model=model,
                duration_ms=duration_ms,
                status="error",
                error_summary=_summarize_error(exc),
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "error": {
                        "code": "llm_request_failed",
                        "message": "Failed to call LLM.",
                    }
                },
            ) from exc

    if response is None:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        record_llm_event(
            model=model,
            duration_ms=duration_ms,
            status="error",
            error_summary="LLM response was empty.",
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "llm_request_failed",
                    "message": "Failed to call LLM.",
                }
            },
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        decoded = _decode_llm_json(content)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        record_llm_event(
            model=model,
            duration_ms=duration_ms,
            status="error",
            error_summary=_summarize_error(exc),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "llm_bad_response",
                    "message": "LLM response was not valid JSON.",
                }
            },
        ) from exc

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    record_llm_event(model=model, duration_ms=duration_ms, status="ok")
    return decoded


def _decode_llm_json(content: Any) -> dict[str, Any]:
    if isinstance(content, list):
        text = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    else:
        text = str(content)
    text = text.strip()

    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text)
        if fenced_match:
            decoded = json.loads(fenced_match.group(1))
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end < 0 or start >= end:
                raise
            decoded = json.loads(text[start : end + 1])

    if not isinstance(decoded, dict):
        raise json.JSONDecodeError("LLM response was not a JSON object.", text, 0)
    return decoded
