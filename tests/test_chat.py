from __future__ import annotations

from types import SimpleNamespace

from app.chat import handle_chat, plan_chat, resolve_action_readiness
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
        spotify_client_id=None,
        spotify_client_secret=None,
        spotify_redirect_uri=None,
        spotify_scopes=(),
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


def test_resolve_action_readiness_requires_clarification_for_missing_parameters(
    monkeypatch,
) -> None:
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

    readiness = resolve_action_readiness(
        _settings(),
        "email.read",
        {},
        "ler meu e-mail importante",
        confidence=0.4,
    )

    assert readiness["status"] == "requires_clarification"
    assert readiness["missing_factor"] == "missing_required_parameters"
    assert "message_id" in readiness["technical_details"]


def test_plan_chat_returns_needs_connection_with_authorization_url(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Posso verificar sua agenda depois de reconectar o Google.",
            "action": {
                "tool": "calendar.list_events",
                "payload": {"calendar_id": "primary"},
            },
        }

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr(
        "app.chat.resolve_action_readiness",
        lambda *_args, **_kwargs: {
            "status": "needs_connection",
            "tool": "calendar.list_events",
            "explanation": "Reconecte sua conta Google.",
            "technical_details": "Nenhum token OAuth encontrado.",
            "missing_factor": "google_account_connection",
            "authorization_url": "https://example.com/oauth",
            "state": "state-123",
        },
    )

    result = plan_chat(_settings(), {"message": "ver agenda"})

    assert result["status"] == "needs_connection"
    assert result["authorization_url"] == "https://example.com/oauth"
    assert result["tool_readiness"]["missing_factor"] == "google_account_connection"


def test_handle_chat_executes_when_tool_is_ready(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Li seus e-mails",
            "action": {"tool": "email.read", "payload": {"message_id": "abc"}},
        }

    def fake_email_read(settings, payload):
        assert payload == {"message_id": "abc"}
        return {"id": "abc", "subject": "Olá"}

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr("app.chat.email_read", fake_email_read)
    monkeypatch.setitem(
        __import__("app.chat", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS,
        "email.read",
        {"handler": fake_email_read, "requires_confirmation": False},
    )
    monkeypatch.setattr(
        "app.chat.resolve_action_readiness",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "tool": "email.read",
            "explanation": "ready",
            "technical_details": "ready",
            "missing_factor": "none",
        },
    )
    monkeypatch.setattr(
        "app.chat.check_google_connection",
        lambda _settings, _scopes: __import__(
            "app.oauth", fromlist=["GoogleConnectionCheck"]
        ).GoogleConnectionCheck(status="ready"),
    )

    result = handle_chat(_settings(), {"message": "ler email"})

    assert result == {
        "status": "ok",
        "response": "Li seus e-mails",
        "tool_result": {"id": "abc", "subject": "Olá"},
    }


def test_handle_chat_sensitive_tool_waits_for_confirmation_when_ready(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Posso enviar assim que você confirmar.",
            "action": {"tool": "email.send", "payload": {"raw_base64": "abc"}},
        }

    def fake_require_confirmation(tool, payload):
        assert tool == "email.send"
        assert payload == {"raw_base64": "abc"}
        return {"action_id": "pending-1", "tool": tool, "payload": payload}

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr("app.chat.require_confirmation", fake_require_confirmation)
    monkeypatch.setattr(
        "app.chat.resolve_action_readiness",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "tool": "email.send",
            "explanation": "ready",
            "technical_details": "ready",
            "missing_factor": "none",
        },
    )
    monkeypatch.setattr(
        "app.chat.check_google_connection",
        lambda _settings, _scopes: __import__(
            "app.oauth", fromlist=["GoogleConnectionCheck"]
        ).GoogleConnectionCheck(status="ready"),
    )

    result = handle_chat(_settings(), {"message": "enviar email"})

    assert result == {
        "status": "pending_confirmation",
        "response": "Posso enviar assim que você confirmar.",
        "pending_action": {
            "action_id": "pending-1",
            "tool": "email.send",
            "payload": {"raw_base64": "abc"},
        },
    }


def test_plan_chat_returns_clarification_when_tool_and_confidence_are_weak(monkeypatch) -> None:
    def fake_generate_response(settings, message, forced_tool=None, history=None):
        return {
            "response": "Acho que quer ler um e-mail, mas faltam detalhes.",
            "action": {"tool": "email.read", "payload": {}},
        }

    monkeypatch.setattr("app.chat.generate_response", fake_generate_response)
    monkeypatch.setattr(
        "app.chat.decide_tool",
        lambda _message: SimpleNamespace(
            tool="email.read", reason="teste", confidence=0.9
        ),
    )
    monkeypatch.setattr("app.chat.is_high_confidence", lambda _decision: True)
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

    result = plan_chat(_settings(), {"message": "abre o email"})

    assert result["status"] == "requires_clarification"
    assert result["tool_readiness"]["missing_factor"] == "missing_required_parameters"
    assert result["requires_confirmation"] is False
