from __future__ import annotations

import io
import json
import sys
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
    ok = speaker(
        tmp_path, lambda r: httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]}), voicestudio_model="b"
    )
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


class FakeWinsound:
    """`winsound` dublê: registra cada `PlaySound(som, flags)`."""

    SND_FILENAME, SND_ASYNC, SND_NODEFAULT, SND_PURGE = 0x20000, 0x1, 0x2, 0x40

    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.fail = fail

    def PlaySound(self, sound, flags):
        self.calls.append((sound, flags))
        if self.fail is not None and sound is not None:
            raise self.fail


def _windows(monkeypatch, fake=None):
    fake = fake or FakeWinsound()
    monkeypatch.setitem(sys.modules, "winsound", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    return fake


def _record_sleeps(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(playback.asyncio, "sleep", fake_sleep)
    return slept


ASYNC_FLAGS = FakeWinsound.SND_FILENAME | FakeWinsound.SND_ASYNC | FakeWinsound.SND_NODEFAULT


def test_play_wav_on_windows_plays_async_and_waits_the_wav_duration(monkeypatch, tmp_path):
    fake = _windows(monkeypatch)
    slept = _record_sleeps(monkeypatch)
    wav = tmp_path / "a.wav"
    wav.write_bytes(make_wav(frames=11025, rate=22050))  # 0,5 s
    run(playback.play_wav(wav))
    assert fake.calls == [(str(wav), ASYNC_FLAGS)]
    assert len(slept) == 1 and slept[0] == pytest.approx(0.5, abs=0.2) and slept[0] >= 0.5


def test_play_wav_on_windows_reads_duration_of_float_wav(monkeypatch, tmp_path):
    _windows(monkeypatch)
    slept = _record_sleeps(monkeypatch)
    wav = tmp_path / "f.wav"
    wav.write_bytes(make_float_wav(frames=22050, rate=22050))  # 1 s, recusado pelo `wave`
    run(playback.play_wav(wav))
    assert slept[0] == pytest.approx(1.0, abs=0.2) and slept[0] >= 1.0


def test_windows_stop_playback_calls_playsound_none_zero(monkeypatch):
    fake = _windows(monkeypatch)
    playback.stop_playback()
    assert fake.calls == [(None, 0)]


def test_windows_cancel_during_sleep_stops_the_sound(monkeypatch, tmp_path):
    import asyncio

    fake = _windows(monkeypatch)
    wav = tmp_path / "longo.wav"
    wav.write_bytes(make_wav(frames=10000, rate=1000))  # 10 s

    async def scenario():
        task = asyncio.create_task(playback.play_wav(wav))
        await asyncio.sleep(0.05)
        assert fake.calls == [(str(wav), ASYNC_FLAGS)]  # já tocando, esperando a duração
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    assert fake.calls == [(str(wav), ASYNC_FLAGS), (None, 0)]


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


def _blocking_play(monkeypatch):
    import asyncio

    log = []
    gates = {}

    async def fake_play(path):
        name = f"w{len(log)}"
        log.append(name)
        gate = gates.setdefault(name, asyncio.Event())
        await gate.wait()

    monkeypatch.setattr(playback, "play_wav", fake_play)
    monkeypatch.setattr(playback, "stop_playback", lambda: None)
    return log, gates


def _two_speeches(tmp_path, monkeypatch, explicit_stop):
    import asyncio

    log, gates = _blocking_play(monkeypatch)
    inputs = []

    def handler(request):
        inputs.append(json.loads(request.content)["input"])
        return httpx.Response(200, content=make_wav())

    vs = speaker(tmp_path, handler)
    long_a = " ".join(f"Alfa {i} frase longa de teste." for i in range(300))

    async def scenario():
        task_a = asyncio.create_task(vs.speak(long_a))
        while not log:
            await asyncio.sleep(0)
        if explicit_stop:
            vs.stop()
        task_b = asyncio.create_task(vs.speak("Beta curta."))
        await asyncio.sleep(0.05)
        for gate in list(gates.values()) + [None]:
            if gate:
                gate.set()
        for _ in range(5):
            await asyncio.sleep(0.01)
            for gate in gates.values():
                gate.set()
        await asyncio.gather(task_a, task_b)

    run(scenario())
    return log, inputs


@pytest.mark.parametrize("explicit_stop", [False, True])
def test_new_speech_interrupts_previous_one(tmp_path, monkeypatch, explicit_stop):
    log, inputs = _two_speeches(tmp_path, monkeypatch, explicit_stop)
    a_chunks = [i for i in inputs if i.startswith("Alfa")]
    assert len(log) == 2  # A tocou só o primeiro bloco; B tocou
    assert inputs.count("Beta curta.") == 1
    assert len(a_chunks) == 1  # A nem sintetizou os blocos seguintes


def test_stop_playback_terminates_linux_process(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    terminated = []

    class FakeProcess:
        returncode = None

        def terminate(self):
            terminated.append(True)

    monkeypatch.setattr(playback, "_process", FakeProcess())
    playback.stop_playback()
    assert terminated == [True]


def test_playback_failures_become_tts_error(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(playback.shutil, "which", lambda name: None)
    with pytest.raises(TTSError, match="player"):
        run(playback.play_wav(tmp_path / "a.wav"))

    _windows(monkeypatch, FakeWinsound(fail=RuntimeError("falhou")))
    wav = tmp_path / "a.wav"
    wav.write_bytes(make_wav())
    with pytest.raises(TTSError, match="Windows"):
        run(playback.play_wav(wav))
    with pytest.raises(TTSError, match="WAV"):
        run(playback.play_wav(tmp_path / "nao-existe.wav"))


def test_locked_temp_wav_does_not_turn_success_or_cancel_into_error(tmp_path, monkeypatch):
    import asyncio

    original = Path.unlink

    def locked(self, missing_ok=False):
        if self.suffix == ".wav":
            raise PermissionError("arquivo em uso")
        return original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)

    async def quick(path):
        return None

    monkeypatch.setattr(playback, "play_wav", quick)
    vs = speaker(tmp_path, lambda r: httpx.Response(200, content=make_wav()))
    run(vs.speak("oi"))  # sucesso continua sucesso

    async def forever(path):
        await asyncio.Event().wait()

    monkeypatch.setattr(playback, "play_wav", forever)

    async def scenario():
        task = asyncio.create_task(vs.speak("oi"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):  # o cancelamento não vira PermissionError
            await task

    run(scenario())
    playback.discard(tmp_path / "qualquer.wav")  # direto: também engole o OSError


def test_non_wav_response_becomes_tts_error(tmp_path):
    vs = speaker(tmp_path, lambda r: httpx.Response(200, content=b"nao e wav"))
    with pytest.raises(TTSError, match="não é WAV .*RIFF/WAVE"):
        run(vs.synthesize("oi"))


def test_timeout_default_is_900_and_message_hints_the_setting(tmp_path):
    assert Settings().voicestudio_timeout_seconds == 900.0

    def handler(request):
        raise httpx.ReadTimeout("lento", request=request)

    with pytest.raises(TTSError) as info:
        run(speaker(tmp_path, handler).synthesize("oi"))
    assert str(info.value) == (
        "VoiceStudio demorou demais para responder (aumente VOICESTUDIO_TIMEOUT_SECONDS)."
    )


def test_env_example_documents_timeout_and_keeps_url_commented():
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "\nVOICESTUDIO_TIMEOUT_SECONDS=900\n" in text
    assert "3–10 min" in text
    assert "\n# VOICESTUDIO_URL=http://127.0.0.1:3900\n" in text
    assert "\nVOICESTUDIO_URL=" not in text  # preenchida, trocaria o Piper pelo VoiceStudio sem aviso


def test_health_requires_configured_model(tmp_path):
    def models(payload):
        return lambda r: httpx.Response(200, json=payload)

    present = speaker(tmp_path, models({"data": [{"id": "voxcpm2"}]}), voicestudio_model="voxcpm2")
    assert run(present.health()) == {"ok": True, "detail": "1 modelos"}
    bare = speaker(tmp_path, models([{"id": "voxcpm2"}, {"id": "kittentts"}]), voicestudio_model="voxcpm2")
    assert run(bare.health()) == {"ok": True, "detail": "2 modelos"}
    missing = speaker(tmp_path, models({"data": [{"id": "voxcpm2"}]}))  # padrão: omnivoice
    assert run(missing.health()) == {"ok": False, "detail": "modelo omnivoice ausente; disponíveis: voxcpm2"}
    empty = speaker(tmp_path, models({"data": []}))
    assert run(empty.health()) == {"ok": False, "detail": "modelo omnivoice ausente; disponíveis: nenhum"}


@pytest.mark.parametrize("status", [401, 403])
def test_health_maps_auth_errors_to_api_key_hint(tmp_path, status):
    vs = speaker(tmp_path, lambda r: httpx.Response(status, json={"error": {"message": "x"}}))
    assert run(vs.health()) == {"ok": False, "detail": "configure VOICESTUDIO_API_KEY"}


def test_health_marks_connection_failures_offline(tmp_path):
    def down(request):
        raise httpx.ConnectError("recusado", request=request)

    def slow(request):
        raise httpx.ConnectTimeout("lento", request=request)

    for handler in (down, slow):
        result = run(speaker(tmp_path, handler).health())
        assert result["ok"] is False and result["offline"] is True and result["detail"]
    other = run(speaker(tmp_path, lambda r: httpx.Response(500, text="erro")).health())
    assert other == {"ok": False, "detail": "HTTP 500"}


def make_float_wav(frames: int = 100, rate: int = 22050) -> bytes:
    """WAV IEEE-float (formato 3), que o módulo `wave` recusa."""
    import struct

    data = b"\x00\x00\x00\x00" * frames
    fmt = struct.pack("<HHIIHH", 3, 1, rate, rate * 4, 4, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_float_wav_single_chunk_is_accepted(tmp_path):
    with pytest.raises(wave.Error):
        wave.open(io.BytesIO(make_float_wav()), "rb")
    path = run(speaker(tmp_path, lambda r: httpx.Response(200, content=make_float_wav())).synthesize("oi"))
    assert path.read_bytes() == make_float_wav()


def test_float_wav_cannot_be_concatenated(tmp_path):
    text = " ".join(f"Frase número {i} do texto longo." for i in range(300))
    vs = speaker(tmp_path, lambda r: httpx.Response(200, content=make_float_wav()))
    with pytest.raises(TTSError, match="formato WAV não suportado para concatenação: .*3"):
        run(vs.synthesize(text))
    assert list(tmp_path.glob("*.wav")) == []  # o temporário não fica para trás


def test_busy_gpu_429_is_retried_until_free(tmp_path, monkeypatch):
    from nickel.speech import voicestudio
    monkeypatch.setattr(voicestudio, "_BUSY_WAIT_SECONDS", 0)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": {"message": "the local GPU worker pool is saturated"}})
        return httpx.Response(200, content=make_wav())

    path = run(speaker(tmp_path, handler).synthesize("oi"))
    assert len(calls) == 3 and path.read_bytes().startswith(b"RIFF")


def test_busy_gpu_429_gives_up_after_retries(tmp_path, monkeypatch):
    from nickel.speech import voicestudio
    monkeypatch.setattr(voicestudio, "_BUSY_WAIT_SECONDS", 0)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": {"message": "saturated"}})

    with pytest.raises(TTSError, match="429"):
        run(speaker(tmp_path, handler).synthesize("oi"))
    assert len(calls) == voicestudio._BUSY_RETRIES + 1
