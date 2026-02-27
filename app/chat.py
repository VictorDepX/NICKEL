from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from app.audit import record_event

from app.calendar import list_events as calendar_list
from app.config import Settings
from app.gmail import draft as email_draft
from app.gmail import read as email_read
from app.gmail import search as email_search
from app.llm import generate_response
from app.orchestrator import decide_tool, is_high_confidence
from app.pending_actions import require_confirmation
from app.spotify import pause as spotify_pause
from app.spotify import play as spotify_play
from app.spotify import skip as spotify_skip
from app.tasks import list_tasks


TOOL_HANDLERS: dict[str, dict[str, Any]] = {
    "email.search": {"handler": email_search, "requires_confirmation": False},
    "email.read": {"handler": email_read, "requires_confirmation": False},
    "email.draft": {"handler": email_draft, "requires_confirmation": False},
    "email.send": {"handler": None, "requires_confirmation": True},
    "calendar.list_events": {
        "handler": calendar_list,
        "requires_confirmation": False,
    },
    "calendar.create_event": {"handler": None, "requires_confirmation": True},
    "calendar.modify_event": {"handler": None, "requires_confirmation": True},
    "notes.create": {"handler": None, "requires_confirmation": True},
    "tasks.create": {"handler": None, "requires_confirmation": True},
    "tasks.list": {"handler": list_tasks, "requires_confirmation": False},
    "spotify.play": {"handler": spotify_play, "requires_confirmation": False},
    "spotify.pause": {"handler": spotify_pause, "requires_confirmation": False},
    "spotify.skip": {"handler": spotify_skip, "requires_confirmation": False},
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


def handle_chat(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
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

    history = _parse_history(payload)
    decision = decide_tool(message)
    forced_tool = decision.tool if is_high_confidence(decision) else None
    llm_response = generate_response(
        settings,
        message,
        forced_tool=forced_tool,
        history=history,
    )
    action = llm_response.get("action")
    response_text = llm_response.get("response", "")

    if action:
        tool = action.get("tool")
        if forced_tool and tool != forced_tool:
            record_event(
                tool="orchestrator.mismatch",
                status="fallback",
                payload={
                    "message": message,
                    "decision_tool": decision.tool,
                    "decision_reason": decision.reason,
                    "decision_confidence": decision.confidence,
                    "forced_tool": forced_tool,
                    "llm_tool": tool,
                },
            )
            return {
                "status": "requires_clarification",
                "response": "Encontrei um conflito na interpretação do pedido. Pode confirmar a ação desejada?",
                "fallback": "tool_mismatch",
                "orchestration": {
                    "decision": {
                        "tool": decision.tool,
                        "reason": decision.reason,
                        "confidence": decision.confidence,
                    },
                    "llm_tool": tool,
                },
            }

        if decision.tool is None and tool:
            record_event(
                tool="orchestrator.low_confidence_action",
                status="observed",
                payload={
                    "message": message,
                    "decision_reason": decision.reason,
                    "decision_confidence": decision.confidence,
                    "llm_tool": tool,
                },
            )

        action_payload = action.get("payload", {})
        tool_config = TOOL_HANDLERS.get(tool)
        if tool_config is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "unsupported_tool",
                        "message": f"Tool {tool} is not supported.",
                    }
                },
            )

        if tool_config["requires_confirmation"]:
            pending = require_confirmation(tool, action_payload)
            return {
                "status": "pending_confirmation",
                "response": response_text,
                "pending_action": pending,
            }

        tool_result = tool_config["handler"](settings, action_payload)
        return {
            "status": "ok",
            "response": response_text,
            "tool_result": tool_result,
        }

    return {
        "status": "ok",
        "response": response_text,
    }
