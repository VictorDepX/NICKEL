from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SESSION_FILE = Path(".nickel_session.json")


@dataclass
class PendingActionState:
    id: str
    summary: str


@dataclass
class SessionState:
    session_id: str | None
    pending_action: PendingActionState | None


def load_session() -> SessionState:
    if not SESSION_FILE.exists():
        return SessionState(session_id=None, pending_action=None)
    data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    session_id = data.get("session_id")
    pending = data.get("pending_action")
    pending_state = None
    if isinstance(pending, dict):
        pending_id = pending.get("id")
        pending_summary = pending.get("summary")
        if pending_id and pending_summary:
            pending_state = PendingActionState(
                id=str(pending_id), summary=str(pending_summary)
            )
    return SessionState(session_id=session_id, pending_action=pending_state)


def save_session(state: SessionState) -> None:
    payload: dict[str, Any] = asdict(state)
    SESSION_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
