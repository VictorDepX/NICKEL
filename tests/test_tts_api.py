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
        self.active = 0
        self.max_active = 0

    async def speak(self, text: str) -> None:
        self.spoken.append(text)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.fail is not None:
                raise self.fail
            if self.block:
                await asyncio.Event().wait()
        finally:
            self.active -= 1

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
    for needle in ("/api/preferences", "/api/tts/speak", "/api/tts/stop", '"Ouvir"', "nickel:speech", "voice.tts", "Voz desligada"):
        assert needle in app_js, needle
    assert "localStorage.setItem(\"nickel.speak" not in app_js  # a preferência fica no servidor
    monitor = (STATIC_DIR / "monitor.js").read_text(encoding="utf-8")
    assert "nickel:speech" in monitor and "speechSignal(" in monitor


def _statuses(services) -> list[str]:
    return [e["status"] for e in _tts(services)]


def test_concurrent_speaks_play_only_the_last_one(services):
    speaker = _with_speaker(services, FakeSpeaker(block=True))

    async def scenario():
        first = asyncio.create_task(services.speak("A", source="ui"))
        while not speaker.spoken:
            await asyncio.sleep(0)
        # B e C chegam juntos enquanto A ainda está sendo cancelada.
        second = asyncio.create_task(services.speak("B", source="ui"))
        third = asyncio.create_task(services.speak("C", source="ui"))
        while speaker.spoken[-1] != "C":
            await asyncio.sleep(0)
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        services.stop_speaking()
        await asyncio.wait_for(third, 1)

    run(scenario())
    assert speaker.spoken == ["A", "C"]
    assert speaker.max_active == 1
    assert _statuses(services) == ["start", "done", "start", "done"]
    starts = [e["detail"]["chars"] for e in _tts(services) if e["status"] == "start"]
    assert starts == [1, 1]


def test_stop_during_handoff_stops_everything(services):
    speaker = _with_speaker(services, FakeSpeaker(block=True))

    async def scenario():
        first = asyncio.create_task(services.speak("A", source="ui"))
        while not speaker.spoken:
            await asyncio.sleep(0)
        second = asyncio.create_task(services.speak("B", source="ui"))
        await asyncio.sleep(0)  # B já cancelou A e espera ela registrar o fim
        services.stop_speaking()
        await asyncio.wait_for(asyncio.gather(first, second), 1)

    run(scenario())
    assert speaker.spoken == ["A"]
    assert _statuses(services) == ["start", "done"]
    assert services._speech is None or services._speech.done()


def test_speak_returns_error_message_or_none(services):
    _with_speaker(services, FakeSpeaker())
    assert run(services.speak("Oi", source="ui")) is None
    _with_speaker(services, FakeSpeaker(fail=RuntimeError("quebrou")))
    assert run(services.speak("Oi", source="ui")) == "quebrou"
    services.tts = None
    assert run(services.speak("Oi", source="ui")) == "voz indisponível"


def test_voice_session_notifies_when_speech_fails(services, llm):
    llm.queue(say("Vai falhar."))
    voice = _voice(services, llm, stt=FakeSTT(), tts=FakeSpeaker(fail=RuntimeError("VoiceStudio caiu")))
    notes: list[str] = []

    async def notify(body: str) -> None:
        notes.append(body)

    voice._notify = notify
    run(voice._session())
    assert "Erro na voz: VoiceStudio caiu" in notes
    assert voice.state == "idle"


def test_shutdown_stops_speech_before_system_shutdown(services):
    speaker = _with_speaker(services, FakeSpeaker(block=True))
    with _client(services) as client:
        client.post("/api/tts/speak", json={"text": "Fala longa."})
        _wait_for(lambda: speaker.spoken == ["Fala longa."])
    events = list(reversed(services.audit.recent(500)))
    keys = [(e["kind"], e["status"]) for e in events]
    assert keys[-1] == ("system", "shutdown")
    assert ("tts", "done") in keys and keys.index(("tts", "done")) < keys.index(("system", "shutdown"))
    assert speaker.stops >= 2 and speaker.active == 0


def test_chat_does_not_speak_when_voice_is_off(services, llm):
    services.tts = None
    services.state.set("ui.speak", "1")
    llm.queue(say("Só texto."))
    with _client(services) as client:
        assert client.post("/api/chat", json={"text": "oi"}).json()["text"] == "Só texto."
        time.sleep(0.1)
    assert _tts(services) == []


# ------------------------------------------------------------------ Limite de texto


def test_speak_truncates_long_text_at_sentence_boundary(services):
    speaker = _with_speaker(services, FakeSpeaker())
    sentence = "Esta é uma frase de teste com algumas palavras."  # 47 caracteres
    text = " ".join([sentence] * 200)  # ~9600 caracteres
    run(services.speak(text, source="ui"))
    spoken = speaker.spoken[0]
    assert len(spoken) <= 4000 and spoken.endswith("palavras.")
    assert text.startswith(spoken)
    start, done = _tts(services)
    assert start["detail"]["chars"] == len(spoken) == done["detail"]["chars"]


def test_short_text_is_spoken_as_is(services):
    speaker = _with_speaker(services, FakeSpeaker())
    run(services.speak("**Oi** tudo bem?", source="ui"))
    assert speaker.spoken == ["**Oi** tudo bem?"]  # a limpeza fica com o provedor


def test_tts_speak_rejects_text_over_limit_with_413(services):
    speaker = _with_speaker(services, FakeSpeaker())
    with _client(services) as client:
        response = client.post("/api/tts/speak", json={"text": "a" * 4001})
        assert response.status_code == 413
        assert "4000 caracteres" in response.json()["detail"]
        assert client.post("/api/tts/speak", json={"text": "a" * 4000}).status_code == 202
        _wait_for(lambda: len(speaker.spoken) == 1)


# ------------------------------------------------------------------ Nota de voz do WhatsApp


class NoteSpeaker(FakeSpeaker):
    """Speaker cuja síntese (`synthesize`) só termina quando `release` é liberado."""

    def __init__(self, work_dir, *, fail: Exception | None = None, block: bool = True) -> None:
        super().__init__(block=True)
        self.work_dir = work_dir
        self.synth: list[str] = []
        self.synth_fail = fail
        self.synth_block = block
        self.release = asyncio.Event()
        self.started = asyncio.Event()

    async def synthesize(self, text: str):
        self.synth.append(text)
        self.started.set()
        if self.synth_block:
            await self.release.wait()
        if self.synth_fail is not None:
            raise self.synth_fail
        path = self.work_dir / f"nota{len(self.synth)}.wav"
        path.write_bytes(b"RIFF....WAVE")
        return path


def _wa_channel(services, monkeypatch):
    from nickel.channels.whatsapp import WhatsAppChannel
    from nickel.core.agent import Agent

    async def fake_ogg(wav):
        assert wav.exists()
        return b"ogg:" + wav.name.encode()

    monkeypatch.setattr("nickel.speech.tts.wav_to_ogg_opus", fake_ogg)
    services.settings = dataclasses.replace(services.settings, wa_voice_replies=True, music_auto_detect=False)

    class STT:
        async def transcribe(self, path):
            return "me responde em áudio"

    services.stt = STT()
    return WhatsAppChannel(services, Agent(services, build_registry()))


def _audio(message_id: str) -> dict:
    import base64

    return {"id": message_id, "type": "ptt", "mimetype": "audio/ogg", "media_b64": base64.b64encode(b"OggS").decode()}


def test_whatsapp_sends_text_before_voice_note_is_synthesized(services, llm, monkeypatch, tmp_path):
    speaker = _with_speaker(services, NoteSpeaker(tmp_path))
    channel = _wa_channel(services, monkeypatch)
    llm.queue(say("Resposta em texto e voz."))

    async def scenario():
        reply = await asyncio.wait_for(channel.handle_inbound(_audio("v1")), 1)  # não espera a síntese
        assert reply == "Resposta em texto e voz."
        assert services.whatsapp.sent == ["Resposta em texto e voz."]
        await asyncio.wait_for(speaker.started.wait(), 1)
        assert services.whatsapp.voice == []  # síntese ainda presa
        speaker.release.set()
        await asyncio.wait_for(asyncio.gather(*channel.voice_tasks), 1)

    run(scenario())
    assert speaker.synth == ["Resposta em texto e voz."]
    assert services.whatsapp.voice == [b"ogg:nota1.wav"]
    assert not (tmp_path / "nota1.wav").exists()  # o WAV temporário é apagado
    start, done = _tts(services)
    assert start["status"] == "start" and done["status"] == "done"
    assert start["detail"] == {
        "source": "whatsapp", "chars": len("Resposta em texto e voz."), "provider": "voicestudio", "voice": "default",
    }
    assert done["detail"] == {"chars": len("Resposta em texto e voz.")}
    keys = [(e["kind"], e["status"]) for e in reversed(services.audit.recent(500))]
    assert keys.index(("whatsapp", "replied")) < keys.index(("tts", "start"))
    replied = [e for e in reversed(services.audit.recent(500)) if (e["kind"], e["status"]) == ("whatsapp", "replied")]
    assert replied[0]["detail"]["voice"] is True
    for event in _tts(services):
        assert set(event["detail"]) <= set(CATALOG["tts"].fields)


def test_whatsapp_voice_note_failure_is_audited_and_text_still_sent(services, llm, monkeypatch, tmp_path):
    _with_speaker(services, NoteSpeaker(tmp_path, fail=RuntimeError("VoiceStudio caiu"), block=False))
    channel = _wa_channel(services, monkeypatch)
    llm.queue(say("Só o texto chega."))

    async def scenario():
        await asyncio.wait_for(channel.handle_inbound(_audio("v2")), 1)
        await asyncio.wait_for(asyncio.gather(*channel.voice_tasks), 1)

    run(scenario())
    assert services.whatsapp.sent == ["Só o texto chega."] and services.whatsapp.voice == []
    assert _statuses(services) == ["start", "error"]
    assert _tts(services)[-1]["detail"] == {"source": "whatsapp", "detail": "VoiceStudio caiu"}


def test_whatsapp_voice_note_is_skipped_while_gui_speaks(services, llm, monkeypatch, tmp_path):
    speaker = _with_speaker(services, NoteSpeaker(tmp_path))
    channel = _wa_channel(services, monkeypatch)
    llm.queue(say("Agora não dá para falar."))

    async def scenario():
        gui = asyncio.create_task(services.speak("Fala da GUI.", source="ui"))
        while not speaker.spoken:
            await asyncio.sleep(0)
        await asyncio.wait_for(channel.handle_inbound(_audio("v3")), 1)
        await asyncio.wait_for(asyncio.gather(*channel.voice_tasks), 1)
        assert not gui.done()  # a fala da GUI segue
        services.stop_speaking()
        await asyncio.wait_for(gui, 1)

    run(scenario())
    assert services.whatsapp.sent == ["Agora não dá para falar."]
    assert speaker.synth == [] and services.whatsapp.voice == []
    events = _tts(services)
    busy = [e for e in events if e["status"] == "error"]
    assert busy[0]["detail"] == {"source": "whatsapp", "detail": "voz ocupada"}
    assert [e["status"] for e in events] == ["start", "error", "done"]


def test_gui_speech_takes_over_a_pending_voice_note(services, llm, monkeypatch, tmp_path):
    speaker = _with_speaker(services, NoteSpeaker(tmp_path))
    speaker.block = False
    channel = _wa_channel(services, monkeypatch)
    llm.queue(say("Nota que vai ser cortada."))

    async def scenario():
        await asyncio.wait_for(channel.handle_inbound(_audio("v4")), 1)
        await asyncio.wait_for(speaker.started.wait(), 1)
        await asyncio.wait_for(services.speak("GUI.", source="ui"), 1)  # uma fala por vez: a nota cede
        await asyncio.wait_for(asyncio.gather(*channel.voice_tasks), 1)

    run(scenario())
    assert services.whatsapp.voice == []
    assert speaker.spoken == ["GUI."]
    events = _tts(services)
    assert [(e["detail"].get("source"), e["status"]) for e in events] == [
        ("whatsapp", "start"), (None, "done"), ("ui", "start"), (None, "done"),
    ]
    assert events[1]["detail"]["interrupted"] is True
