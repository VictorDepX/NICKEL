from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.config import Settings
from app.calendar import list_events as calendar_list
from app.gmail import draft as email_draft
from app.gmail import read as email_read
from app.gmail import search as email_search
from app.llm import generate_response
from app.orchestrator import decide_tool
from app.pending_actions import require_confirmation


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
    decision = decide_tool(message)
    llm_response = generate_response(settings, message, forced_tool=decision.tool)
    action = llm_response.get("action")
    response_text = llm_response.get("response", "")

    if action:
        tool = action.get("tool")
        if decision.tool and tool != decision.tool:
            raise HTTPException(
                status_code=502,
                detail={
                    "error": {
                        "code": "llm_tool_mismatch",
                        "message": "LLM returned a tool different from orchestrator decision.",
                    }
                },
            )
        action_payload = action.get("payload", {})
        if tool == "email.search":
            tool_result = email_search(settings, action_payload)
            return {
                "status": "ok",
                "response": response_text,
                "tool_result": tool_result,
            }
        if tool == "email.read":
            tool_result = email_read(settings, action_payload)
            return {
                "status": "ok",
                "response": response_text,
                "tool_result": tool_result,
            }
        if tool == "email.draft":
            tool_result = email_draft(settings, action_payload)
            return {
                "status": "ok",
                "response": response_text,
                "tool_result": tool_result,
            }
        if tool == "email.send":
            pending = require_confirmation("email.send", action_payload)
            return {
                "status": "pending_confirmation",
                "response": response_text,
                "pending_action": pending,
            }
        if tool == "calendar.list_events":
            tool_result = calendar_list(settings, action_payload)
            return {
                "status": "ok",
                "response": response_text,
                "tool_result": tool_result,
            }
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
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "unsupported_tool",
                    "message": f"Tool {tool} is not supported.",
                }
            },
        )

    return {
        "status": "ok",
        "response": response_text,
    }
