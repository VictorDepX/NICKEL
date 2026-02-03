from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException


@dataclass
class MemoryProposal:
    memory_id: str
    key: str
    value: str
    created_at: datetime
    status: str


@dataclass
class MemoryItem:
    memory_id: str
    key: str
    value: str
    created_at: datetime


class MemoryStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path
        self._memories: dict[str, MemoryItem] = {}
        self._load()

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for memory_id, payload in data.items():
                self._memories[memory_id] = MemoryItem(
                    memory_id=payload["memory_id"],
                    key=payload["key"],
                    value=payload["value"],
                    created_at=datetime.fromisoformat(payload["created_at"]),
                )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "memory_store_corrupt",
                        "message": "Memory store cannot be loaded.",
                    }
                },
            ) from exc

    def _persist(self) -> None:
        if not self._storage_path:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            memory_id: {
                **asdict(memory),
                "created_at": memory.created_at.isoformat(),
            }
            for memory_id, memory in self._memories.items()
        }
        self._storage_path.write_text(json.dumps(data), encoding="utf-8")

    def store(self, proposal: MemoryProposal) -> MemoryItem:
        memory = MemoryItem(
            memory_id=proposal.memory_id,
            key=proposal.key,
            value=proposal.value,
            created_at=proposal.created_at,
        )
        self._memories[memory.memory_id] = memory
        self._persist()
        return memory

    def list(self) -> list[MemoryItem]:
        return list(self._memories.values())


class MemoryProposalStore:
    def __init__(self) -> None:
        self._pending: dict[str, MemoryProposal] = {}

    def create(self, key: str, value: str) -> MemoryProposal:
        memory_id = str(uuid4())
        proposal = MemoryProposal(
            memory_id=memory_id,
            key=key,
            value=value,
            created_at=datetime.now(timezone.utc),
            status="pending_confirmation",
        )
        self._pending[memory_id] = proposal
        return proposal

    def pop(self, memory_id: str) -> MemoryProposal:
        proposal = self._pending.pop(memory_id, None)
        if not proposal:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "memory_proposal_not_found",
                        "message": "Memory proposal not found.",
                    }
                },
            )
        return proposal


memory_store = MemoryStore()
memory_proposals = MemoryProposalStore()


def configure_memory_store(storage_path: Path | None) -> None:
    global memory_store
    memory_store = MemoryStore(storage_path=storage_path)


def propose_memory(payload: dict[str, Any]) -> dict[str, Any]:
    key = payload.get("key")
    value = payload.get("value")
    if not key or not value:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_memory_fields",
                    "message": "key and value are required.",
                }
            },
        )
    proposal = memory_proposals.create(key=str(key), value=str(value))
    return {
        "status": proposal.status,
        "memory_id": proposal.memory_id,
        "key": proposal.key,
        "value": proposal.value,
        "created_at": proposal.created_at.isoformat(),
    }


def confirm_memory(payload: dict[str, Any]) -> dict[str, Any]:
    memory_id = payload.get("memory_id")
    confirmed = payload.get("confirmed") is True
    if not memory_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_memory_id",
                    "message": "memory_id is required.",
                }
            },
        )
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
    proposal = memory_proposals.pop(str(memory_id))
    proposal.status = "confirmed"
    memory = memory_store.store(proposal)
    return {
        "status": "ok",
        "data": {
            "memory": {
                "memory_id": memory.memory_id,
                "key": memory.key,
                "value": memory.value,
                "created_at": memory.created_at.isoformat(),
            }
        },
    }


def list_memory() -> dict[str, Any]:
    items = [
        {
            "memory_id": item.memory_id,
            "key": item.key,
            "value": item.value,
            "created_at": item.created_at.isoformat(),
        }
        for item in memory_store.list()
    ]
    return {"status": "ok", "data": {"memories": items}}
