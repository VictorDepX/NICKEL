"""Eventos de voz, WhatsApp, outbound e sistema (ciclo de vida e saúde)."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from nickel.app import create_app
from nickel.channels.voice import VoiceController
from nickel.channels.whatsapp import WhatsAppChannel
from nickel.core.agent import Agent, Turn
from nickel.core.trace import run_scope
from nickel.skills import build_registry

from conftest import run, say


def _events(services, kind: str) -> list[dict]:
    return [e for e in reversed(services.audit.recent(500)) if e["kind"] == kind]


class FakeRecorder:
    async def record(self, stop, max_seconds, silence_seconds) -> Path:
        return Path("/tmp/nickel-nao-existe.wav")


class FakeSTT:
    def __init__(self, text: str = "oi nickel", fail: bool = False) -> None:
        self.text, self.fail = text, fail

    async def transcribe(self, path) -> str:
        if self.fail:
            raise RuntimeError("stt quebrou")
        return self.text


class FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        pass


def _voice(services, llm, *, stt=None, tts=None):
    services.recorder = FakeRecorder()
    services.stt = stt or FakeSTT()
    services.tts = tts
    return VoiceController(services, Agent(services, build_registry()))


def _session(voice) -> None:
    run(voice._session())


def test_voice_state_changes_emit_events(services, llm):
    llm.queue(say("Olá!"))
    tts = FakeTTS()
    voice = _voice(services, llm, tts=tts)
    _session(voice)
    events = _events(services, "voice")
    assert [e["status"] for e in events] == ["listening", "transcribing", "thinking", "speaking", "idle"]
    assert next(e for e in events if e["status"] == "thinking")["detail"] == {"chars": len("oi nickel")}
    assert tts.spoken == ["Olá!"]
    # a sessão de voz e o turno do agente compartilham o mesmo run_id
    turn = [e for e in _events(services, "turn") if e["status"] == "start"][0]
    assert {e["run_id"] for e in events} == {turn["run_id"]}
    assert turn["run_id"]


def test_voice_error_emits_error_then_idle(services, llm):
    voice = _voice(services, llm, stt=FakeSTT(fail=True))
    _session(voice)
    statuses = [e["status"] for e in _events(services, "voice")]
    assert statuses[-2:] == ["error", "idle"]
    error = [e for e in _events(services, "voice") if e["status"] == "error"][0]
    assert "stt quebrou" in error["detail"]["detail"]


def test_agent_turn_inside_outer_scope_keeps_outer_run_id(services, llm):
    llm.queue(say("ok"))
    agent = Agent(services, build_registry())

    async def go():
        with run_scope("outer-123"):
            await agent.handle(Turn(channel="ui", text="oi"))

    run(go())
    assert {e["run_id"] for e in _events(services, "turn")} == {"outer-123"}


def test_agent_turn_without_outer_scope_gets_fresh_ids(services, llm):
    llm.queue(say("a"), say("b"))
    agent = Agent(services, build_registry())
    run(agent.handle(Turn(channel="ui", text="um")))
    run(agent.handle(Turn(channel="ui", text="dois")))
    ids = {e["run_id"] for e in _events(services, "turn") if e["status"] == "start"}
    assert len(ids) == 2 and None not in ids


def test_whatsapp_reply_and_error_events(services, llm):
    channel = WhatsAppChannel(services, Agent(services, build_registry()))
    llm.queue(say("Recebido."))
    run(channel.handle_inbound({"id": "w1", "type": "chat", "body": "oi"}))
    received = _events(services, "whatsapp")
    assert [e["status"] for e in received] == ["received", "replied"]
    assert received[1]["detail"] == {"chars": len("Recebido."), "voice": False}
    turn = [e for e in _events(services, "turn") if e["status"] == "start"][0]
    assert {e["run_id"] for e in received} == {turn["run_id"]}

    async def boom(payload):
        raise RuntimeError("falhou geral")

    channel.build_turn = boom
    run(channel.handle_inbound({"id": "w2", "type": "chat", "body": "x"}))
    errors = [e for e in _events(services, "whatsapp") if e["status"] == "error"]
    assert len(errors) == 1 and "falhou geral" in errors[0]["detail"]["detail"]


def test_outbound_event_keeps_existing_shape(services):
    assert run(services.outbound.notify("Beber água", channel="lembrete")) is True
    event = _events(services, "outbound")[-1]
    assert (event["name"], event["status"], event["detail"]) == ("lembrete", "ok", {"text": "Beber água"})
    services.whatsapp.ok = False
    assert run(services.outbound.notify("De novo")) is False
    assert _events(services, "outbound")[-1]["status"] == "undelivered"


def _wait_for(services, status: str, timeout: float = 2.0) -> dict:
    """O `system/health` roda em segundo plano depois do startup: espera ele aparecer."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = [e for e in _events(services, "system") if e["status"] == status]
        if found:
            return found[0]
        time.sleep(0.01)
    raise AssertionError(f"system/{status} não apareceu")


def test_lifespan_emits_startup_and_shutdown(services):
    app = create_app(services=services, registry=build_registry(), background=False)
    with TestClient(app):
        _wait_for(services, "health")
        startup = _events(services, "system")
        assert [e["status"] for e in startup][:1] == ["startup"]
        detail = startup[0]["detail"]
        assert detail["version"] == "2.0.0"
        assert detail["workspace_count"] >= 1
        assert "llm" in detail
    statuses = [e["status"] for e in _events(services, "system")]
    assert statuses == ["startup", "health", "shutdown"]


def test_health_event_contains_service_snapshot_without_secrets(services):
    app = create_app(services=services, registry=build_registry(), background=False)
    with TestClient(app):
        health = _wait_for(services, "health")
    assert set(health["detail"]) == {"llm", "whatsapp", "google", "spotify", "obsidian", "voice"}
    dump = str(health["detail"]).lower()
    for secret in ("segredo", "token_key", services.settings.oauth_token_key.lower()):
        assert secret not in dump
    assert health["detail"]["llm"]["ok"] is True


def test_health_event_is_recorded_even_if_llm_is_slow(services, monkeypatch):
    async def slow():
        await asyncio.sleep(30)

    monkeypatch.setattr("nickel.app.HEALTH_TIMEOUT", 0.05)
    services.llm.health = slow
    app = create_app(services=services, registry=build_registry(), background=False)
    with TestClient(app):
        health = _wait_for(services, "health")
    assert health["detail"]["llm"]["ok"] is False


def test_startup_does_not_wait_for_health(services, monkeypatch):
    async def slow():
        await asyncio.sleep(30)

    monkeypatch.setattr("nickel.app.HEALTH_TIMEOUT", 30.0)
    services.llm.health = slow
    app = create_app(services=services, registry=build_registry(), background=False)
    started = time.monotonic()
    with TestClient(app):
        entered = time.monotonic() - started
        statuses = [e["status"] for e in _events(services, "system")]
    assert entered < 1.0
    assert statuses == ["startup"]
    final = [e["status"] for e in _events(services, "system")]
    assert final == ["startup", "shutdown"]
    assert time.monotonic() - started < 2.0
