from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.calendar import list_events as calendar_list
from app.config import Settings
from app.gmail import draft as email_draft
from app.gmail import read as email_read
from app.gmail import search as email_search
from app.llm import generate_response
from app.orchestrator import decide_tool
from app.pending_actions import require_confirmation
from app.spotify import pause as spotify_pause
from app.spotify import play as spotify_play
from app.spotify import skip as spotify_skip
from app.tasks import list_tasks


_CONFIRMATION_REQUIRED_TOOLS = {
    "email.send",
    "calendar.create_event",
    "calendar.modify_event",
    "notes.create",
    "tasks.create",
}


def _parse_history(payload: dict[str, Any]) -> list[dict[str, str]]:
    history = payload.get("history")
    if not isinstance(history, list):
        return []

    parsed: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        parsed.append({"role": role, "content": content.strip()})
    return parsed


def _require_message(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if not message or not isinstance(message, str):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_message",
                    "message": "message is required.",
                }
            },
        )
    return message


def _compute_confidence(requested_tool: str | None, action_tool: str | None) -> float:
    if requested_tool and action_tool == requested_tool:
        return 0.95
    if requested_tool and action_tool is None:
        return 0.35
    if not requested_tool and action_tool:
        return 0.65
    return 0.8


def plan_chat(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    message = _require_message(payload)

    history = _parse_history(payload)
    decision = decide_tool(message)
    llm_response = generate_response(
        settings,
        message,
        forced_tool=decision.tool,
        history=history,
    )
    action = llm_response.get("action")
    action_tool = action.get("tool") if isinstance(action, dict) else None
    if decision.tool and action_tool != decision.tool:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "llm_tool_mismatch",
                    "message": "LLM returned a tool different from orchestrator decision.",
                }
            },
        )

    return {
        "response": llm_response.get("response", ""),
        "action": action if isinstance(action, dict) else None,
        "confidence": _compute_confidence(decision.tool, action_tool),
        "requires_confirmation": action_tool in _CONFIRMATION_REQUIRED_TOOLS,
    }


def execute_chat_plan(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    response_text = payload.get("response", "")

    if action is None:
        return {
            "status": "ok",
            "response": response_text,
        }

    if not isinstance(action, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "invalid_action",
                    "message": "action must be an object or null.",
                }
            },
        )

    tool = action.get("tool")
    action_payload = action.get("payload", {})
    if tool == "email.search":
        tool_result = email_search(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "email.read":
        tool_result = email_read(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "email.draft":
        tool_result = email_draft(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "email.send":
        pending = require_confirmation("email.send", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "calendar.list_events":
        tool_result = calendar_list(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "calendar.create_event":
        pending = require_confirmation("calendar.create_event", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "calendar.modify_event":
        pending = require_confirmation("calendar.modify_event", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "notes.create":
        pending = require_confirmation("notes.create", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "tasks.create":
        pending = require_confirmation("tasks.create", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "tasks.list":
        tool_result = list_tasks(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "spotify.play":
        tool_result = spotify_play(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "spotify.pause":
        tool_result = spotify_pause(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "spotify.skip":
        tool_result = spotify_skip(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "unsupported_tool",
                "message": f"Tool {tool} is not supported.",
            }
        },
    )


def handle_chat(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    plan_result = plan_chat(settings, payload)
    return execute_chat_plan(settings, plan_result)
