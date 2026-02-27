from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SESSION_FILE = Path(".nickel_session.json")
MAX_HISTORY_ITEMS = 30


@dataclass
class PendingActionState:
    action_id: str
    tool: str


@dataclass
class SessionState:
    pending_action: PendingActionState | None
    history: list[dict[str, str]] = field(default_factory=list)


def load_session() -> SessionState:
    if not SESSION_FILE.exists():
        return SessionState(pending_action=None)
    data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))

    pending_state = None
    pending = data.get("pending_action")
    if isinstance(pending, dict):
        action_id = pending.get("action_id")
        tool = pending.get("tool")
        if action_id and tool:
            pending_state = PendingActionState(action_id=str(action_id), tool=str(tool))

    history: list[dict[str, str]] = []
    raw_history = data.get("history")
    if isinstance(raw_history, list):
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"}:
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            history.append({"role": role, "content": content.strip()})

    return SessionState(pending_action=pending_state, history=history[-MAX_HISTORY_ITEMS:])


def save_session(state: SessionState) -> None:
    payload: dict[str, Any] = asdict(state)
    payload["history"] = state.history[-MAX_HISTORY_ITEMS:]
    SESSION_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
