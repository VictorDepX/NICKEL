from __future__ import annotations

import asyncio
import dataclasses

import httpx
from fastapi.testclient import TestClient

from nickel.app import create_app
from nickel.cli import main
from nickel.skills import build_registry
from nickel.services import build_services
from nickel.speech.tts import PiperSpeaker
from nickel.speech.voicestudio import VoiceStudioSpeaker

from conftest import FakeLLM, run


def _build(settings, monkeypatch, **overrides):
    # O módulo piper não precisa existir de verdade: só a checagem de disponibilidade.
    monkeypatch.setattr("nickel.services.module_available", lambda name: True)
    return build_services(dataclasses.replace(settings, **overrides), FakeLLM())


def test_auto_prefers_voicestudio_when_url_set(settings, monkeypatch, tmp_path):
    voice = tmp_path / "voz.onnx"
    services = _build(settings, monkeypatch, voicestudio_url="http://vs.test", tts_voice_path=voice)
    assert isinstance(services.tts, VoiceStudioSpeaker)
    assert services.tts_provider == "voicestudio"


def test_voicestudio_provider_forced_without_url_uses_default_address(settings, monkeypatch):
    services = _build(settings, monkeypatch, tts_provider="voicestudio")
    assert isinstance(services.tts, VoiceStudioSpeaker)


def test_auto_falls_back_to_piper_without_url(settings, monkeypatch, tmp_path):
    services = _build(settings, monkeypatch, tts_voice_path=tmp_path / "voz.onnx")
    assert isinstance(services.tts, PiperSpeaker)
    assert services.tts_provider == "piper"


def test_provider_none_disables_tts(settings, monkeypatch, tmp_path):
    services = _build(
        settings, monkeypatch, tts_provider="none", voicestudio_url="http://vs.test", tts_voice_path=tmp_path / "v.onnx"
    )
    assert services.tts is None
    assert run(services.tts_status()) == {"provider": None, "ok": False, "detail": "voz desligada"}


def _app_with_voicestudio(services, handler):
    settings = dataclasses.replace(services.settings, voicestudio_url="http://vs.test")
    services.settings = settings
    services.tts = VoiceStudioSpeaker(settings, settings.data_dir / "tmp", transport=httpx.MockTransport(handler))
    services.tts_provider = "voicestudio"
    return create_app(services=services, registry=build_registry(), background=False)


def test_state_reports_provider_and_health_cached(services):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": "omnivoice"}]})

    app = _app_with_voicestudio(services, handler)
    with TestClient(app) as client:
        first = client.get("/api/state").json()["voice"]["tts"]
        second = client.get("/api/state").json()["voice"]["tts"]
    assert first == {"provider": "voicestudio", "ok": True, "detail": "1 modelos"}
    assert second == first
    assert calls == ["/v1/models"]


def test_state_health_is_bounded_to_two_seconds(services, monkeypatch):
    class Slow:
        async def health(self):
            await asyncio.sleep(10)

    services.tts, services.tts_provider = Slow(), "voicestudio"
    status = run(services.tts_status(timeout=0.05))
    assert status == {"provider": "voicestudio", "ok": False, "detail": "sem resposta em 0.05 s"}


def test_state_reports_piper_voice_file(services, tmp_path):
    voice = tmp_path / "pt.onnx"
    voice.write_bytes(b"x")
    services.settings = dataclasses.replace(services.settings, tts_voice_path=voice)
    services.tts, services.tts_provider = object(), "piper"
    assert run(services.tts_status()) == {"provider": "piper", "ok": True, "detail": "pt.onnx"}


def _doctor_env(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("NICKEL_DATA_DIR", str(tmp_path))
    for key in ("VOICESTUDIO_URL", "TTS_VOICE_PATH", "TTS_PROVIDER", "VOICE_ENABLED", "WA_VOICE_REPLIES"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)  # sem .env


def _doctor_with_health(monkeypatch, capsys, health) -> str:
    async def fake_health(self):
        return health

    monkeypatch.setattr(VoiceStudioSpeaker, "health", fake_health)
    main(["doctor"])
    return capsys.readouterr().out


def test_doctor_line_for_voicestudio_online_offline_and_detail(monkeypatch, tmp_path, capsys):
    _doctor_env(monkeypatch, tmp_path, VOICESTUDIO_URL="http://vs.test", VOICESTUDIO_VOICE="marina")
    out = _doctor_with_health(monkeypatch, capsys, {"ok": True, "detail": "1 modelos"})
    assert "[ok] VoiceStudio em http://vs.test (voz: marina)" in out
    assert "Piper" not in out

    out = _doctor_with_health(monkeypatch, capsys, {"ok": False, "offline": True, "detail": "sem conexão"})
    assert "[!!] VoiceStudio em http://vs.test — abra o app VoiceStudio" in out

    detail = "modelo omnivoice ausente; disponíveis: voxcpm2"
    out = _doctor_with_health(monkeypatch, capsys, {"ok": False, "detail": detail})
    assert f"[!!] VoiceStudio em http://vs.test — {detail}" in out
    assert "abra o app VoiceStudio" not in out

    out = _doctor_with_health(monkeypatch, capsys, {"ok": False, "detail": "configure VOICESTUDIO_API_KEY"})
    assert "[!!] VoiceStudio em http://vs.test — configure VOICESTUDIO_API_KEY" in out


def test_doctor_checks_tts_even_without_voice_or_whatsapp_voice(monkeypatch, tmp_path, capsys):
    _doctor_env(monkeypatch, tmp_path, VOICESTUDIO_URL="http://vs.test", VOICE_ENABLED="false")
    out = _doctor_with_health(monkeypatch, capsys, {"ok": True, "detail": "1 modelos"})
    assert "[ok] VoiceStudio em http://vs.test" in out  # a GUI fala mesmo sem VOICE_ENABLED


def test_doctor_warns_when_auto_finds_no_voice(monkeypatch, tmp_path, capsys):
    _doctor_env(monkeypatch, tmp_path, VOICE_ENABLED="false")
    main(["doctor"])
    out = capsys.readouterr().out
    assert "[!!] Voz — configure VOICESTUDIO_URL ou TTS_VOICE_PATH" in out


def test_doctor_flags_invalid_tts_provider(monkeypatch, tmp_path, capsys):
    _doctor_env(monkeypatch, tmp_path, TTS_PROVIDER="elevenlabs")
    main(["doctor"])
    out = capsys.readouterr().out
    assert "[!!] TTS_PROVIDER inválido: elevenlabs (use auto|voicestudio|piper|none)" in out


def test_doctor_reports_voice_off_when_provider_none(monkeypatch, tmp_path, capsys):
    _doctor_env(monkeypatch, tmp_path, TTS_PROVIDER="none", VOICESTUDIO_URL="http://vs.test")
    main(["doctor"])
    out = capsys.readouterr().out
    assert "[ok] Voz desligada (TTS_PROVIDER=none)" in out
    assert "VoiceStudio em" not in out


def test_tts_status_default_timeout_tolerates_slow_voicestudio_models_endpoint():
    """O /v1/models do VoiceStudio real levou ~2,4 s no PC; o teto padrão precisa ficar acima disso."""
    import inspect

    from nickel.services import Services

    assert inspect.signature(Services.tts_status).parameters["timeout"].default >= 5.0
