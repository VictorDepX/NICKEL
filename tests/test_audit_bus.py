from __future__ import annotations

import asyncio
import sqlite3

from nickel.core import trace
from nickel.core.db import Database
from nickel.core.stores import AuditLog


def make_audit() -> AuditLog:
    return AuditLog(Database(":memory:"))


def test_record_returns_event_and_stamps_run_id():
    audit = make_audit()
    with trace.run_scope("abc123"):
        event = audit.record("tool", "x", "ok", {"a": 1}, duration_ms=7)
    assert event["run_id"] == "abc123"
    assert event["duration_ms"] == 7
    assert event["detail"] == {"a": 1}
    assert {"id", "at", "kind", "name", "status"} <= set(event)
    assert audit.recent(1)[0]["run_id"] == "abc123"


def test_run_scope_restores_previous_value():
    with trace.run_scope() as rid:
        assert len(rid) == 12
        assert trace.current_run_id.get() == rid
    assert trace.current_run_id.get() is None


def test_subscriber_receives_events_from_worker_thread():
    audit = make_audit()

    async def main():
        queue = audit.subscribe()
        await asyncio.to_thread(audit.record, "system", "startup", "ok")
        return await asyncio.wait_for(queue.get(), 1)

    assert asyncio.run(main())["kind"] == "system"


def test_full_queue_drops_oldest():
    audit = make_audit()

    async def main():
        queue = audit.subscribe(maxsize=2)
        for i in range(3):
            audit.record("tool", f"t{i}", "ok")
        await asyncio.sleep(0)
        return [queue.get_nowait()["name"], queue.get_nowait()["name"]]

    assert asyncio.run(main()) == ["t1", "t2"]


def test_unsubscribe_clears_subscribers():
    audit = make_audit()

    async def main():
        queue = audit.subscribe()
        assert audit.has_subscribers()
        audit.unsubscribe(queue)
        return audit.has_subscribers()

    assert asyncio.run(main()) is False


def test_closed_loop_subscriber_is_dropped_silently():
    audit = make_audit()

    async def main():
        audit.subscribe()

    asyncio.run(main())  # o loop fecha com o assinante registrado
    audit.record("system", "x", "ok")
    assert not audit.has_subscribers()


def test_since_and_run_are_ascending_and_filtered():
    audit = make_audit()
    with trace.run_scope("r1"):
        first = audit.record("tool", "a", "ok")
        audit.record("tool", "b", "error")
    audit.record("system", "c", "ok")
    assert [e["name"] for e in audit.since(first["id"])] == ["b", "c"]
    assert [e["name"] for e in audit.since(0, limit=2)] == ["a", "b"]
    assert [e["name"] for e in audit.run("r1")] == ["a", "b"]
    runs = audit.runs()
    assert runs[0]["run_id"] == "r1"
    assert runs[0]["events"] == 2 and runs[0]["errors"] == 1


def test_text_limit_and_redaction():
    audit = make_audit()
    event = audit.record("tool", "x", "ok", {"token": "s3", "text": "x" * 900})
    assert event["detail"]["token"] == "***"
    assert len(event["detail"]["text"]) == 501
    big = audit.record("tool", "x", "ok", {"text": "x" * 900}, text_limit=4000)
    assert len(big["detail"]["text"]) == 900


def test_migrates_legacy_audit_table(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL,"
        " name TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}')"
    )
    conn.execute("INSERT INTO audit (at, kind, name, status) VALUES ('t','k','n','ok')")
    conn.commit()
    conn.close()
    db = Database(path)
    event = AuditLog(db).record("tool", "x", "ok", duration_ms=3)
    assert event["duration_ms"] == 3
    cols = {row["name"] for row in db.query("PRAGMA table_info(audit)")}
    assert {"run_id", "duration_ms"} <= cols
    assert AuditLog(db).recent(5)[-1]["run_id"] is None
