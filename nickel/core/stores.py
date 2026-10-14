"""Repositórios sobre o SQLite: conversa, ações pendentes, auditoria, memória e tokens."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from nickel.core.db import Database, dumps, iso, parse_iso, utcnow

MAIN_CONVERSATION = "main"


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
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, kind: str, name: str, status: str, detail: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "INSERT INTO audit (at, kind, name, status, detail) VALUES (?, ?, ?, ?, ?)",
            (iso(utcnow()), kind, name, status, dumps(_redact(detail or {}))),
        )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["detail"] = json.loads(row["detail"] or "{}")
        return rows


_SECRET_KEYS = {"access_token", "refresh_token", "token", "password", "secret", "audio_b64", "image_b64"}


def _redact(detail: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in detail.items():
        if key in _SECRET_KEYS:
            clean[key] = "***"
        elif isinstance(value, str) and len(value) > 500:
            clean[key] = value[:500] + "…"
        else:
            clean[key] = value
    return clean


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
