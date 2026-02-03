from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
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
    def __init__(self, storage_path: Path | None = None) -> None:
        self._pending: dict[str, PendingAction] = {}
        self._storage_path = storage_path
        self._load()

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for action_id, payload in data.items():
                self._pending[action_id] = PendingAction(
                    action_id=payload["action_id"],
                    tool=payload["tool"],
                    payload=payload["payload"],
                    created_at=datetime.fromisoformat(payload["created_at"]),
                    status=payload["status"],
                )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "pending_actions_store_corrupt",
                        "message": "Pending actions store cannot be loaded.",
                    }
                },
            ) from exc
        data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        for action_id, payload in data.items():
            self._pending[action_id] = PendingAction(
                action_id=payload["action_id"],
                tool=payload["tool"],
                payload=payload["payload"],
                created_at=datetime.fromisoformat(payload["created_at"]),
                status=payload["status"],
            )

    def _persist(self) -> None:
        if not self._storage_path:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            action_id: {
                **asdict(action),
                "created_at": action.created_at.isoformat(),
            }
            for action_id, action in self._pending.items()
        }
        self._storage_path.write_text(json.dumps(data), encoding="utf-8")

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
        self._persist()
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


def configure_pending_actions(storage_path: Path | None) -> None:
    global pending_actions
    pending_actions = PendingActionStore(storage_path=storage_path)


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
    pending_actions._persist()
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
    pending_actions._persist()
    return action
