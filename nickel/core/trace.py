"""Identificador de execução (run_id) propagado por ContextVar para correlacionar eventos."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

current_run_id: ContextVar[str | None] = ContextVar("nickel_run_id", default=None)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def run_scope(run_id: str | None = None) -> Iterator[str]:
    rid = run_id or new_run_id()
    token = current_run_id.set(rid)
    try:
        yield rid
    finally:
        current_run_id.reset(token)
