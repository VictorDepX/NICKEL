from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.calendar import create_event, modify_event
from app.config import Settings
from app.gmail import send as email_send
from app.notes import create_note
from app.pending_actions import PendingAction


def execute_action(_settings: Settings, action: PendingAction) -> dict[str, Any]:
    if action.tool == "calendar.create_event":
        return create_event(_settings, action.payload)
    if action.tool == "calendar.modify_event":
        return modify_event(_settings, action.payload)
    if action.tool == "email.send":
        return email_send(_settings, action.payload)
    if action.tool == "notes.create":
        return create_note(_settings, action.payload)
    raise HTTPException(
        status_code=501,
        detail={
            "error": {
                "code": "action_not_implemented",
                "message": f"Action {action.tool} is not implemented.",
            }
        },
    )
