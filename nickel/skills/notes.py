"""Captura de pensamentos e busca de notas no Obsidian."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from nickel.core.skills import ToolContext, ToolRegistry, ToolResult
from nickel.integrations.obsidian import KINDS

_SOURCES = {"whatsapp": "whatsapp", "voice": "voz", "ui": "ui"}


def _available(services) -> bool:
    return services.obsidian is not None and services.obsidian.available


def register(registry: ToolRegistry) -> None:
    @registry.add(
        "notes_capture",
        "Registra um pensamento avulso, ideia, tarefa solta ou reflexão como nota no Obsidian (pasta de pensamentos). "
        "Organize o conteúdo em markdown limpo sem inventar informação. O texto original é guardado automaticamente.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título curto e específico (até ~8 palavras)"},
                "content": {"type": "string", "description": "Conteúdo organizado em markdown"},
                "kind": {"type": "string", "enum": list(KINDS)},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "1 a 4 tags temáticas"},
                "links": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Títulos de notas existentes citadas pelo usuário",
                },
            },
            "required": ["title", "content"],
        },
        available=_available,
    )
    async def notes_capture(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        vault = ctx.services.obsidian
        now = datetime.now(ZoneInfo(ctx.settings.timezone))
        path, links = vault.create_note(
            title=args["title"],
            content=args["content"],
            kind=args.get("kind") or "pensamento",
            tags=args.get("tags") or [],
            links=args.get("links") or [],
            source=_SOURCES.get(ctx.channel, ctx.channel),
            original=ctx.user_text,
            now=now,
        )
        relative = path.relative_to(vault.vault_path)
        return ToolResult(True, f"Nota criada: {relative}.", {"path": str(relative), "links": links})

    @registry.add(
        "notes_search",
        "Procura nas notas de pensamentos (ou no vault inteiro) por um termo.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "whole_vault": {"type": "boolean", "description": "Buscar no vault todo, não só nos pensamentos"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        available=_available,
    )
    async def notes_search(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        results = ctx.services.obsidian.search(
            args["query"], limit=min(int(args.get("limit") or 5), 10), whole_vault=bool(args.get("whole_vault"))
        )
        if not results:
            return ToolResult(True, f"Nenhuma nota com '{args['query']}'.", {"results": []})
        titles = ", ".join(item["title"] for item in results)
        return ToolResult(True, f"{len(results)} nota(s): {titles}.", {"results": results})
