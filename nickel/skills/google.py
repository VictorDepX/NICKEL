"""Gmail e Google Agenda (portados do v1, com argumentos que um LLM consegue preencher)."""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps
from typing import Any
from zoneinfo import ZoneInfo

from nickel.core.skills import ToolContext, ToolRegistry, ToolResult
from nickel.integrations.google import NotConnected


def _configured(services) -> bool:
    return services.google_configured()


def _guard(handler):
    @wraps(handler)
    async def wrapper(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            return await handler(ctx, args)
        except NotConnected as exc:
            return ToolResult.fail(exc.status.get("message", "Google não conectado."), status=exc.status.get("status"))

    return wrapper


def _local(value: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def register(registry: ToolRegistry) -> None:
    # ------------------------------------------------------------------ Gmail
    @registry.add(
        "email_search",
        "Busca e-mails no Gmail (sintaxe de busca do Gmail: from:, subject:, is:unread, newer_than:2d...).",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"],
        },
        available=_configured,
    )
    @_guard
    async def email_search(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        results = await ctx.services.gmail.search(args["query"], min(int(args.get("max_results") or 5), 10))
        if not results:
            return ToolResult(True, "Nenhum e-mail encontrado.", {"results": []})
        lines = [f"{r['from']} — {r['subject']} (id {r['id']})" for r in results]
        return ToolResult(True, f"{len(results)} e-mail(s): " + "; ".join(lines), {"results": results})

    @registry.add(
        "email_read",
        "Lê um e-mail. Use 'message_id' se souber; senão, lê o mais recente que casar com 'query' (padrão: caixa de entrada).",
        {"type": "object", "properties": {"message_id": {"type": "string"}, "query": {"type": "string"}}},
        available=_configured,
    )
    @_guard
    async def email_read(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        gmail = ctx.services.gmail
        message_id = args.get("message_id")
        if not message_id:
            found = await gmail.search(args.get("query") or "in:inbox", 1)
            if not found:
                return ToolResult(True, "Nenhum e-mail encontrado.")
            message_id = found[0]["id"]
        message = await gmail.read(message_id)
        return ToolResult(True, f"E-mail de {message['from']}: {message['subject']}.", message)

    @registry.add(
        "email_draft",
        "Cria um rascunho no Gmail (não envia).",
        {
            "type": "object",
            "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "subject", "body"],
        },
        available=_configured,
    )
    @_guard
    async def email_draft(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        await ctx.services.gmail.draft(args["to"], args["subject"], args["body"])
        return ToolResult(True, f"Rascunho criado para {args['to']}: '{args['subject']}'.")

    @registry.add(
        "email_send",
        "Envia um e-mail pelo Gmail. Exige confirmação do usuário.",
        {
            "type": "object",
            "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "subject", "body"],
        },
        confirm=True,
        describe=lambda a: f"enviar e-mail para {a.get('to')} com assunto '{a.get('subject')}'",
        available=_configured,
    )
    @_guard
    async def email_send(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        await ctx.services.gmail.send(args["to"], args["subject"], args["body"])
        return ToolResult(True, f"E-mail enviado para {args['to']}.")

    # ------------------------------------------------------------------ Agenda
    @registry.add(
        "calendar_list",
        "Lista eventos do Google Agenda num intervalo (ISO 8601). Padrão: agora até 7 dias.",
        {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "max_results": {"type": "integer"},
            },
        },
        available=_configured,
    )
    @_guard
    async def calendar_list(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        tz = ZoneInfo(ctx.settings.timezone)
        start = _local(args["start"], tz) if args.get("start") else datetime.now(tz)
        end = _local(args["end"], tz) if args.get("end") else start + timedelta(days=7)
        events = await ctx.services.calendar.list(start.isoformat(), end.isoformat(), min(int(args.get("max_results") or 10), 25))
        if not events:
            return ToolResult(True, "Nenhum evento no período.", {"events": []})
        lines = [f"{e['start']} {e['summary']}" for e in events]
        return ToolResult(True, "; ".join(lines), {"events": events})

    @registry.add(
        "calendar_create",
        "Cria um evento no Google Agenda. Exige confirmação. 'start'/'end' em ISO 8601 com fuso; sem 'end', dura 1 hora.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["title", "start"],
        },
        confirm=True,
        describe=lambda a: f"criar o evento '{a.get('title')}' em {a.get('start')}",
        available=_configured,
    )
    @_guard
    async def calendar_create(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        tz = ZoneInfo(ctx.settings.timezone)
        start = _local(args["start"], tz)
        end = _local(args["end"], tz) if args.get("end") else start + timedelta(hours=1)
        event = await ctx.services.calendar.create(
            summary=args["title"],
            start=start.isoformat(),
            end=end.isoformat(),
            description=args.get("description"),
            location=args.get("location"),
        )
        return ToolResult(True, f"Evento criado: {args['title']}.", {"id": event.get("id"), "link": event.get("htmlLink")})

    @registry.add(
        "calendar_update",
        "Altera um evento existente (use o id de calendar_list). Exige confirmação.",
        {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["event_id"],
        },
        confirm=True,
        describe=lambda a: "alterar o evento "
        + str(a.get("event_id"))
        + ": "
        + ", ".join(f"{k}={v}" for k, v in a.items() if k != "event_id"),
        available=_configured,
    )
    @_guard
    async def calendar_update(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        tz = ZoneInfo(ctx.settings.timezone)
        changes = {
            "summary": args.get("title"),
            "description": args.get("description"),
            "location": args.get("location"),
            "start": _local(args["start"], tz).isoformat() if args.get("start") else None,
            "end": _local(args["end"], tz).isoformat() if args.get("end") else None,
        }
        await ctx.services.calendar.patch(args["event_id"], changes)
        return ToolResult(True, "Evento alterado.")
