from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.config import Settings


@dataclass
class Note:
    note_id: str
    title: str | None
    body: str
    created_at: datetime


class NotesStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path
        self._notes: dict[str, Note] = {}
        self._load()

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for note_id, payload in data.items():
                self._notes[note_id] = Note(
                    note_id=payload["note_id"],
                    title=payload.get("title"),
                    body=payload["body"],
                    created_at=datetime.fromisoformat(payload["created_at"]),
                )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "notes_store_corrupt",
                        "message": "Notes store cannot be loaded.",
                    }
                },
            ) from exc

    def _persist(self) -> None:
        if not self._storage_path:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            note_id: {
                **asdict(note),
                "created_at": note.created_at.isoformat(),
            }
            for note_id, note in self._notes.items()
        }
        self._storage_path.write_text(json.dumps(data), encoding="utf-8")

    def create(self, title: str | None, body: str) -> Note:
        note_id = str(uuid4())
        note = Note(
            note_id=note_id,
            title=title,
            body=body,
            created_at=datetime.now(timezone.utc),
        )
        self._notes[note_id] = note
        self._persist()
        return note


notes_store = NotesStore()


def configure_notes_store(storage_path: Path | None) -> None:
    global notes_store
    notes_store = NotesStore(storage_path=storage_path)


def create_note(_settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("body")
    title = payload.get("title")
    if not body:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_body",
                    "message": "body is required.",
                }
            },
        )
    note = notes_store.create(title=title, body=str(body))
    return {
        "status": "ok",
        "data": {
            "note": {
                "note_id": note.note_id,
                "title": note.title,
                "body": note.body,
                "created_at": note.created_at.isoformat(),
            }
        },
    }
