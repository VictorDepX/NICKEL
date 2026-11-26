"""Provedor Edge TTS: síntese via edge-tts (MP3) + ffmpeg (WAV), sem rede nos testes."""

from __future__ import annotations

import shutil

import pytest

from nickel.config import Settings
from nickel.services import build_services, resolve_tts_provider
from nickel.speech import edge as edge_module
from nickel.speech.edge import EdgeSpeaker
from nickel.speech.tts import TTSError

from conftest import run


class FakeCommunicate:
    calls: list[tuple[str, str, str]] = []

    def __init__(self, text, voice, rate="+0%"):
        FakeCommunicate.calls.append((text, voice, rate))
        self.text = text

    async def stream(self):
        yield {"type": "WordBoundary"}
        yield {"type": "audio", "data": b"ID3fake"}


class Silent(FakeCommunicate):
    async def stream(self):
        yield {"type": "WordBoundary"}


def test_resolve_edge_provider():
    assert resolve_tts_provider(Settings(tts_provider="edge")) == "edge"


def test_build_services_wires_edge(tmp_path):
    services = build_services(Settings(tts_provider="edge", data_dir=tmp_path))
    assert isinstance(services.tts, EdgeSpeaker) and services.tts_provider == "edge"


def test_synthesize_uses_voice_and_rate_and_converts(tmp_path, monkeypatch):
    FakeCommunicate.calls = []
    seen = {}

    async def fake_to_wav(self, mp3, target):
        seen["mp3"] = mp3
        target.write_bytes(b"RIFF....WAVE")

    monkeypatch.setattr(EdgeSpeaker, "_to_wav", fake_to_wav)
    settings = Settings(edge_tts_voice="pt-BR-FranciscaNeural", edge_tts_rate="+10%")
    path = run(EdgeSpeaker(settings, tmp_path, communicate=FakeCommunicate).synthesize("**Oi** https://x.y tudo bem"))
    assert FakeCommunicate.calls == [("Oi tudo bem", "pt-BR-FranciscaNeural", "+10%")]
    assert seen["mp3"] == b"ID3fake" and path.read_bytes().startswith(b"RIFF")


def test_no_audio_is_an_error(tmp_path):
    with pytest.raises(TTSError, match="não devolveu áudio"):
        run(EdgeSpeaker(Settings(), tmp_path, communicate=Silent).synthesize("oi"))


def test_health_reports_missing_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(edge_module.shutil, "which", lambda name: None)
    health = run(EdgeSpeaker(Settings(), tmp_path, communicate=FakeCommunicate).health())
    assert health == {"ok": False, "detail": "ffmpeg ausente"}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_to_wav_rejects_garbage(tmp_path):
    with pytest.raises(TTSError, match="ffmpeg falhou"):
        run(EdgeSpeaker(Settings(), tmp_path)._to_wav(b"not mp3", tmp_path / "x.wav"))
