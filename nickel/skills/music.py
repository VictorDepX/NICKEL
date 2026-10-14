"""Reconhecer música e achar links (Spotify primeiro, YouTube como reserva)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nickel.core.skills import ToolContext, ToolRegistry, ToolResult
from nickel.integrations.music import MusicMatch


def _summary(match: MusicMatch) -> str:
    link = match.spotify_url or match.youtube_url
    where = "no Spotify" if match.spotify_url else "no YouTube" if match.youtube_url else ""
    text = f"'{match.title}' — {match.artist}".strip(" —")
    return f"{text}. {where}: {link}" if link else f"{text}. Sem link no Spotify nem no YouTube."


def _last_audio(ctx: ToolContext) -> Path | None:
    if ctx.last_audio_path and ctx.last_audio_path.exists():
        return ctx.last_audio_path
    for message in reversed(ctx.services.conversations.recent(20)):
        for attachment in message.attachments:
            if attachment.get("type") == "audio" and Path(attachment.get("path", "")).exists():
                return Path(attachment["path"])
    return None


def register(registry: ToolRegistry) -> None:
    @registry.add(
        "music_recognize",
        "Identifica uma música. source='microphone' grava o microfone do PC por alguns segundos "
        "(use quando o usuário pedir pelo PC/voz 'que música é essa'). source='last_audio' usa o último áudio recebido.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["microphone", "last_audio"]},
                "seconds": {"type": "integer", "description": "Duração da gravação (5 a 20). Padrão: 10"},
            },
            "required": ["source"],
        },
        available=lambda services: services.music is not None,
    )
    async def music_recognize(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        services = ctx.services
        if args["source"] == "microphone":
            if services.recorder is None:
                return ToolResult.fail("Microfone indisponível nesta máquina (instale o extra 'voice').")
            seconds = min(max(int(args.get("seconds") or services.settings.music_record_seconds), 5), 20)
            path = await services.recorder.record_fixed(seconds)
        else:
            path = _last_audio(ctx)
            if path is None:
                return ToolResult.fail("Não há áudio recente para analisar. Grave um trecho da música e envie.")
        match = await services.music.recognize(path)
        if match is None:
            return ToolResult.fail("Não reconheci a música. Tente um trecho mais longo e com menos ruído.")
        if match.best_link:
            ctx.links.append(match.best_link)
        return ToolResult(True, _summary(match), match.as_dict())

    @registry.add(
        "music_find",
        "Acha uma música pelo nome e devolve o link no Spotify ou, se não houver, no YouTube.",
        {
            "type": "object",
            "properties": {"title": {"type": "string"}, "artist": {"type": "string"}},
            "required": ["title"],
        },
        available=lambda services: services.music is not None,
    )
    async def music_find(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        match = MusicMatch(title=args["title"], artist=args.get("artist", ""))
        await ctx.services.music.attach_links(match)
        if not match.best_link:
            return ToolResult.fail(f"Não achei '{match.title}' no Spotify nem no YouTube.")
        ctx.links.append(match.best_link)
        return ToolResult(True, _summary(match), match.as_dict())
