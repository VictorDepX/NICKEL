from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException


@dataclass
class PendingAction:
    action_id: str
    tool: str
    payload: dict[str, Any]
    created_at: datetime
    status: str


class PendingActionStore:
    def __init__(self) -> None:
        self._pending: dict[str, PendingAction] = {}

    def create(self, tool: str, payload: dict[str, Any]) -> PendingAction:
        action_id = str(uuid4())
        action = PendingAction(
            action_id=action_id,
            tool=tool,
            payload=payload,
            created_at=datetime.now(timezone.utc),
            status="pending_confirmation",
        )
        self._pending[action_id] = action
        return action

    def get(self, action_id: str) -> PendingAction:
        action = self._pending.get(action_id)
        if not action:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "pending_action_not_found",
                        "message": "Pending action not found.",
                    }
                },
            )
        return action

    def pop(self, action_id: str) -> PendingAction:
        action = self._pending.pop(action_id, None)
        if not action:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "pending_action_not_found",
                        "message": "Pending action not found.",
                    }
                },
            )
        return action


pending_actions = PendingActionStore()


def require_confirmation(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    action = pending_actions.create(tool=tool, payload=payload)
    return {
        "status": action.status,
        "action_id": action.action_id,
        "tool": action.tool,
        "created_at": action.created_at.isoformat(),
    }


def cancel_action(action_id: str, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "confirmation_required",
                    "message": "Explicit confirmation is required.",
                }
            },
        )
    action = pending_actions.pop(action_id)
    action.status = "cancelled"
    return {
        "status": action.status,
        "action_id": action.action_id,
        "tool": action.tool,
        "cancelled_at": datetime.now(timezone.utc).isoformat(),
    }


def confirm_action(action_id: str, confirmed: bool) -> PendingAction:
    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "confirmation_required",
                    "message": "Explicit confirmation is required.",
                }
            },
        )
    action = pending_actions.pop(action_id)
    action.status = "confirmed"
    return action
