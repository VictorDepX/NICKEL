"""Repositórios sobre o SQLite: conversa, ações pendentes, auditoria, memória e tokens."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from nickel.core.db import Database, dumps, iso, parse_iso, utcnow
from nickel.core.trace import current_run_id

log = logging.getLogger(__name__)

MAIN_CONVERSATION = "main"
MAX_TEXT_LIMIT = 4000
PROGRESS_MAX_AGE = timedelta(hours=1)  # idade a partir da qual `reasoning/progress` órfão é apagado no startup


@dataclass
class StoredMessage:
    id: int
    channel: str
    role: str
    content: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""


class ConversationStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        role: str,
        content: str,
        *,
        channel: str,
        attachments: list[dict[str, Any]] | None = None,
        conversation: str = MAIN_CONVERSATION,
    ) -> int:
        return self.db.execute(
            "INSERT INTO messages (conversation, channel, role, content, attachments, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (conversation, channel, role, content, dumps(attachments or []), iso(utcnow())),
        )

    def count(self, conversation: str = MAIN_CONVERSATION) -> int:
        rows = self.db.query("SELECT COUNT(*) AS n FROM messages WHERE conversation = ?", (conversation,))
        return int(rows[0]["n"]) if rows else 0

    def recent(self, limit: int, conversation: str = MAIN_CONVERSATION) -> list[StoredMessage]:
        rows = self.db.query(
            "SELECT * FROM messages WHERE conversation = ? ORDER BY id DESC LIMIT ?",
            (conversation, limit),
        )
        return [
            StoredMessage(
                id=row["id"],
                channel=row["channel"],
                role=row["role"],
                content=row["content"],
                attachments=json.loads(row["attachments"] or "[]"),
                created_at=row["created_at"],
            )
            for row in reversed(rows)
        ]


@dataclass
class PendingAction:
    id: str
    tool: str
    arguments: dict[str, Any]
    summary: str
    channel: str
    status: str
    created_at: str
    result: dict[str, Any] | None = None


class PendingActionStore:
    """Ações que exigem confirmação explícita antes de executar."""

    def __init__(self, db: Database, ttl_minutes: int = 15) -> None:
        self.db = db
        self.ttl = timedelta(minutes=ttl_minutes)

    def create(
        self,
        tool: str,
        arguments: dict[str, Any],
        summary: str,
        *,
        channel: str,
        conversation: str = MAIN_CONVERSATION,
    ) -> PendingAction:
        self.expire_old()
        # Só uma ação pendente por vez: a nova substitui a anterior.
        self.db.execute(
            "UPDATE pending_actions SET status = 'superseded', resolved_at = ?"
            " WHERE conversation = ? AND status = 'pending'",
            (iso(utcnow()), conversation),
        )
        action_id = uuid.uuid4().hex[:12]
        now = iso(utcnow())
        self.db.execute(
            "INSERT INTO pending_actions (id, conversation, channel, tool, arguments, summary, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (action_id, conversation, channel, tool, dumps(arguments), summary, now),
        )
        return PendingAction(action_id, tool, arguments, summary, channel, "pending", now)

    def current(self, conversation: str = MAIN_CONVERSATION) -> PendingAction | None:
        self.expire_old()
        row = self.db.query_one(
            "SELECT * FROM pending_actions WHERE conversation = ? AND status = 'pending'"
            " ORDER BY created_at DESC LIMIT 1",
            (conversation,),
        )
        return self._from_row(row) if row else None

    def get(self, action_id: str) -> PendingAction | None:
        row = self.db.query_one("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
        return self._from_row(row) if row else None

    def list_pending(self) -> list[PendingAction]:
        self.expire_old()
        rows = self.db.query(
            "SELECT * FROM pending_actions WHERE status = 'pending' ORDER BY created_at DESC"
        )
        return [self._from_row(row) for row in rows]

    def resolve(self, action_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "UPDATE pending_actions SET status = ?, result = ?, resolved_at = ? WHERE id = ?",
            (status, dumps(result) if result is not None else None, iso(utcnow()), action_id),
        )

    def expire_old(self) -> None:
        cutoff = iso(utcnow() - self.ttl)
        self.db.execute(
            "UPDATE pending_actions SET status = 'expired', resolved_at = ?"
            " WHERE status = 'pending' AND created_at < ?",
            (iso(utcnow()), cutoff),
        )

    @staticmethod
    def _from_row(row: dict[str, Any]) -> PendingAction:
        return PendingAction(
            id=row["id"],
            tool=row["tool"],
            arguments=json.loads(row["arguments"]),
            summary=row["summary"],
            channel=row["channel"],
            status=row["status"],
            created_at=row["created_at"],
            result=json.loads(row["result"]) if row.get("result") else None,
        )


class AuditLog:
    """Trilha de auditoria e barramento de eventos: cada `record` grava e entrega aos assinantes."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self._sub_lock = threading.Lock()

    def record(
        self,
        kind: str,
        name: str,
        status: str,
        detail: dict[str, Any] | None = None,
        *,
        duration_ms: int | None = None,
        run_id: str | None = None,
        text_limit: int = 500,
    ) -> dict[str, Any]:
        run_id = run_id if run_id is not None else current_run_id.get()
        clean = _redact(detail or {}, min(text_limit, MAX_TEXT_LIMIT))
        at = iso(utcnow(), ms=True)
        event_id = self.db.execute(
            "INSERT INTO audit (at, kind, name, status, detail, run_id, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (at, kind, name, status, dumps(clean), run_id, duration_ms),
        )
        if kind == "reasoning" and status == "final":
            # O parcial já foi entregue ao vivo; no banco só o final importa (sem isto, até 2,5 linhas/s para sempre).
            self.db.delete(
                "DELETE FROM audit WHERE run_id IS ? AND kind = 'reasoning' AND status = 'progress'"
                " AND json_extract(detail, '$.step') IS ?",
                (run_id, clean.get("step") if isinstance(clean, dict) else None),
            )
        event = {
            "id": event_id,
            "at": at,
            "kind": kind,
            "name": name,
            "status": status,
            "detail": clean,
            "run_id": run_id,
            "duration_ms": duration_ms,
        }
        self._publish(event)
        return event

    def subscribe(self, maxsize: int = 1000) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._sub_lock:
            self._subscribers[queue] = asyncio.get_running_loop()
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._sub_lock:
            self._subscribers.pop(queue, None)

    def has_subscribers(self) -> bool:
        with self._sub_lock:
            return bool(self._subscribers)

    def _publish(self, event: dict[str, Any]) -> None:
        with self._sub_lock:
            targets = list(self._subscribers.items())
        for queue, loop in targets:
            try:
                loop.call_soon_threadsafe(_offer, queue, event)
            except Exception:  # loop fechado ou falha ao entregar: auditar nunca derruba o fluxo
                log.debug("assinante do audit descartado", exc_info=True)
                self.unsubscribe(queue)

    def prune_stale_progress(self, older_than: timedelta = PROGRESS_MAX_AGE) -> int:
        """Apaga `reasoning/progress` antigos que ficaram de turnos que caíram antes do `final`."""
        cutoff = iso(utcnow() - older_than, ms=True)
        return self.db.delete(
            "DELETE FROM audit WHERE kind = 'reasoning' AND status = 'progress' AND at < ?", (cutoff,)
        )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return _decode(self.db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)))

    def since(self, after_id: int, limit: int = 500) -> list[dict[str, Any]]:
        return _decode(
            self.db.query("SELECT * FROM audit WHERE id > ? ORDER BY id ASC LIMIT ?", (after_id, limit))
        )

    def run(self, run_id: str) -> list[dict[str, Any]]:
        return _decode(self.db.query("SELECT * FROM audit WHERE run_id = ? ORDER BY id ASC", (run_id,)))

    def runs(self, limit: int = 30) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT a.run_id AS run_id, MIN(a.at) AS started_at, COUNT(*) AS events,"
            " SUM(CASE WHEN a.status = 'error' THEN 1 ELSE 0 END) AS errors,"
            " COALESCE((SELECT t.duration_ms FROM audit t WHERE t.run_id = a.run_id AND t.kind = 'turn'"
            "  AND t.status IN ('done', 'error') AND t.duration_ms IS NOT NULL ORDER BY t.id DESC LIMIT 1),"
            "  SUM(COALESCE(a.duration_ms, 0))) AS duration_ms"
            " FROM audit a WHERE a.run_id IS NOT NULL GROUP BY a.run_id ORDER BY MAX(a.id) DESC LIMIT ?",
            (limit,),
        )


def _offer(queue: asyncio.Queue, event: dict[str, Any]) -> None:
    """Entrega sem bloquear: com a fila cheia, descarta o item mais antigo."""
    try:
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(event)
    except Exception:
        log.debug("falha ao entregar evento de audit", exc_info=True)


def _decode(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        row["detail"] = json.loads(row["detail"] or "{}")
    return rows


_SECRET_KEYS = {
    "access_token", "refresh_token", "token", "password", "secret", "audio_b64", "image_b64",
    "api_key", "authorization", "bridge_token",
}


def _is_secret(key: Any) -> bool:
    return isinstance(key, str) and key.lower() in _SECRET_KEYS


def _redact(detail: Any, limit: int = 500) -> Any:
    """Mascara segredos (chave sem diferenciar maiúsculas) e trunca textos, recursivamente em dicts e listas."""
    if isinstance(detail, dict):
        return {
            key: "***" if _is_secret(key) else _redact(value, limit) for key, value in detail.items()
        }
    if isinstance(detail, (list, tuple)):
        return [_redact(item, limit) for item in detail]
    if isinstance(detail, str) and len(detail) > limit:
        return detail[:limit] + "…"
    return detail


class MemoryStore:
    """Memória de longo prazo, só com permissão explícita (policy_memory.md)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO memory (key, value, created_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key.strip(), value.strip(), iso(utcnow())),
        )

    def delete(self, key: str) -> bool:
        return bool(self.db.execute("DELETE FROM memory WHERE key = ?", (key.strip(),)))

    def all(self) -> list[dict[str, str]]:
        return self.db.query("SELECT key, value, created_at FROM memory ORDER BY key")


class StateStore:
    """Pares chave/valor de estado do NICKEL (ex.: workspace ativo)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.query_one("SELECT value FROM state WHERE key = ?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, iso(utcnow())),
        )


class TokenStore:
    """Tokens OAuth criptografados com Fernet (OAUTH_TOKEN_KEY)."""

    def __init__(self, db: Database, key: str | None) -> None:
        self.db = db
        self._fernet = Fernet(key.encode()) if key else None

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def put(self, name: str, payload: dict[str, Any]) -> None:
        if not self._fernet:
            raise RuntimeError("OAUTH_TOKEN_KEY não configurada.")
        blob = self._fernet.encrypt(json.dumps(payload).encode())
        self.db.execute(
            "INSERT INTO tokens (name, payload, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (name, blob, iso(utcnow())),
        )

    def get(self, name: str) -> dict[str, Any] | None:
        if not self._fernet:
            return None
        row = self.db.query_one("SELECT payload FROM tokens WHERE name = ?", (name,))
        if not row:
            return None
        try:
            return json.loads(self._fernet.decrypt(row["payload"]))
        except InvalidToken:
            return None

    def delete(self, name: str) -> None:
        self.db.execute("DELETE FROM tokens WHERE name = ?", (name,))


class InboundDedup:
    def __init__(self, db: Database) -> None:
        self.db = db

    def seen(self, message_id: str) -> bool:
        """Registra o ID e diz se ele já tinha sido processado."""
        if self.db.query_one("SELECT 1 FROM processed_inbound WHERE message_id = ?", (message_id,)):
            return True
        self.db.execute(
            "INSERT OR IGNORE INTO processed_inbound (message_id, at) VALUES (?, ?)",
            (message_id, iso(utcnow())),
        )
        cutoff = iso(utcnow() - timedelta(days=7))
        self.db.execute("DELETE FROM processed_inbound WHERE at < ?", (cutoff,))
        return False


__all__ = [
    "AuditLog",
    "ConversationStore",
    "InboundDedup",
    "MAIN_CONVERSATION",
    "MemoryStore",
    "PendingAction",
    "PendingActionStore",
    "StoredMessage",
    "TokenStore",
    "parse_iso",
]
