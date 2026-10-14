"""API local do NICKEL: UI, OAuth, voz e entrada do WhatsApp."""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from nickel.channels.voice import VoiceController
from nickel.channels.whatsapp import WhatsAppChannel, prune_media
from nickel.config import Settings, load_settings
from nickel.core.agent import Agent, Turn
from nickel.core.skills import ToolRegistry
from nickel.services import Services, build_services
from nickel.skills import build_registry

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "ui" / "static"


def create_app(
    settings: Settings | None = None,
    services: Services | None = None,
    registry: ToolRegistry | None = None,
    *,
    background: bool = True,
) -> FastAPI:
    settings = settings or (services.settings if services else load_settings())
    services = services or build_services(settings)
    registry = registry or build_registry()
    agent = Agent(services, registry)
    whatsapp = WhatsAppChannel(services, agent)
    voice = VoiceController(services, agent)
    pending_tasks: set[asyncio.Task] = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        pending_tasks.add(task)
        task.add_done_callback(pending_tasks.discard)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        stop = asyncio.Event()
        workers: list[asyncio.Task] = []
        if background:
            removed = prune_media(settings.media_dir)
            if removed:
                log.info("%s mídia(s) antiga(s) removida(s)", removed)
        if background and services.reminders is not None:
            workers.append(asyncio.create_task(services.reminders.run(stop)))
        if background and services.stt is not None and hasattr(services.stt, "warm_up"):
            workers.append(asyncio.create_task(services.stt.warm_up()))
        try:
            yield
        finally:
            stop.set()
            for task in workers:
                task.cancel()
            for client in (services.llm, services.spotify, services.whatsapp):
                if client is not None and hasattr(client, "aclose"):
                    await client.aclose()

    app = FastAPI(title="NICKEL", version="2.0.0", lifespan=lifespan)
    app.state.services = services
    app.state.agent = agent
    app.state.registry = registry
    app.state.voice = voice
    app.state.whatsapp = whatsapp
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ------------------------------------------------------------------ UI
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        llm_health = await services.llm.health() if hasattr(services.llm, "health") else {"ok": True}
        wa = await services.whatsapp.health() if services.whatsapp else {"ready": False, "detail": "BRIDGE_TOKEN ausente"}
        vault = services.obsidian
        return {
            "llm": llm_health,
            "whatsapp": wa,
            "google": services.google.status() if services.google else {"status": "disabled"},
            "spotify": services.spotify.status() if services.spotify else {"status": "disabled"},
            "obsidian": {
                "available": bool(vault and vault.available),
                "notes_dir": settings.obsidian_notes_dir,
                "vault": str(settings.obsidian_vault_path or ""),
            },
            "voice": voice.status(),
            "music": services.music is not None,
            "tools": [tool.name for tool in registry.available(services)],
        }

    @app.get("/api/messages")
    async def messages(limit: int = 60) -> list[dict[str, Any]]:
        return [message.__dict__ for message in services.conversations.recent(min(limit, 300))]

    @app.post("/api/chat")
    async def chat(payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Mensagem vazia.")
        reply = await agent.handle(Turn(channel="ui", text=text))
        return {"text": reply.text, "pending_action_id": reply.pending_action_id, "links": reply.links}

    @app.get("/api/pending")
    async def pending() -> list[dict[str, Any]]:
        return [action.__dict__ for action in services.pending.list_pending()]

    @app.post("/api/pending/{action_id}/confirm")
    async def confirm(action_id: str) -> dict[str, Any]:
        reply = await agent.confirm(action_id, "ui")
        return {"text": reply.text}

    @app.post("/api/pending/{action_id}/cancel")
    async def cancel(action_id: str) -> dict[str, Any]:
        reply = await agent.cancel(action_id, "ui")
        return {"text": reply.text}

    @app.get("/api/reminders")
    async def reminders() -> list[dict[str, Any]]:
        return services.reminders.upcoming(50)

    @app.delete("/api/reminders/{reminder_id}")
    async def delete_reminder(reminder_id: int) -> dict[str, Any]:
        row = await services.reminders.cancel(reminder_id)
        if not row:
            raise HTTPException(404, "Lembrete não encontrado.")
        return {"cancelled": reminder_id}

    @app.get("/api/audit")
    async def audit(limit: int = 80) -> list[dict[str, Any]]:
        return services.audit.recent(min(limit, 500))

    @app.get("/api/memory")
    async def memory() -> list[dict[str, str]]:
        return services.memory.all()

    @app.delete("/api/memory/{key}")
    async def forget(key: str) -> dict[str, Any]:
        return {"deleted": services.memory.delete(key)}

    # ------------------------------------------------------------------ OAuth
    @app.get("/auth/google/start", include_in_schema=False)
    async def google_start():
        from nickel.integrations.google import NotConnected

        try:
            return RedirectResponse(services.google.start())
        except NotConnected as exc:
            raise HTTPException(400, exc.status.get("message")) from exc

    @app.get("/auth/google/callback", include_in_schema=False)
    async def google_callback(code: str, state: str):
        try:
            await asyncio.to_thread(services.google.finish, code, state)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        services.audit.record("oauth", "google", "connected")
        return RedirectResponse("/?connected=google")

    @app.get("/auth/spotify/start", include_in_schema=False)
    async def spotify_start():
        from nickel.integrations.spotify import SpotifyError

        try:
            return RedirectResponse(services.spotify.start())
        except SpotifyError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/auth/spotify/callback", include_in_schema=False)
    async def spotify_callback(code: str, state: str):
        try:
            await services.spotify.finish(code, state)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        services.audit.record("oauth", "spotify", "connected")
        return RedirectResponse("/?connected=spotify")

    # ------------------------------------------------------------------ Voz
    @app.post("/voice/toggle")
    async def voice_toggle() -> dict[str, str]:
        return {"state": await voice.toggle()}

    # ------------------------------------------------------------------ WhatsApp
    @app.post("/channels/whatsapp/inbound", status_code=202)
    async def whatsapp_inbound(
        request: Request, x_nickel_token: str | None = Header(default=None)
    ) -> dict[str, bool]:
        expected = settings.bridge_token
        if not expected:
            raise HTTPException(503, "BRIDGE_TOKEN não configurado.")
        if not x_nickel_token or not hmac.compare_digest(x_nickel_token, expected):
            raise HTTPException(401, "Token inválido.")
        payload = await request.json()
        spawn(whatsapp.handle_inbound(payload))
        return {"accepted": True}

    return app


def main_app() -> FastAPI:
    """Fábrica usada pelo uvicorn (`nickel.app:main_app`)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
