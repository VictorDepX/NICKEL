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
class Task:
    task_id: str
    title: str
    notes: str | None
    created_at: datetime


class TasksStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path
        self._tasks: dict[str, Task] = {}
        self._load()

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for task_id, payload in data.items():
                self._tasks[task_id] = Task(
                    task_id=payload["task_id"],
                    title=payload["title"],
                    notes=payload.get("notes"),
                    created_at=datetime.fromisoformat(payload["created_at"]),
                )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": "tasks_store_corrupt",
                        "message": "Tasks store cannot be loaded.",
                    }
                },
            ) from exc

    def _persist(self) -> None:
        if not self._storage_path:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            task_id: {
                **asdict(task),
                "created_at": task.created_at.isoformat(),
            }
            for task_id, task in self._tasks.items()
        }
        self._storage_path.write_text(json.dumps(data), encoding="utf-8")

    def create(self, title: str, notes: str | None) -> Task:
        task_id = str(uuid4())
        task = Task(
            task_id=task_id,
            title=title,
            notes=notes,
            created_at=datetime.now(timezone.utc),
        )
        self._tasks[task_id] = task
        self._persist()
        return task

    def list(self) -> list[Task]:
        return list(self._tasks.values())


tasks_store = TasksStore()


def configure_tasks_store(storage_path: Path | None) -> None:
    global tasks_store
    tasks_store = TasksStore(storage_path=storage_path)


def create_task(_settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    title = payload.get("title")
    notes = payload.get("notes")
    if not title:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_title",
                    "message": "title is required.",
                }
            },
        )
    task = tasks_store.create(title=str(title), notes=str(notes) if notes else None)
    return {
        "status": "ok",
        "data": {
            "task": {
                "task_id": task.task_id,
                "title": task.title,
                "notes": task.notes,
                "created_at": task.created_at.isoformat(),
            }
        },
    }


def list_tasks(_settings: Settings, _payload: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        {
            "task_id": task.task_id,
            "title": task.title,
            "notes": task.notes,
            "created_at": task.created_at.isoformat(),
        }
        for task in tasks_store.list()
    ]
    return {"status": "ok", "data": {"tasks": tasks}}
