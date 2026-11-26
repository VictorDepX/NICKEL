"""Conectores/pipelines só quando configurados, e memória do sistema para o gráfico do Monitor."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from nickel.app import create_app
from nickel.core.connectors import build_connectors
from nickel.core.sysmon import MemorySampler, read_memory
from nickel.skills import build_registry

SNAPSHOT = {
    "llm": {"ok": True, "model": "gemma", "model_present": True, "detail": "servindo"},
    "whatsapp": {"ready": False, "detail": "bridge offline"},
    "google": {"status": "needs_configuration"},
    "spotify": {"status": "needs_connection"},
    "obsidian": {"available": False},
    "voice": {"available": False, "stt": False, "microphone": False, "tts": {"provider": "edge", "ok": True, "detail": "pt-BR"}},
}


def _ids(items):
    return {i["id"]: i["level"] for i in items}


def test_unconfigured_integrations_are_hidden():
    out = build_connectors(SNAPSHOT, whatsapp=False, music=False, reminders=True, obsidian_path="")
    assert _ids(out["connectors"]) == {"llm": "ok", "tts": "ok", "spotify": "warn"}
    assert _ids(out["pipelines"]) == {"reminders": "ok", "speech": "ok"}
    assert "mcp" not in out


def test_configured_but_offline_is_bad_and_oauth_step_has_action():
    out = build_connectors(SNAPSHOT, whatsapp=True, music=True, reminders=False, obsidian_path="C:/vault")
    levels = _ids(out["connectors"])
    assert levels["whatsapp"] == "bad" and levels["obsidian"] == "bad" and levels["music"] == "ok"
    spotify = next(i for i in out["connectors"] if i["id"] == "spotify")
    assert spotify["action"] == "/auth/spotify/start"
    assert _ids(out["pipelines"])["whatsapp-in"] == "bad"


def test_model_down_is_bad():
    snap = {**SNAPSHOT, "llm": {"ok": False, "model": "gemma", "detail": "sem resposta"}}
    assert _ids(build_connectors(snap, whatsapp=False, music=False, reminders=False, obsidian_path="")["connectors"])["llm"] == "bad"


def test_read_memory_sums_llama_server_rss():
    def proc(name, rss):
        return SimpleNamespace(info={"name": name, "memory_info": SimpleNamespace(rss=rss)})

    fake = SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(total=20, available=5),
        process_iter=lambda attrs: [proc("llama-server.exe", 8), proc("chrome.exe", 3), proc("llama-server", 1)],
        Process=lambda pid: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=2)),
    )
    point = read_memory(fake)
    assert (point["total"], point["used"], point["available"], point["llama"], point["nickel"]) == (20, 15, 5, 9, 2)


def test_sampler_keeps_a_window_and_hides_without_psutil():
    values = iter(range(10))
    sampler = MemorySampler(reader=lambda: {"t": next(values)}, window=3)
    for _ in range(5):
        sampler.sample()
    assert [s["t"] for s in sampler.snapshot()["samples"]] == [2, 3, 4]
    assert MemorySampler(reader=lambda: None).snapshot() == {"available": False, "samples": [], "interval_s": 5.0}


def test_state_and_memory_endpoints(services):
    with TestClient(create_app(services=services, registry=build_registry(), background=False)) as client:
        state = client.get("/api/state").json()
        assert state["connectors"][0]["id"] == "llm" and "pipelines" in state
        memory = client.get("/api/system/memory").json()
        assert memory["available"] is True and memory["samples"][0]["total"] > 0


def test_ui_assets_are_revalidated(services):
    with TestClient(create_app(services=services, registry=build_registry(), background=False)) as client:
        assert client.get("/static/app.js").headers["cache-control"] == "no-cache"
        assert client.get("/").headers["cache-control"] == "no-cache"
        assert "cache-control" not in client.get("/health").headers
