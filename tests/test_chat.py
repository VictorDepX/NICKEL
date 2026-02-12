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
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="ollama",
        llm_model="qwen2.5:7b-instruct",
        llm_timeout_seconds=30.0,
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
