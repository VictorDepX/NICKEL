from __future__ import annotations

from app.chat import handle_chat
from app.config import Settings


def _settings() -> Settings:
    return Settings(
        google_client_id=None,
        google_client_secret=None,
        google_redirect_uri=None,
        google_scopes=(),
        oauth_token_key=None,
        llm_base_url="https://api.groq.com/openai/v1",
        llm_api_key="groq-test-key",
        llm_model="llama-3.1-8b-instant",
        llm_timeout_seconds=30.0,
        llm_max_tokens=512,
        llm_temperature=0.2,
        llm_retry_count=2,
        llm_retry_backoff_ms=250,
        llm_enable_native_tools=False,
        token_store_path=None,
        pending_actions_path=None,
        notes_store_path=None,
        tasks_store_path=None,
        memory_store_path=None,
        audit_store_path=None,
        spotify_access_token=None,
        spotify_device_id=None,
        spotify_base_url=None,
    )


def test_handle_chat_passes_history_to_llm(monkeypatch) -> None:
    captured = {}

    def fake_generate_response(settings, message, forced_tool=None, history=None):
        captured["message"] = message
        captured["forced_tool"] = forced_tool
        captured["history"] = history
        return {"response": "ok", "action": None}

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)

    result = handle_chat(
        _settings(),
        {
            "message": "continua",
            "history": [
                {"role": "assistant", "content": "Resposta anterior"},
                {"role": "user", "content": "Pergunta anterior"},
            ],
        },
    )

    assert result["response"] == "ok"
    assert captured["message"] == "continua"
    assert captured["history"] == [
        {"role": "assistant", "content": "Resposta anterior"},
        {"role": "user", "content": "Pergunta anterior"},
    ]


def test_handle_chat_ignores_invalid_history_entries(monkeypatch) -> None:
    captured = {}

    def fake_generate_response(settings, message, forced_tool=None, history=None):
        captured["history"] = history
        return {"response": "ok", "action": None}

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)

    handle_chat(
        _settings(),
        {
            "message": "oi",
            "history": [
                {"role": "system", "content": "hack"},
                {"role": "assistant", "content": "  "},
                {"role": "assistant", "content": "Olá"},
                "bad",
            ],
        },
    )

    assert captured["history"] == [{"role": "assistant", "content": "Olá"}]


def test_handle_chat_does_not_force_tool_when_low_confidence(monkeypatch) -> None:
    captured = {}

    def fake_generate_response(settings, message, forced_tool=None, history=None):
        captured["forced_tool"] = forced_tool
        return {"response": "ok", "action": None}

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)

    handle_chat(
        _settings(),
        {"message": "quero ver agenda e mandar email"},
    )

    assert captured["forced_tool"] is None


def test_handle_chat_fallbacks_on_high_confidence_mismatch(monkeypatch) -> None:
    captured = {}

    def fake_generate_response(settings, message, forced_tool=None, history=None):
        captured["forced_tool"] = forced_tool
        return {
            "response": "vou enviar",
            "action": {"tool": "email.send", "payload": {}},
        }

    def fake_record_event(tool, status, payload, action_id=None):
        captured["audit"] = {
            "tool": tool,
            "status": status,
            "payload": payload,
            "action_id": action_id,
        }

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr("app.chat.record_event", fake_record_event)

    result = handle_chat(
        _settings(),
        {"message": "pausar música"},
    )

    assert captured["forced_tool"] == "spotify.pause"
    assert result["status"] == "requires_clarification"
    assert result["fallback"] == "tool_mismatch"
    assert captured["audit"]["tool"] == "orchestrator.mismatch"


def test_handle_chat_routes_supported_read_tool(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Li seus e-mails",
            "action": {"tool": "email.read", "payload": {"id": "abc"}},
        }

    def fake_email_read(settings, payload):
        assert payload == {"id": "abc"}
        return {"id": "abc", "subject": "Olá"}

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr("app.chat.email_read", fake_email_read)
    monkeypatch.setattr(
        "app.chat.resolve_tool_readiness",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "tool": "email.read",
            "explanation": "ready",
            "technical_details": "ready",
            "missing_factor": "none",
        },
    )
    monkeypatch.setitem(
        __import__("app.chat", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS,
        "email.read",
        {"handler": fake_email_read, "requires_confirmation": False},
    )

    result = handle_chat(_settings(), {"message": "ler email"})

    assert result == {
        "status": "ok",
        "response": "Li seus e-mails",
        "tool_result": {"id": "abc", "subject": "Olá"},
    }


def test_handle_chat_routes_supported_confirmation_tool(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Posso enviar",
            "action": {"tool": "email.send", "payload": {"to": "a@b.com"}},
        }

    def fake_require_confirmation(tool, payload):
        assert tool == "email.send"
        assert payload == {"to": "a@b.com"}
        return {"action_id": "pending-1", "tool": tool, "payload": payload}

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr("app.chat.require_confirmation", fake_require_confirmation)
    monkeypatch.setattr(
        "app.chat.resolve_tool_readiness",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "tool": "email.send",
            "explanation": "ready",
            "technical_details": "ready",
            "missing_factor": "none",
        },
    )

    result = handle_chat(_settings(), {"message": "enviar email"})

    assert result == {
        "status": "pending_confirmation",
        "response": "Posso enviar",
        "pending_action": {
            "action_id": "pending-1",
            "tool": "email.send",
            "payload": {"to": "a@b.com"},
        },
    }


def test_handle_chat_returns_recovery_when_google_not_connected(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Posso verificar sua agenda depois que a conta estiver conectada.",
            "action": {
                "tool": "calendar.list_events",
                "payload": {"calendar_id": "primary"},
            },
        }

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr(
        "app.chat.resolve_tool_readiness",
        lambda *_args, **_kwargs: {
            "status": "needs_connection",
            "tool": "calendar.list_events",
            "explanation": "Conecte sua conta Google.",
            "technical_details": "Nenhum token OAuth encontrado.",
            "missing_factor": "google_account_connection",
            "authorization_url": "https://example.com/oauth",
            "state": "state-123",
        },
    )

    result = handle_chat(_settings(), {"message": "ver agenda"})

    assert result["status"] == "tool_not_ready"
    assert result["tool_readiness"]["status"] == "needs_connection"
    assert result["tool_readiness"]["authorization_url"] == "https://example.com/oauth"
    assert result["requires_confirmation"] is False


def test_handle_chat_sensitive_tool_only_confirms_when_ready(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Posso enviar assim que você confirmar.",
            "action": {"tool": "email.send", "payload": {"to": "a@b.com"}},
        }

    calls = {"confirm": 0}

    def fake_require_confirmation(tool, payload):
        calls["confirm"] += 1
        return {"action_id": "pending-1", "tool": tool, "payload": payload}

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr("app.chat.require_confirmation", fake_require_confirmation)
    monkeypatch.setattr(
        "app.chat.resolve_tool_readiness",
        lambda *_args, **_kwargs: {
            "status": "needs_connection",
            "tool": "email.send",
            "explanation": "Conecte o Google antes de enviar.",
            "technical_details": "Nenhum token OAuth encontrado.",
            "missing_factor": "google_account_connection",
        },
    )

    blocked = handle_chat(_settings(), {"message": "enviar email"})

    assert blocked["status"] == "tool_not_ready"
    assert calls["confirm"] == 0

    monkeypatch.setattr(
        "app.chat.resolve_tool_readiness",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "tool": "email.send",
            "explanation": "ready",
            "technical_details": "ready",
            "missing_factor": "none",
        },
    )

    ready = handle_chat(_settings(), {"message": "enviar email"})

    assert ready["status"] == "pending_confirmation"
    assert calls["confirm"] == 1


def test_handle_chat_returns_spotify_device_recovery_instead_of_handler_error(
    monkeypatch,
) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Posso pausar quando houver um device disponível.",
            "action": {"tool": "spotify.pause", "payload": {}},
        }

    def fail_pause(*_args, **_kwargs):
        raise AssertionError("spotify handler should not run when readiness is blocked")

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr("app.chat.spotify_pause", fail_pause)
    monkeypatch.setattr(
        "app.chat.resolve_tool_readiness",
        lambda *_args, **_kwargs: {
            "status": "needs_external_activation",
            "tool": "spotify.pause",
            "explanation": "Abra o Spotify em um device ativo.",
            "technical_details": "Nenhum device encontrado.",
            "missing_factor": "spotify_playback_device",
        },
    )

    result = handle_chat(_settings(), {"message": "pausar música"})

    assert result["status"] == "tool_not_ready"
    assert result["tool_readiness"]["missing_factor"] == "spotify_playback_device"


def test_handle_chat_returns_clarification_for_unsupported_tool(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Não consegui",
            "action": {"tool": "invalid.tool", "payload": {}},
        }

    from types import SimpleNamespace

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr(
        "app.chat.decide_tool",
        lambda _message: SimpleNamespace(
            tool="invalid.tool", reason="forced_test", confidence=0.99
        ),
    )
    monkeypatch.setattr("app.chat.is_high_confidence", lambda _decision: True)

    result = handle_chat(_settings(), {"message": "fazer algo"})

    assert result["status"] == "requires_clarification"
    assert result["fallback"] == "unsupported_llm_tool"
    assert result["orchestration"]["llm_tool"] == "invalid.tool"
