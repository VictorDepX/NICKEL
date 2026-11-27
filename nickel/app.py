"""API local do NICKEL: UI, OAuth, voz e entrada do WhatsApp."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from nickel.channels.voice import VoiceController
from nickel.channels.whatsapp import WhatsAppChannel, prune_media
from nickel.config import Settings, load_settings
from nickel.core.agent import Agent, Turn
from nickel.core.connectors import build_connectors
from nickel.core.db import utcnow
from nickel.core.events import CATALOG, PHASE_LABELS, PHASES
from nickel.core.report import render_run_report
from nickel.core.trace import new_run_id, run_scope
from nickel.core.skills import ToolRegistry
from nickel.core.sysmon import MemorySampler
from nickel.services import SPEECH_MAX_CHARS, Services, build_services
from nickel.skills import build_registry
from nickel.skills.reminders import REPEATS, format_local, parse_when_or_clock

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "ui" / "static"
VERSION = "2.0.0"
HEALTH_TIMEOUT = 3.0  # segundos: teto da consulta de saúde no startup
SSE_PING = 15.0  # segundos entre comentários `: ping`
SSE_POLL = 1.0  # segundos entre checagens de desconexão
SSE_REPLAY = 100  # eventos reprisados quando `after` é omitido
SSE_PAGE = 500  # tamanho do lote ao paginar `since`
SPEAK_KEY = "ui.speak"  # StateStore: "1" fala as respostas do chat da GUI
# Ligado por `nickel serve` no Ctrl+C: os streams SSE abertos (aba do Monitor) encerram em até SSE_POLL,
# antes de o uvicorn esgotar `timeout_graceful_shutdown` e cancelar a conexão à força.
SHUTDOWN = threading.Event()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _frame(event: dict[str, Any]) -> str:
    return f"id: {event['id']}\nevent: audit\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


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
    memory_sampler = MemorySampler()
    pending_tasks: set[asyncio.Task] = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        pending_tasks.add(task)
        task.add_done_callback(pending_tasks.discard)

    async def _bounded(coro, fallback: dict[str, Any], timeout: float | None) -> dict[str, Any]:
        if timeout is None:
            return await coro
        try:
            return await asyncio.wait_for(coro, timeout)
        except Exception as exc:  # offline, lento ou com erro: registra o que houver
            return {**fallback, "detail": str(exc) or type(exc).__name__}

    async def services_snapshot(timeout: float | None = None) -> dict[str, Any]:
        """Estado dos serviços (sem tokens/chaves), usado por `/api/state` e por `system/health`."""

        async def llm_health() -> dict[str, Any]:
            return await services.llm.health() if hasattr(services.llm, "health") else {"ok": True}

        async def wa_health() -> dict[str, Any]:
            if not services.whatsapp:
                return {"ready": False, "detail": "BRIDGE_TOKEN ausente"}
            return await services.whatsapp.health()

        llm_state, wa, tts_state = await asyncio.gather(
            _bounded(llm_health(), {"ok": False}, timeout),
            _bounded(wa_health(), {"ready": False}, timeout),
            services.tts_status(),
        )
        vault = services.obsidian
        return {
            "llm": llm_state,
            "whatsapp": wa,
            "google": services.google.status() if services.google else {"status": "disabled"},
            "spotify": services.spotify.status() if services.spotify else {"status": "disabled"},
            "obsidian": {
                "available": bool(vault and vault.available),
                "notes_dir": settings.obsidian_notes_dir,
                "vault": str(settings.obsidian_vault_path or ""),
            },
            "voice": {**voice.status(), "tts": tts_state},
        }

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        stop = asyncio.Event()
        workers: list[asyncio.Task] = []
        SHUTDOWN.clear()
        if background:
            removed = prune_media(settings.media_dir)
            if removed:
                log.info("%s mídia(s) antiga(s) removida(s)", removed)
        if background and services.reminders is not None:
            workers.append(asyncio.create_task(services.reminders.run(stop)))
        if background:
            workers.append(asyncio.create_task(memory_sampler.run(stop)))
        if background and services.stt is not None and hasattr(services.stt, "warm_up"):
            workers.append(asyncio.create_task(services.stt.warm_up()))
        async def announce_health() -> None:
            try:
                services.audit.record("system", "nickel", "health", await services_snapshot(HEALTH_TIMEOUT))
            except Exception:
                log.exception("falha ao registrar o evento de saúde")

        try:
            try:
                removed = services.audit.prune_stale_progress()
                if removed:
                    log.info("%s evento(s) reasoning/progress órfão(s) removido(s)", removed)
            except Exception:
                log.exception("falha ao limpar raciocínio parcial antigo")
            try:
                services.audit.record(
                    "system",
                    "nickel",
                    "startup",
                    {
                        "version": VERSION,
                        "llm": f"{settings.llm_provider}:{settings.llm_model}",
                        "workspace_count": len(services.workspaces.all()),
                    },
                )
            except Exception:
                log.exception("falha ao registrar os eventos de startup")
            # A saúde consulta serviços (até HEALTH_TIMEOUT); roda depois do startup para não atrasar a subida.
            workers.append(asyncio.create_task(announce_health()))
            yield
        finally:
            try:  # nenhuma fala registra depois do `system/shutdown`, e nenhum player fica tocando
                await services.shutdown_speech()
            except Exception:
                log.exception("falha ao parar a fala no desligamento")
            services.audit.record("system", "nickel", "shutdown")
            stop.set()
            for task in workers:
                task.cancel()
            for client in (services.llm, services.llm_cloud, services.spotify, services.whatsapp, services.tts):
                if client is not None and hasattr(client, "aclose"):
                    await client.aclose()

    app = FastAPI(title="NICKEL", version=VERSION, lifespan=lifespan)

    @app.middleware("http")
    async def revalidate_ui(request, call_next):
        # A GUI muda a cada atualização do NICKEL: o navegador sempre revalida (ETag) em vez de usar cópia velha.
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response
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
        active = services.workspaces.active()
        snapshot = await services_snapshot()
        return {
            **snapshot,
            **build_connectors(
                snapshot,
                whatsapp=services.whatsapp is not None,
                music=services.music is not None,
                reminders=services.reminders is not None,
                obsidian_path=str(settings.obsidian_vault_path or ""),
            ),
            "music": services.music is not None,
            "tools": [tool.name for tool in registry.available(services)],
            "workspace": active.id,
            # Padrão efetivo de `think` quando a UI não manda: o do workspace ativo, senão LLM_THINK.
            "think_default": active.think if active.think is not None else settings.llm_think,
        }

    @app.get("/api/system/memory")
    async def system_memory() -> dict[str, Any]:
        return memory_sampler.snapshot()

    @app.get("/api/messages")
    async def messages(limit: int = 60, workspace: str | None = None) -> list[dict[str, Any]]:
        selected = services.workspaces.get(workspace) if workspace else services.workspaces.active()
        if selected is None:
            raise HTTPException(404, "Workspace inexistente.")
        return [message.__dict__ for message in services.conversations.recent(min(limit, 300), selected.conversation)]

    @app.get("/api/workspaces")
    async def workspaces() -> dict[str, Any]:
        manager = services.workspaces
        manager.refresh()
        active = manager.active()
        return {
            "active": active.id,
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "aliases": list(item.aliases),
                    "backend": item.backend,
                    "tools": None if item.tools is None else list(item.tools),
                    "notes_dir": item.notes_dir,
                }
                for item in manager.all()
            ],
        }

    @app.post("/api/workspaces/{workspace_id}/activate")
    async def activate_workspace(workspace_id: str) -> dict[str, Any]:
        try:
            selected = services.workspaces.activate(workspace_id)
        except KeyError:
            raise HTTPException(404, "Workspace inexistente.")
        return {"active": selected.id, "name": selected.name}

    def speak_preference() -> bool:
        """Preferência "Falar respostas" da GUI, guardada no StateStore (padrão: desligada)."""
        return services.state is not None and services.state.get(SPEAK_KEY) == "1"

    @app.post("/api/chat")
    async def chat(payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Mensagem vazia.")
        think = payload.get("think")
        speak = payload.get("speak")
        with run_scope(new_run_id()):  # a fala herda o run_id do turno (mesma execução no Monitor)
            reply = await agent.handle(Turn(channel="ui", text=text, think=think if isinstance(think, bool) else None))
            wants = speak if isinstance(speak, bool) else speak_preference()
            if wants and services.tts is not None and reply.text.strip():
                spawn(services.speak(reply.text, source="ui"))  # a resposta HTTP não espera a fala
        return {"text": reply.text, "pending_action_id": reply.pending_action_id, "links": reply.links}

    # ------------------------------------------------------------------ Preferências e fala
    @app.get("/api/preferences")
    async def get_preferences() -> dict[str, bool]:
        return {"speak": speak_preference()}

    @app.post("/api/preferences")
    async def set_preferences(payload: dict[str, Any]) -> dict[str, bool]:
        speak = payload.get("speak")
        if not isinstance(speak, bool):
            raise HTTPException(400, "Informe `speak` como verdadeiro ou falso.")
        services.state.set(SPEAK_KEY, "1" if speak else "0")
        return {"speak": speak}

    @app.post("/api/tts/speak", status_code=202)
    async def tts_speak(payload: dict[str, Any]) -> dict[str, bool]:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Texto vazio: informe o que falar.")
        if len(text) > SPEECH_MAX_CHARS:
            raise HTTPException(
                413, f"Texto longo demais para falar: o limite é {SPEECH_MAX_CHARS} caracteres (recebi {len(text)})."
            )
        spawn(services.speak(text, source="ui"))
        return {"accepted": True}

    @app.post("/api/tts/stop")
    async def tts_stop() -> dict[str, bool]:
        services.stop_speaking()
        return {"stopped": True}

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

    @app.post("/api/reminders", status_code=201)
    async def create_reminder(request: Request) -> dict[str, Any]:
        if not request.headers.get("content-type", "").lower().startswith("application/json"):
            raise HTTPException(422, "Envie o corpo como application/json.")
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(422, "Envie um objeto JSON com text, when e repeat.")
        service = services.reminders
        text = str(payload.get("text") or "").strip()
        if not text:
            raise HTTPException(422, "Escreva o que lembrar.")
        repeat = payload.get("repeat") or "none"
        if not isinstance(repeat, str) or repeat not in REPEATS:
            raise HTTPException(422, "Repetição inválida: use nenhuma, diária, semanal ou mensal.")
        try:
            when = parse_when_or_clock(str(payload.get("when") or ""), service.tz)
        except ValueError:
            raise HTTPException(422, "Horário inválido: use HH:MM ou data e hora (2026-11-27T15:02).") from None
        if when <= utcnow() and repeat == "none":
            raise HTTPException(422, f"{format_local(when, service.tz)} já passou. Escolha um horário futuro.")
        created = await service.create(text, when, repeat)
        row = next((r for r in service.upcoming(500) if r["id"] == created["id"]), None)
        return row or created

    @app.delete("/api/reminders/{reminder_id}")
    async def delete_reminder(reminder_id: int) -> dict[str, Any]:
        row = await services.reminders.cancel(reminder_id)
        if not row:
            raise HTTPException(404, "Lembrete não encontrado.")
        return {"cancelled": reminder_id}

    @app.get("/api/audit")
    async def audit(limit: int = 80) -> list[dict[str, Any]]:
        return services.audit.recent(min(limit, 500))

    @app.get("/api/events/stream")
    async def events_stream(request: Request, after: str | None = None, once: bool = False) -> StreamingResponse:
        last = _int_or_none(request.headers.get("last-event-id"))
        if last is None:
            last = _int_or_none(after)
        audit_log = services.audit

        async def backfill(start: int):
            """Eventos com id > start, em lotes até um lote curto (sem teto de 500)."""
            while True:
                batch = audit_log.since(start, SSE_PAGE)
                for item in batch:
                    yield item
                if len(batch) < SSE_PAGE:
                    return
                start = batch[-1]["id"]

        async def generate():
            queue = audit_log.subscribe()  # antes da reprise: sem lacunas
            try:
                sent = last if last is not None else 0
                if last is None:
                    for event in reversed(audit_log.recent(SSE_REPLAY)):
                        sent = max(sent, event["id"])
                        yield _frame(event)
                else:
                    async for event in backfill(sent):
                        sent = event["id"]
                        yield _frame(event)
                if once:
                    return
                idle = 0.0
                while not SHUTDOWN.is_set() and not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), SSE_POLL)
                    except asyncio.TimeoutError:
                        idle += SSE_POLL
                        if idle >= SSE_PING:
                            idle = 0.0
                            yield ": ping\n\n"
                        continue
                    idle = 0.0
                    if event["id"] <= sent:
                        continue
                    if event["id"] > sent + 1:  # fila cheia descartou eventos: preenche a lacuna
                        async for missing in backfill(sent):
                            if missing["id"] >= event["id"]:
                                break
                            sent = missing["id"]
                            yield _frame(missing)
                    if event["id"] > sent:
                        sent = event["id"]
                        yield _frame(event)
            except asyncio.CancelledError:
                # Desligamento do servidor (timeout_graceful_shutdown) com a aba aberta: encerra sem traceback.
                return
            finally:
                audit_log.unsubscribe(queue)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/events/catalog")
    async def events_catalog() -> dict[str, Any]:
        return {
            "kinds": {
                kind: {
                    "description": spec.description,
                    "statuses": list(spec.statuses),
                    "fields": list(spec.fields),
                    "source": spec.source,
                }
                for kind, spec in CATALOG.items()
            },
            "phases": {f"{kind}/{status}": phase for (kind, status), phase in PHASES.items()},
            "labels": PHASE_LABELS,
        }

    @app.get("/api/runs")
    async def runs(limit: int = 30) -> list[dict[str, Any]]:
        return services.audit.runs(max(1, min(limit, 200)))

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str) -> list[dict[str, Any]]:
        events = services.audit.run(run_id)
        if not events:
            raise HTTPException(404, "Execução não encontrada.")
        return events

    @app.get("/api/runs/{run_id}/report.md")
    async def run_report(run_id: str) -> Response:
        events = services.audit.run(run_id)
        if not events:
            raise HTTPException(404, "Execução não encontrada.")
        safe = "".join(c for c in run_id if c.isalnum() or c in "-_.")
        return Response(
            render_run_report(events),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="nickel-{safe}.md"'},
        )

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
