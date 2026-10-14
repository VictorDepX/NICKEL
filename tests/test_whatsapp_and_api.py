from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

from nickel.app import create_app
from nickel.channels.whatsapp import WhatsAppChannel
from nickel.core.agent import Agent
from nickel.integrations.google import SCOPES
from nickel.integrations.music import MusicMatch
from nickel.skills import build_registry

from conftest import call, run, say


class FakeSTT:
    def __init__(self, text: str) -> None:
        self.text = text
        self.paths = []

    async def transcribe(self, path):
        self.paths.append(path)
        return self.text


class FakeMusic:
    def __init__(self, match):
        self.match = match

    async def recognize(self, path):
        return self.match


@pytest.fixture
def channel(services):
    return WhatsAppChannel(services, Agent(services, build_registry()))


def test_text_message_roundtrip(services, llm, channel):
    llm.queue(say("Bom dia."))
    reply = run(channel.handle_inbound({"id": "m1", "type": "chat", "body": "bom dia"}))
    assert reply == "Bom dia."
    assert services.whatsapp.sent == ["Bom dia."]
    # mensagem repetida (reentrega da bridge) é ignorada
    assert run(channel.handle_inbound({"id": "m1", "type": "chat", "body": "bom dia"})) is None
    assert len(llm.calls) == 1


def test_image_goes_to_model(services, llm, channel):
    llm.queue(say("Um recibo."))
    image = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    run(channel.handle_inbound({"id": "m2", "type": "image", "caption": "o que é?", "mimetype": "image/jpeg",
                                "media_b64": image}))
    current = llm.calls[0]["messages"][-1]
    assert current["images"] == [image] and current["content"] == "o que é?"
    assert list(services.settings.media_dir.glob("wa-m2*"))


def test_audio_is_transcribed_and_music_annotated(services, llm, channel):
    services.stt = FakeSTT("que música é essa")
    services.music = FakeMusic(MusicMatch("Oceano", "Djavan", spotify_url="https://open.spotify.com/track/1"))
    llm.queue(say("É Oceano, do Djavan: https://open.spotify.com/track/1"))
    audio = base64.b64encode(b"OggS-fake").decode()
    run(channel.handle_inbound({"id": "m3", "type": "ptt", "mimetype": "audio/ogg; codecs=opus", "media_b64": audio}))
    content = llm.calls[0]["messages"][-1]["content"]
    assert content.startswith("[Áudio] que música é essa")
    assert "[Reconhecimento musical: 'Oceano' — Djavan. Spotify: https://open.spotify.com/track/1]" in content
    stored = services.conversations.recent(5)[0]
    assert stored.attachments[0]["type"] == "audio"


def test_unsupported_type_answers_without_model(services, llm, channel):
    reply = run(channel.handle_inbound({"id": "m4", "type": "sticker"}))
    assert "Ainda não processo" in reply and llm.calls == []


def test_confirmation_over_whatsapp(services, llm, channel):
    from nickel.integrations.google import GoogleAuth

    class FakeGmail:
        sent = []

        async def send(self, to, subject, body):
            self.sent.append((to, subject))

    settings = services.settings.with_overrides(google_client_id="id", google_client_secret="s")
    services.google = GoogleAuth(settings, services.tokens)
    services.tokens.put("google", {"access_token": "t", "refresh_token": "r", "expiry": None, "scopes": list(SCOPES)})
    services.gmail = FakeGmail()
    llm.queue(call("email_send", to="ana@x.com", subject="Oi", body="Teste"))
    run(channel.handle_inbound({"id": "c1", "type": "chat", "body": "manda um email pra ana dizendo teste"}))
    assert services.whatsapp.sent[-1].startswith("Confirma: enviar e-mail para ana@x.com")
    run(channel.handle_inbound({"id": "c2", "type": "chat", "body": "sim"}))
    assert FakeGmail.sent == [("ana@x.com", "Oi")]
    assert services.whatsapp.sent[-1] == "E-mail enviado para ana@x.com."


# ---------------------------------------------------------------- API
@pytest.fixture
def client(services):
    app = create_app(services=services, registry=build_registry(), background=False)
    with TestClient(app) as test_client:
        yield test_client


def test_inbound_requires_token(client):
    assert client.post("/channels/whatsapp/inbound", json={}).status_code == 401
    assert client.post("/channels/whatsapp/inbound", json={}, headers={"X-Nickel-Token": "errado"}).status_code == 401


def test_inbound_accepts_and_processes(client, services, llm):
    llm.queue(say("Recebido."))
    response = client.post("/channels/whatsapp/inbound", json={"id": "z1", "type": "chat", "body": "oi"},
                           headers={"X-Nickel-Token": "segredo"})
    assert response.status_code == 202
    for _ in range(50):
        if services.whatsapp.sent:
            break
        time.sleep(0.02)
    assert services.whatsapp.sent == ["Recebido."]


def test_ui_endpoints(client, services, llm):
    assert client.get("/").status_code == 200
    state = client.get("/api/state").json()
    assert state["llm"]["ok"] is True and state["whatsapp"]["ready"] is True
    assert "notes_capture" in state["tools"]

    llm.queue(call("memory_save", key="playlist de foco", value="Lo-fi BR"))
    chat = client.post("/api/chat", json={"text": "lembra que minha playlist de foco é Lo-fi BR"}).json()
    assert chat["pending_action_id"]
    pending = client.get("/api/pending").json()
    assert pending[0]["summary"] == "guardar na memória 'playlist de foco': Lo-fi BR"
    assert client.post(f"/api/pending/{pending[0]['id']}/confirm").json()["text"] == "Guardado: playlist de foco."
    assert client.get("/api/memory").json()[0]["value"] == "Lo-fi BR"
    messages = client.get("/api/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant", "assistant"]
    assert client.get("/api/audit").json()


def test_reminder_endpoints(client, services):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    created = run(services.reminders.create("x", datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(hours=1)))
    assert client.get("/api/reminders").json()[0]["id"] == created["id"]
    assert client.delete(f"/api/reminders/{created['id']}").status_code == 200
    assert client.delete(f"/api/reminders/{created['id']}").status_code == 404


def test_prune_media(tmp_path):
    import os

    from nickel.channels.whatsapp import prune_media

    old, new = tmp_path / "old.ogg", tmp_path / "new.ogg"
    old.write_bytes(b"x"); new.write_bytes(b"y")
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    assert prune_media(tmp_path, 30) == 1
    assert not old.exists() and new.exists()


def test_voice_toggle_unavailable_without_mic(client):
    assert client.post("/voice/toggle").json() == {"state": "unavailable"}
