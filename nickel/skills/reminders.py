"""Lembretes: SQLite + Google Agenda (avisa no celular com o PC desligado) + WhatsApp quando ligado."""

from __future__ import annotations

import asyncio
import calendar as _calendar
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from nickel.core.db import iso, parse_iso, utcnow
from nickel.core.skills import ToolContext, ToolRegistry, ToolResult

if TYPE_CHECKING:  # pragma: no cover
    from nickel.services import Services

log = logging.getLogger(__name__)

REPEATS = ["none", "daily", "weekly", "monthly"]
RRULES = {"daily": "RRULE:FREQ=DAILY", "weekly": "RRULE:FREQ=WEEKLY", "monthly": "RRULE:FREQ=MONTHLY"}
REPEAT_LABEL = {"none": "", "daily": " (todo dia)", "weekly": " (toda semana)", "monthly": " (todo mês)"}
_WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def parse_when(value: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def add_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year, month = dt.year + month_index // 12, month_index % 12 + 1
    day = min(dt.day, _calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def next_occurrence(due: datetime, repeat: str) -> datetime:
    if repeat == "daily":
        return due + timedelta(days=1)
    if repeat == "weekly":
        return due + timedelta(weeks=1)
    if repeat == "monthly":
        return add_months(due, 1)
    raise ValueError(repeat)


def format_local(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    return f"{_WEEKDAYS[local.weekday()]} {local.strftime('%d/%m')} às {local.strftime('%H:%M')}"


class ReminderService:
    def __init__(self, services: "Services") -> None:
        self.services = services
        self.tz = ZoneInfo(services.settings.timezone)

    async def create(self, text: str, when: datetime, repeat: str = "none") -> dict[str, Any]:
        while repeat != "none" and when <= utcnow():
            when = next_occurrence(when, repeat)
        db = self.services.db
        reminder_id = db.execute(
            "INSERT INTO reminders (text, due_at, repeat, status, created_at) VALUES (?, ?, ?, 'scheduled', ?)",
            (text.strip(), iso(when), repeat, iso(utcnow())),
        )
        result: dict[str, Any] = {"id": reminder_id, "due": format_local(when, self.tz), "calendar": False}
        settings = self.services.settings
        if settings.reminders_use_calendar and self.services.google_ready():
            local = when.astimezone(self.tz)
            try:
                event = await self.services.calendar.create(
                    summary=f"Lembrete: {text.strip()}",
                    start=local.isoformat(),
                    end=(local + timedelta(minutes=10)).isoformat(),
                    description="Criado pelo NICKEL.",
                    popup_minutes=0,
                    recurrence=RRULES.get(repeat),
                )
                db.execute("UPDATE reminders SET calendar_event_id = ? WHERE id = ?", (event.get("id"), reminder_id))
                result["calendar"] = True
            except Exception as exc:
                log.exception("Falha ao criar o evento do lembrete na Agenda")
                result["calendar_error"] = str(exc)
        return result

    def upcoming(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.services.db.query(
            "SELECT * FROM reminders WHERE status = 'scheduled' ORDER BY due_at LIMIT ?", (limit,)
        )
        for row in rows:
            row["due_local"] = format_local(parse_iso(row["due_at"]), self.tz)
        return rows

    async def cancel(self, reminder_id: int) -> dict[str, Any] | None:
        db = self.services.db
        row = db.query_one("SELECT * FROM reminders WHERE id = ? AND status = 'scheduled'", (reminder_id,))
        if not row:
            return None
        db.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ?", (reminder_id,))
        if row.get("calendar_event_id") and self.services.google_ready():
            try:
                await self.services.calendar.delete(row["calendar_event_id"])
            except Exception:
                log.exception("Falha ao remover o evento %s da Agenda", row["calendar_event_id"])
        return row

    async def deliver_due(self, now: datetime | None = None) -> list[int]:
        now = now or utcnow()
        db = self.services.db
        grace = timedelta(hours=self.services.settings.reminder_late_grace_hours)
        delivered: list[int] = []
        rows = db.query("SELECT * FROM reminders WHERE status = 'scheduled' AND due_at <= ?", (iso(now),))
        for row in rows:
            due = parse_iso(row["due_at"])
            late = now - due
            repeat = row["repeat"]
            if late > grace:
                if repeat == "none":
                    db.execute("UPDATE reminders SET status = 'missed' WHERE id = ?", (row["id"],))
                    continue
            else:
                suffix = f" (atrasado; era {due.astimezone(self.tz).strftime('%H:%M')})" if late > timedelta(minutes=2) else ""
                if not await self.services.outbound.notify(f"Lembrete: {row['text']}{suffix}"):
                    continue  # nenhum canal entregou; tenta de novo no próximo ciclo
                delivered.append(row["id"])
            if repeat == "none":
                db.execute(
                    "UPDATE reminders SET status = 'delivered', delivered_at = ? WHERE id = ?", (iso(now), row["id"])
                )
            else:
                following = next_occurrence(due, repeat)
                while following <= now:
                    following = next_occurrence(following, repeat)
                db.execute(
                    "UPDATE reminders SET due_at = ?, delivered_at = ? WHERE id = ?",
                    (iso(following), iso(now), row["id"]),
                )
        return delivered

    async def run(self, stop: asyncio.Event) -> None:
        interval = self.services.settings.reminder_poll_seconds
        while not stop.is_set():
            try:
                await self.deliver_due()
            except Exception:
                log.exception("Ciclo de lembretes falhou")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


def register(registry: ToolRegistry) -> None:
    @registry.add(
        "reminder_create",
        "Cria um lembrete. 'when' em ISO 8601 com fuso (ex.: 2026-10-15T09:00:00-03:00). "
        "Também vira evento no Google Agenda quando conectado, para avisar no celular.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "O que lembrar, curto"},
                "when": {"type": "string", "description": "Data e hora ISO 8601 com fuso"},
                "repeat": {"type": "string", "enum": REPEATS},
            },
            "required": ["text", "when"],
        },
    )
    async def reminder_create(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        service: ReminderService = ctx.services.reminders
        try:
            when = parse_when(args["when"], service.tz)
        except ValueError:
            return ToolResult.fail(f"Data inválida: {args['when']}. Use ISO 8601.")
        repeat = args.get("repeat") or "none"
        if when <= utcnow() and repeat == "none":
            return ToolResult.fail(f"{format_local(when, service.tz)} já passou. Informe um horário futuro.")
        result = await service.create(args["text"], when, repeat)
        where = " (também no Google Agenda)" if result["calendar"] else ""
        if result.get("calendar_error"):
            where = " (só local: falhou ao criar na Agenda)"
        summary = f"Lembrete #{result['id']}: {args['text'].strip()} — {result['due']}{REPEAT_LABEL[repeat]}{where}."
        return ToolResult(True, summary, result)

    @registry.add("reminder_list", "Lista os próximos lembretes agendados.")
    async def reminder_list(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
        rows = ctx.services.reminders.upcoming(15)
        if not rows:
            return ToolResult(True, "Nenhum lembrete agendado.", {"reminders": []})
        lines = [f"#{r['id']} {r['text']} — {r['due_local']}{REPEAT_LABEL.get(r['repeat'], '')}" for r in rows]
        return ToolResult(True, "; ".join(lines), {"reminders": rows})

    @registry.add(
        "reminder_cancel",
        "Cancela um lembrete pelo número (#id).",
        {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    )
    async def reminder_cancel(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        row = await ctx.services.reminders.cancel(int(args["id"]))
        if not row:
            return ToolResult.fail(f"Lembrete #{args['id']} não existe ou já passou.")
        return ToolResult(True, f"Lembrete #{row['id']} cancelado: {row['text']}.")
