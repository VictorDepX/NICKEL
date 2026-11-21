"""API de monitoramento: SSE, execuções, relatório, catálogo e `think` no chat."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import nickel.app as app_module
from nickel.app import create_app
from nickel.core.events import CATALOG, PHASE_LABELS, PHASES
from nickel.core.report import render_run_report
from nickel.skills import build_registry

from conftest import run, say


@pytest.fixture
def app(services):
    return create_app(services=services, registry=build_registry(), background=False)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def _parse(body: str) -> list[dict]:
    frames = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        fields = {}
        for line in block.split("\n"):
            key, _, value = line.partition(": ")
            fields[key] = value
        frames.append(fields)
    return frames


def _seed(services, n=3):
    return [services.audit.record("tool", f"t{i}", "ok", {"i": i}, run_id="r1", duration_ms=10 * i)["id"] for i in range(n)]


def test_stream_replays_last_events_then_closes_with_once(client, services):
    ids = _seed(services)
    response = client.get("/api/events/stream?once=true")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    tool_frames = [f for f in _parse(response.text) if f["event"] == "audit" and json.loads(f["data"])["kind"] == "tool"]
    got = [int(f["id"]) for f in tool_frames]
    assert got == ids and got == sorted(got)


def test_stream_respects_after_and_last_event_id(client, services):
    ids = _seed(services, 4)
    frames = _parse(client.get(f"/api/events/stream?once=true&after={ids[1]}").text)
    assert [int(f["id"]) for f in frames] == ids[2:]
    frames = _parse(client.get(f"/api/events/stream?once=true&after={ids[0]}", headers={"Last-Event-ID": str(ids[2])}).text)
    assert [int(f["id"]) for f in frames] == ids[3:]
    frames = _parse(client.get("/api/events/stream?once=true&after=abc", headers={"Last-Event-ID": "xx"}).text)
    assert [int(f["id"]) for f in frames][-4:] == ids


def test_stream_frames_survive_newlines_and_unicode_in_detail(client, services):
    event = services.audit.record("tool", "x", "ok", {"summary": "linha1\nlinha2\r\nação ✓  "}, run_id="r2")
    body = client.get(f"/api/events/stream?once=true&after={event['id'] - 1}").text
    frame = _parse(body)[0]
    assert "\n" not in frame["data"]
    assert json.loads(frame["data"])["detail"]["summary"].startswith("linha1\nlinha2")
    assert "ação ✓" in frame["data"]


def test_stream_unsubscribes_on_client_disconnect(app, services, monkeypatch):
    monkeypatch.setattr(app_module, "SSE_POLL", 0.01)
    endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/events/stream")

    class FakeRequest:
        def __init__(self):
            self.headers = {}
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 3

    async def scenario():
        _seed(services, 2)
        request = FakeRequest()
        response = await endpoint(request, after=None, once=False)
        chunks = [chunk async for chunk in response.body_iterator]
        return chunks

    chunks = run(scenario())
    assert chunks  # reprisa antes de fechar
    assert services.audit.has_subscribers() is False


def test_stream_delivers_live_events_without_duplicates(app, services, monkeypatch):
    monkeypatch.setattr(app_module, "SSE_POLL", 0.01)
    endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/events/stream")

    class FakeRequest:
        headers = {}
        calls = 0

        async def is_disconnected(self):
            FakeRequest.calls += 1
            if FakeRequest.calls == 2:
                services.audit.record("tool", "live", "ok", run_id="r3")
            return FakeRequest.calls > 6

    async def scenario():
        _seed(services, 2)
        response = await endpoint(FakeRequest(), after=None, once=False)
        return [c async for c in response.body_iterator]

    frames = _parse("".join(c if isinstance(c, str) else c.decode() for c in run(scenario())))
    ids = [int(f["id"]) for f in frames if "id" in f]
    assert ids == sorted(set(ids))
    assert any(json.loads(f["data"])["name"] == "live" for f in frames if "data" in f)


def test_runs_list_detail_and_404(client, services):
    _seed(services)
    runs = client.get("/api/runs?limit=5").json()
    assert runs[0]["run_id"] == "r1" and runs[0]["events"] == 3
    detail = client.get("/api/runs/r1").json()
    assert [e["name"] for e in detail] == ["t0", "t1", "t2"]
    assert client.get("/api/runs/nao-existe").status_code == 404
    assert client.get("/api/runs/nao-existe/report.md").status_code == 404


def test_report_markdown_contains_steps_tools_and_errors(client, services):
    a = services.audit
    a.record("turn", "ui", "start", run_id="r9")
    a.record("tool", "notes.search", "ok", {"summary": "3 notas"}, run_id="r9", duration_ms=850)
    a.record("tool", "calendar.list", "error", {"summary": "sem conexão"}, run_id="r9", duration_ms=2400)
    a.record("turn", "ui", "done", run_id="r9", duration_ms=3300)
    response = client.get("/api/runs/r9/report.md")
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="nickel-r9.md"'
    text = response.text
    assert "r9" in text and "| hora | tipo | nome | status | ms |" in text
    assert "## Ferramentas" in text and "notes.search" in text and "850 ms" in text
    assert "2,4 s" in text
    assert "sem raciocínio expandido" in text
    assert "## Erros" in text and "sem conexão" in text


def test_report_shows_reasoning_headline_and_conclusion():
    events = [
        {"id": 1, "at": "2026-11-20T10:00:00+00:00", "kind": "reasoning", "name": "model", "status": "final",
         "detail": {"headline": "Vou buscar notas.", "conclusion": "Respondo com o resumo."},
         "run_id": "r", "duration_ms": None},
    ]
    text = render_run_report(events)
    assert "Vou buscar notas." in text and "Respondo com o resumo." in text
    assert "sem raciocínio expandido" not in text


def test_catalog_endpoint_matches_module(client):
    data = client.get("/api/events/catalog").json()
    assert set(data["kinds"]) == set(CATALOG)
    turn = data["kinds"]["turn"]
    assert turn["statuses"] == list(CATALOG["turn"].statuses)
    assert set(turn) == {"description", "statuses", "fields", "source"}
    assert data["phases"] == {f"{k}/{s}": p for (k, s), p in PHASES.items()}
    assert data["labels"] == PHASE_LABELS


def test_chat_accepts_think_flag(client, llm):
    llm.queue(say("a"), say("b"), say("c"))
    for value in (True, False, None):
        assert client.post("/api/chat", json={"text": "oi", "think": value}).status_code == 200
    assert [(c["options"] or {}).get("think") for c in llm.calls] == [True, False, None]


def test_startup_survives_failing_status_and_still_records_shutdown(services):
    class Broken:
        def status(self):
            raise RuntimeError("quebrou")

    services.google = Broken()
    app = create_app(services=services, registry=build_registry(), background=False)
    with TestClient(app) as test_client:
        assert test_client.get("/api/audit").status_code == 200
    statuses = [e["status"] for e in reversed(services.audit.recent(50)) if e["kind"] == "system"]
    assert "startup" in statuses and statuses[-1] == "shutdown"
