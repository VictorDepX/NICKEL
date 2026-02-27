from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException


@dataclass
class AuditEvent:
    event_id: str
    tool: str
    status: str
    payload: dict[str, Any] | None
    action_id: str | None
    created_at: datetime


class AuditStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path
        self._events: list[AuditEvent] = []
        self._load()

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._events = [
                AuditEvent(
                    event_id=item["event_id"],
                    tool=item["tool"],
                    status=item["status"],
                    payload=item.get("payload"),
                    action_id=item.get("action_id"),
                    created_at=datetime.fromisoformat(item["created_at"]),
                )
                for item in data
            ]
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "audit_store_corrupt",
                        "message": "Audit store cannot be loaded.",
                    }
                },
            ) from exc

    def _persist(self) -> None:
        if not self._storage_path:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                **asdict(event),
                "created_at": event.created_at.isoformat(),
            }
            for event in self._events
        ]
        self._storage_path.write_text(json.dumps(data), encoding="utf-8")

    def add(
        self,
        tool: str,
        status: str,
        payload: dict[str, Any] | None,
        action_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=str(uuid4()),
            tool=tool,
            status=status,
            payload=payload,
            action_id=action_id,
            created_at=datetime.now(timezone.utc),
        )
        self._events.append(event)
        self._persist()
        return event

    def list(
        self,
        tool: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        events = self._events
        if tool:
            events = [event for event in events if event.tool == tool]
        if since:
            events = [event for event in events if event.created_at >= since]
        if limit is not None:
            events = events[-limit:]
        return events


audit_store = AuditStore()


def configure_audit_store(storage_path: Path | None) -> None:
    global audit_store
    audit_store = AuditStore(storage_path=storage_path)


def record_event(
    tool: str,
    status: str,
    payload: dict[str, Any] | None,
    action_id: str | None = None,
) -> None:
    audit_store.add(tool=tool, status=status, payload=payload, action_id=action_id)


def record_llm_event(
    *,
    model: str,
    duration_ms: int,
    status: str,
    error_summary: str | None = None,
) -> None:
    safe_payload = {
        "model": model,
        "duration_ms": duration_ms,
        "status": status,
        "error_summary": error_summary,
    }
    audit_store.add(tool="llm.chat.completions", status=status, payload=safe_payload)


def list_events(params: dict[str, Any]) -> dict[str, Any]:
    tool = params.get("tool")
    since_value = params.get("since")
    limit_value = params.get("limit")
    since = datetime.fromisoformat(since_value) if since_value else None
    limit = int(limit_value) if limit_value is not None else None
    events = [
        {
            "event_id": event.event_id,
            "tool": event.tool,
            "status": event.status,
            "payload": event.payload,
            "action_id": event.action_id,
            "created_at": event.created_at.isoformat(),
        }
        for event in audit_store.list(tool=tool, since=since, limit=limit)
    ]
    return {"status": "ok", "data": {"events": events}}
