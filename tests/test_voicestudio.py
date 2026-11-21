from __future__ import annotations

import io
import json
import sys
import types
import wave
from pathlib import Path

import httpx
import pytest

from nickel.config import Settings
from nickel.speech import playback
from nickel.speech.tts import TTSError, split_for_tts
from nickel.speech.voicestudio import VoiceStudioSpeaker

from conftest import run


def make_wav(frames: int = 100, rate: int = 22050, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * channels * frames)
    return buf.getvalue()


def speaker(tmp_path, handler, **overrides):
    settings = Settings(voicestudio_url="http://vs.test", **overrides)
    return VoiceStudioSpeaker(settings, tmp_path, transport=httpx.MockTransport(handler))


def test_split_for_tts_cleans_and_respects_limit_on_sentence_boundaries():
    text = "**Olá** mundo. Veja https://x.com agora!\n\nTudo bem? Sim."
    assert split_for_tts(text) == ["Olá mundo. Veja agora! Tudo bem? Sim."]
    chunks = split_for_tts("Primeira frase aqui. Segunda frase aqui. Terceira frase aqui.", limit=40)
    assert chunks == ["Primeira frase aqui. Segunda frase aqui.", "Terceira frase aqui."]
    assert all(len(c) <= 40 for c in chunks)
    long = split_for_tts("palavra " * 30, limit=50)
    assert all(len(c) <= 50 for c in long)
    assert all(not c.startswith("alavra") and c.endswith("palavra") for c in long)


def test_split_for_tts_empty_after_cleaning_returns_empty_list():
    assert split_for_tts("  **  https://x.com  ") == []
    assert split_for_tts("") == []


def test_synthesize_posts_expected_body(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=make_wav())

    path = run(speaker(tmp_path, handler).synthesize("**Oi** https://a.b tudo bem"))
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/audio/speech"
    assert body["model"] == "omnivoice" and body["voice"] == "default"
    assert body["response_format"] == "wav" and body["input"] == "Oi tudo bem"
    with wave.open(str(path), "rb") as w:
        assert w.getnframes() == 100


def test_authorization_header_only_when_api_key_set(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, content=make_wav())

    run(speaker(tmp_path, handler).synthesize("oi"))
    run(speaker(tmp_path, handler, voicestudio_api_key="segredo").synthesize("oi"))
    assert seen == [None, "Bearer segredo"]


def test_long_text_makes_several_requests_and_concatenates_wav(tmp_path):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["input"])
        return httpx.Response(200, content=make_wav(frames=50))

    text = " ".join(f"Frase número {i} do texto longo." for i in range(300))
    path = run(speaker(tmp_path, handler).synthesize(text))
    assert len(calls) >= 2 and all(len(c) <= 4096 for c in calls)
    with wave.open(str(path), "rb") as w:
        assert w.getnframes() == 50 * len(calls)


def test_mismatched_wav_formats_raise(tmp_path):
    count = iter(range(100))

    def handler(request):
        rate = 22050 if next(count) == 0 else 16000
        return httpx.Response(200, content=make_wav(rate=rate))

    text = " ".join(f"Frase número {i} do texto longo." for i in range(300))
    with pytest.raises(TTSError, match="formatos de áudio diferentes"):
        run(speaker(tmp_path, handler).synthesize(text))


def test_http_error_becomes_tts_error_with_openai_message(tmp_path):
    def handler(request):
        return httpx.Response(
            409, json={"error": {"message": "Voz ambígua: escolha uma.", "code": "ambiguous_voice"}}
        )

    with pytest.raises(TTSError, match="Voz ambígua: escolha uma."):
        run(speaker(tmp_path, handler).synthesize("oi"))


def test_http_error_without_json_uses_raw_text(tmp_path):
    def handler(request):
        return httpx.Response(500, text="x" * 500)

    with pytest.raises(TTSError) as info:
        run(speaker(tmp_path, handler).synthesize("oi"))
    assert "x" * 200 in str(info.value) and "x" * 201 not in str(info.value)


def test_timeout_becomes_tts_error(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("lento", request=request)

    with pytest.raises(TTSError):
        run(speaker(tmp_path, handler).synthesize("oi"))


def test_health_ok_and_offline(tmp_path):
    ok = speaker(tmp_path, lambda r: httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]}))
    assert run(ok.health()) == {"ok": True, "detail": "2 modelos"}

    def down(request):
        raise httpx.ConnectError("recusado", request=request)

    result = run(speaker(tmp_path, down).health())
    assert result["ok"] is False and result["detail"]


def test_speak_empty_text_makes_no_request(tmp_path):
    def handler(request):
        raise AssertionError("não deveria chamar a API")

    run(speaker(tmp_path, handler).speak("  **  "))


def test_speak_plays_and_deletes_temp_wav(tmp_path, monkeypatch):
    played = []

    async def fake_play(path):
        played.append(Path(path))
        assert Path(path).exists()

    monkeypatch.setattr(playback, "play_wav", fake_play)
    run(speaker(tmp_path, lambda r: httpx.Response(200, content=make_wav())).speak("oi"))
    assert len(played) == 1 and not played[0].exists()


def test_play_wav_uses_winsound_on_windows_and_stop_purges(monkeypatch, tmp_path):
    calls = []
    fake = types.SimpleNamespace(
        SND_FILENAME=1, SND_PURGE=2, PlaySound=lambda *a: calls.append(a)
    )
    monkeypatch.setitem(sys.modules, "winsound", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    wav = tmp_path / "a.wav"
    run(playback.play_wav(wav))
    playback.stop_playback()
    assert calls == [(str(wav), 1), (None, 2)]


def test_play_wav_uses_first_available_player_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(playback.shutil, "which", lambda name: name if name == "paplay" else None)
    launched = []

    class FakeProcess:
        returncode = None

        async def wait(self):
            return 0

    async def fake_exec(*args):
        launched.append(args)
        return FakeProcess()

    monkeypatch.setattr(playback.asyncio, "create_subprocess_exec", fake_exec)
    wav = tmp_path / "a.wav"
    run(playback.play_wav(wav))
    assert launched == [("paplay", str(wav))]
