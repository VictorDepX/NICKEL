from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from nickel.core.agent import Agent, Turn
from nickel.core.db import iso, parse_iso
from nickel.skills import build_registry
from nickel.skills.reminders import add_months, next_occurrence

from conftest import FakeWhatsApp, call, run, say

TZ = ZoneInfo("America/Sao_Paulo")


class FakeGoogle:
    def status(self):
        return {"status": "ready"}

    def missing_config(self):
        return []


class FakeCalendar:
    def __init__(self):
        self.created = []
        self.deleted = []

    async def create(self, **fields):
        self.created.append(fields)
        return {"id": "evt1"}

    async def delete(self, event_id):
        self.deleted.append(event_id)


def future(hours=2):
    return (datetime.now(TZ) + timedelta(hours=hours)).replace(microsecond=0)


def test_create_via_agent_local_only(services, llm):
    when = future()
    llm.queue(call("reminder_create", text="pagar a conta de luz", when=when.isoformat()), say("Agendado."))
    run(Agent(services, build_registry()).handle(Turn(channel="whatsapp", text="me lembra de pagar a luz")))
    rows = services.reminders.upcoming()
    assert len(rows) == 1 and rows[0]["text"] == "pagar a conta de luz"
    assert parse_iso(rows[0]["due_at"]) == when.astimezone(timezone.utc)
    assert rows[0]["calendar_event_id"] is None


def test_create_also_creates_calendar_event(services):
    services.google, services.calendar = FakeGoogle(), FakeCalendar()
    when = future()
    result = run(services.reminders.create("dentista", when, "weekly"))
    assert result["calendar"] is True
    created = services.calendar.created[0]
    assert created["summary"] == "Lembrete: dentista"
    assert created["popup_minutes"] == 0 and created["recurrence"] == "RRULE:FREQ=WEEKLY"
    assert services.reminders.upcoming()[0]["calendar_event_id"] == "evt1"
    run(services.reminders.cancel(result["id"]))
    assert services.calendar.deleted == ["evt1"]


def test_tool_rejects_past_dates(services, llm):
    past = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
    llm.queue(call("reminder_create", text="x", when=past), say("Não deu."))
    reply = run(Agent(services, build_registry()).handle(Turn(channel="ui", text="lembra")))
    assert reply.tools[0]["ok"] is False and "já passou" in reply.tools[0]["summary"]
    assert services.reminders.upcoming() == []


def test_naive_datetime_gets_user_timezone(services, llm):
    when = future().replace(tzinfo=None)
    llm.queue(call("reminder_create", text="x", when=when.isoformat()), say("ok"))
    run(Agent(services, build_registry()).handle(Turn(channel="ui", text="lembra")))
    due = parse_iso(services.reminders.upcoming()[0]["due_at"])
    assert due == when.replace(tzinfo=TZ).astimezone(timezone.utc)


def _insert(services, text, due, repeat="none"):
    return services.db.execute(
        "INSERT INTO reminders (text, due_at, repeat, status, created_at) VALUES (?, ?, ?, 'scheduled', ?)",
        (text, iso(due), repeat, iso(due)),
    )


def test_deliver_due_on_time_late_and_missed(services):
    now = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
    on_time = _insert(services, "beber água", now - timedelta(seconds=30))
    late = _insert(services, "ligar pro João", now - timedelta(minutes=30))
    missed = _insert(services, "antigo", now - timedelta(days=2))
    delivered = run(services.reminders.deliver_due(now))
    assert sorted(delivered) == sorted([on_time, late])
    sent = services.whatsapp.sent
    assert "Lembrete: beber água" in sent
    assert any(s.startswith("Lembrete: ligar pro João (atrasado; era") for s in sent)
    statuses = {r["id"]: r["status"] for r in services.db.query("SELECT id, status FROM reminders")}
    assert statuses == {on_time: "delivered", late: "delivered", missed: "missed"}


def test_failed_delivery_keeps_reminder_scheduled(services):
    services.whatsapp = FakeWhatsApp(ok=False)
    now = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
    rid = _insert(services, "x", now - timedelta(seconds=5))
    assert run(services.reminders.deliver_due(now)) == []
    assert services.db.query_one("SELECT status FROM reminders WHERE id = ?", (rid,))["status"] == "scheduled"


def test_daily_repeat_reschedules_to_next_future_occurrence(services):
    now = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
    rid = _insert(services, "remédio", now - timedelta(days=3, minutes=1), "daily")
    run(services.reminders.deliver_due(now))  # atrasado demais: não entrega, mas reagenda
    row = services.db.query_one("SELECT * FROM reminders WHERE id = ?", (rid,))
    assert row["status"] == "scheduled"
    assert parse_iso(row["due_at"]) == now - timedelta(minutes=1) + timedelta(days=1)
    assert services.whatsapp.sent == []


def test_recurring_reminder_in_the_past_starts_next_occurrence(services):
    when = datetime.now(TZ).replace(microsecond=0) - timedelta(hours=3)
    result = run(services.reminders.create("remédio", when, "daily"))
    due = parse_iso(services.reminders.upcoming()[0]["due_at"])
    assert due == (when + timedelta(days=1)).astimezone(timezone.utc)
    assert run(services.reminders.deliver_due()) == []  # não dispara "atrasado" na criação
    assert result["id"]


def test_undelivered_notification_is_not_stored(services):
    services.whatsapp = FakeWhatsApp(ok=False)
    assert run(services.outbound.notify("Lembrete: x")) is False
    assert services.conversations.recent(5) == []


def test_month_math():
    assert add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28)
    assert add_months(datetime(2026, 12, 15), 1) == datetime(2027, 1, 15)
    assert next_occurrence(datetime(2026, 3, 31), "monthly") == datetime(2026, 4, 30)
