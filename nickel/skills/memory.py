"""Memória de longo prazo opt-in (policy_memory.md): só preferências e padrões operacionais."""

from __future__ import annotations

from typing import Any

from nickel.core.skills import ToolContext, ToolRegistry, ToolResult


def register(registry: ToolRegistry) -> None:
    @registry.add(
        "memory_save",
        "Guarda uma preferência ou padrão operacional do usuário (nunca emoções ou traços psicológicos). "
        "Exige confirmação.",
        {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Ex.: 'playlist de foco'"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
        confirm=True,
        describe=lambda a: f"guardar na memória '{a.get('key')}': {a.get('value')}",
    )
    async def memory_save(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        ctx.services.memory.save(args["key"], args["value"])
        return ToolResult(True, f"Guardado: {args['key']}.")

    @registry.add("memory_list", "Lista o que está guardado na memória.")
    async def memory_list(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
        items = ctx.services.memory.all()
        if not items:
            return ToolResult(True, "Memória vazia.", {"items": []})
        return ToolResult(True, "; ".join(f"{i['key']}: {i['value']}" for i in items), {"items": items})

    @registry.add(
        "memory_forget",
        "Apaga um item da memória pela chave.",
        {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    )
    async def memory_forget(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if ctx.services.memory.delete(args["key"]):
            return ToolResult(True, f"Apagado: {args['key']}.")
        return ToolResult.fail(f"Não há '{args['key']}' na memória.")
