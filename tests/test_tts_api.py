"""Fala pela GUI: `Services.speak`, eventos `tts/*`, rotas de voz e preferências."""
from __future__ import annotations

import asyncio
import dataclasses
import re
import time

from fastapi.testclient import TestClient

from nickel.app import STATIC_DIR, create_app
from nickel.core.events import CATALOG, PHASES
from nickel.skills import build_registry
from test_system_events import FakeSTT, _voice

from conftest import run, say


class FakeSpeaker:
    """Registra `speak`/`stop`. Com `block`, a fala só termina quando é cancelada."""

    def __init__(self, *, fail: Exception | None = None, block: bool = False) -> None:
        self.spoken: list[str] = []
        self.stops = 0
        self.fail = fail
        self.block = block

    async def speak(self, text: str) -> None:
        self.spoken.append(text)
        if self.fail is not None:
            raise self.fail
        if self.block:
            await asyncio.Event().wait()

    def stop(self) -> None:
        self.stops += 1


def _tts(services) -> list[dict]:
    return [e for e in reversed(services.audit.recent(500)) if e["kind"] == "tts"]


def _with_speaker(services, speaker, provider="voicestudio"):
    services.tts = speaker
    services.tts_provider = provider
    return speaker


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condição não atingida a tempo")


def _client(services) -> TestClient:
    return TestClient(create_app(services=services, registry=build_registry(), background=False))


def test_speak_emits_start_done_with_duration(services):
    speaker = _with_speaker(services, FakeSpeaker())
    services.settings = dataclasses.replace(services.settings, voicestudio_voice="ana")
    run(services.speak("Olá, tudo bem?", source="ui"))
    assert speaker.spoken == ["Olá, tudo bem?"]
    assert speaker.stops >= 1  # cancela a fala em curso antes de começar
    start, done = _tts(services)
    assert (start["status"], done["status"]) == ("start", "done")
    assert start["detail"] == {"source": "ui", "chars": 14, "provider": "voicestudio", "voice": "ana"}
    assert done["detail"] == {"chars": 14}
    assert isinstance(done["duration_ms"], int) and done["duration_ms"] >= 0


def test_speak_swallows_errors_and_emits_tts_error(services):
    _with_speaker(services, FakeSpeaker(fail=RuntimeError("VoiceStudio fora do ar")))
    run(services.speak("Oi", source="voice"))  # não levanta
    statuses = [e["status"] for e in _tts(services)]
    assert statuses == ["start", "error"]
    error = _tts(services)[-1]
    assert error["detail"] == {"source": "voice", "detail": "VoiceStudio fora do ar"}


def test_speak_without_tts_emits_error_event(services):
    services.tts = None
    run(services.speak("Oi", source="ui"))
    events = _tts(services)
    assert [e["status"] for e in events] == ["error"]
    assert events[0]["detail"] == {"source": "ui", "detail": "voz indisponível"}


def test_second_speak_stops_the_first(services):
    speaker = _with_speaker(services, FakeSpeaker(block=True))

    async def scenario():
        first = asyncio.create_task(services.speak("primeira", source="ui"))
        while not speaker.spoken:
            await asyncio.sleep(0)
        stops_before = speaker.stops
        speaker.block = False
        await services.speak("segunda", source="ui")
        await asyncio.wait_for(first, 1)
        return stops_before

    stops_before = run(scenario())
    assert speaker.spoken == ["primeira", "segunda"]
    assert speaker.stops > stops_before
    events = _tts(services)
    # A primeira registra o fim (interrompida) antes de a segunda começar: a fase não volta a "Ocioso" no meio.
    assert [e["status"] for e in events] == ["start", "done", "start", "done"]
    assert events[1]["detail"] == {"chars": len("primeira"), "interrupted": True}
    assert events[3]["detail"] == {"chars": len("segunda")}


def test_chat_with_speak_true_triggers_speech_without_blocking_reply(services, llm):
    speaker = _with_speaker(services, FakeSpeaker(block=True))
    llm.queue(say("Resposta falada."))
    with _client(services) as client:
        response = client.post("/api/chat", json={"text": "oi", "speak": True})
        assert response.status_code == 200
        assert response.json()["text"] == "Resposta falada."
        _wait_for(lambda: speaker.spoken == ["Resposta falada."])
        start = _tts(services)[0]
        assert start["status"] == "start" and start["detail"]["source"] == "ui"
        assert client.post("/api/tts/stop").json() == {"stopped": True}
        _wait_for(lambda: [e["status"] for e in _tts(services)] == ["start", "done"])


def test_preferences_roundtrip_persist_in_state(services):
    with _client(services) as client:
        assert client.get("/api/preferences").json() == {"speak": False}
        assert client.post("/api/preferences", json={"speak": True}).json() == {"speak": True}
        assert services.state.get("ui.speak") == "1"
        assert client.get("/api/preferences").json() == {"speak": True}
        assert client.post("/api/preferences", json={"speak": "sim"}).status_code == 400
        assert client.post("/api/preferences", json={"speak": False}).json() == {"speak": False}
        assert services.state.get("ui.speak") == "0"


def test_chat_uses_stored_preference_when_flag_absent(services, llm):
    speaker = _with_speaker(services, FakeSpeaker())
    llm.queue(say("Sem voz."), say("Com voz."), say("Calado."))
    with _client(services) as client:
        client.post("/api/chat", json={"text": "um"})
        services.state.set("ui.speak", "1")
        client.post("/api/chat", json={"text": "dois", "speak": None})
        _wait_for(lambda: speaker.spoken == ["Com voz."])
        client.post("/api/chat", json={"text": "três", "speak": False})  # a flag sobrescreve a preferência
        time.sleep(0.1)  # tempo para uma fala (indevida) em segundo plano aparecer
    assert len(_tts(services)) == 2
    assert speaker.spoken == ["Com voz."]


def test_tts_speak_and_stop_endpoints(services):
    speaker = _with_speaker(services, FakeSpeaker(block=True))
    with _client(services) as client:
        empty = client.post("/api/tts/speak", json={"text": "   "})
        assert empty.status_code == 400 and "vazio" in empty.json()["detail"].lower()
        response = client.post("/api/tts/speak", json={"text": "Ouvir isto."})
        assert response.status_code == 202 and response.json() == {"accepted": True}
        _wait_for(lambda: speaker.spoken == ["Ouvir isto."])
        stops = speaker.stops
        assert client.post("/api/tts/stop").json() == {"stopped": True}
        assert speaker.stops > stops
        _wait_for(lambda: [e["status"] for e in _tts(services)] == ["start", "done"])
    assert _tts(services)[-1]["detail"]["interrupted"] is True


def test_voice_controller_speaks_through_services_speak(services, llm):
    calls: list[tuple[str, str]] = []

    async def fake_speak(text: str, *, source: str) -> None:
        calls.append((text, source))

    llm.queue(say("Olá pela voz."))
    voice = _voice(services, llm, stt=FakeSTT(), tts=FakeSpeaker())
    services.speak = fake_speak
    run(voice._session())
    assert calls == [("Olá pela voz.", "voice")]
    assert voice.services.tts.spoken == []  # nada chama o speaker por fora de services.speak


def test_catalog_has_tts_and_phase_mapping():
    spec = CATALOG["tts"]
    assert spec.statuses == ("start", "done", "error")
    assert {"source", "chars", "provider", "voice", "detail"} <= set(spec.fields)
    assert PHASES[("tts", "start")] == "speaking"
    assert PHASES[("tts", "done")] == "idle"
    assert PHASES[("tts", "error")] == "error"


def test_ui_has_speak_toggle_listen_and_stop_buttons():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<header class="topbar">.*id="speak".*Falar respostas.*</header>', html, re.S)
    assert re.search(r'id="stop-speech"[^>]*hidden', html)
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for needle in ("/api/preferences", "/api/tts/speak", "/api/tts/stop", '"Ouvir"', "nickel:phase", '"speaking"'):
        assert needle in app_js, needle
    assert "localStorage.setItem(\"nickel.speak" not in app_js  # a preferência fica no servidor
    monitor = (STATIC_DIR / "monitor.js").read_text(encoding="utf-8")
    assert "nickel:phase" in monitor
