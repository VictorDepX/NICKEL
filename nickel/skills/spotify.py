"""Controle do Spotify."""

from __future__ import annotations

from typing import Any

from nickel.core.skills import ToolContext, ToolRegistry, ToolResult
from nickel.integrations.spotify import SpotifyError

KINDS = ["track", "album", "playlist", "artist"]


def _configured(services) -> bool:
    return services.spotify_configured()


def _not_ready(ctx: ToolContext) -> ToolResult | None:
    status = ctx.services.spotify.status()
    if status["status"] != "ready":
        return ToolResult.fail(status["message"], status=status["status"])
    return None


def register(registry: ToolRegistry) -> None:
    @registry.add(
        "spotify_play",
        "Toca no Spotify. Com 'query', busca e toca o primeiro resultado do tipo 'kind'. "
        "Com 'uri' (spotify:track:..., spotify:album:...), toca exatamente aquele item. Sem nada, retoma a reprodução.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Ex.: 'Clube da Esquina Milton Nascimento'"},
                "kind": {"type": "string", "enum": KINDS, "description": "Tipo buscado. Padrão: track"},
                "uri": {"type": "string", "description": "URI do Spotify, se já conhecida"},
            },
        },
        available=_configured,
    )
    async def spotify_play(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if (blocked := _not_ready(ctx)) is not None:
            return blocked
        spotify = ctx.services.spotify
        try:
            uri = args.get("uri")
            label = uri
            if not uri and args.get("query"):
                kind = args.get("kind") or "track"
                results = await spotify.search(args["query"], kind, 5)
                if not results:
                    return ToolResult.fail(f"Nada encontrado no Spotify para '{args['query']}'.")
                first = results[0]
                uri, label = first["uri"], f"{first['name']} — {first['artists']}".strip(" —")
                ctx.links.append(first["url"])
            if uri and uri.startswith("spotify:track:"):
                await spotify.play(uris=[uri])
            elif uri:
                await spotify.play(context_uri=uri)
            else:
                await spotify.play()
                return ToolResult(True, "Reprodução retomada.")
            return ToolResult(True, f"Tocando: {label}.", {"uri": uri})
        except SpotifyError as exc:
            return ToolResult.fail(str(exc), code=exc.code)

    @registry.add("spotify_pause", "Pausa o Spotify.", available=_configured)
    async def spotify_pause(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
        if (blocked := _not_ready(ctx)) is not None:
            return blocked
        try:
            await ctx.services.spotify.pause()
        except SpotifyError as exc:
            return ToolResult.fail(str(exc), code=exc.code)
        return ToolResult(True, "Pausado.")

    @registry.add("spotify_next", "Pula para a próxima faixa.", available=_configured)
    async def spotify_next(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
        if (blocked := _not_ready(ctx)) is not None:
            return blocked
        try:
            await ctx.services.spotify.next()
        except SpotifyError as exc:
            return ToolResult.fail(str(exc), code=exc.code)
        return ToolResult(True, "Próxima faixa.")

    @registry.add("spotify_previous", "Volta para a faixa anterior.", available=_configured)
    async def spotify_previous(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
        if (blocked := _not_ready(ctx)) is not None:
            return blocked
        try:
            await ctx.services.spotify.previous()
        except SpotifyError as exc:
            return ToolResult.fail(str(exc), code=exc.code)
        return ToolResult(True, "Faixa anterior.")

    @registry.add("spotify_now_playing", "Diz o que está tocando no Spotify agora.", available=_configured)
    async def spotify_now_playing(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
        if (blocked := _not_ready(ctx)) is not None:
            return blocked
        try:
            current = await ctx.services.spotify.now_playing()
        except SpotifyError as exc:
            return ToolResult.fail(str(exc), code=exc.code)
        if not current:
            return ToolResult(True, "Nada tocando agora.")
        state = "tocando" if current["is_playing"] else "pausado"
        return ToolResult(True, f"{current['name']} — {current['artists']} ({state}).", current)
