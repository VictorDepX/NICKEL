from __future__ import annotations

from typing import Any

from cli.api_client import NickelAPIClient
from cli.main import _render_agent_response
from cli.session_store import SessionState


class DummyHTTPResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def test_api_client_parses_conversational_fields(monkeypatch) -> None:
    payload = {
        "status": "needs_connection",
        "response": "Posso consultar seu Gmail quando a conexão estiver pronta.",
        "requires_confirmation": False,
        "service": "Gmail",
        "fallback": "google_auth",
        "google_connection": {
            "authorization_url": "https://example.com/oauth",
            "service": "Gmail",
        },
    }

    monkeypatch.setattr(
        "cli.api_client.requests.request",
        lambda *args, **kwargs: DummyHTTPResponse(payload),
    )

    client = NickelAPIClient("http://localhost:8000")
    response = client.send_message("Leia meus e-mails", [])

    assert response.status == "needs_connection"
    assert response.reply == payload["response"]
    assert response.authorization_url == "https://example.com/oauth"
    assert response.service == "Gmail"
    assert response.requires_confirmation is False
    assert response.fallback == "google_auth"
    assert response.pending_action is None


def test_api_client_parses_pending_confirmation(monkeypatch) -> None:
    payload = {
        "status": "pending_confirmation",
        "response": "Posso enviar esse e-mail.",
        "requires_confirmation": True,
        "pending_action": {"action_id": "act-123", "tool": "email.send"},
    }

    monkeypatch.setattr(
        "cli.api_client.requests.request",
        lambda *args, **kwargs: DummyHTTPResponse(payload),
    )

    client = NickelAPIClient("http://localhost:8000")
    response = client.send_message("Envie este e-mail", [])

    assert response.status == "pending_confirmation"
    assert response.pending_action is not None
    assert response.pending_action.action_id == "act-123"
    assert response.pending_action.tool == "email.send"
    assert response.requires_confirmation is True


def test_render_response_needs_connection(monkeypatch) -> None:
    state = SessionState(pending_action=None, history=[{"role": "user", "content": "Leia meu Gmail"}])
    response = type("Response", (), {
        "reply": "Posso consultar seu Gmail quando a conexão estiver pronta.",
        "status": "needs_connection",
        "authorization_url": "https://example.com/oauth",
        "service": "Gmail",
        "pending_action": None,
    })()

    calls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr("cli.main.print_nickel", lambda message: calls.append(("nickel", (message,))))
    monkeypatch.setattr(
        "cli.main.print_connection_notice",
        lambda message, authorization_url=None: calls.append(("connection", (message, authorization_url))),
    )
    monkeypatch.setattr(
        "cli.main.print_user_action_instruction",
        lambda message: calls.append(("action", (message,))),
    )

    _render_agent_response(response, state)

    assert state.pending_action is None
    assert state.history[-1] == {"role": "assistant", "content": response.reply}
    assert calls[0] == ("nickel", (response.reply,))
    assert calls[1] == (
        "connection",
        (
            "Não consegui acessar seu Gmail agora. Posso te passar o link para conectar a conta.",
            "https://example.com/oauth",
        ),
    )
    assert calls[2] == (
        "action",
        ("Abra o link acima para conectar a conta e depois tente novamente o pedido.",),
    )


def test_render_response_requires_clarification(monkeypatch) -> None:
    state = SessionState(pending_action=None, history=[])
    response = type("Response", (), {
        "reply": "Você quer arquivar ou apagar esse e-mail?",
        "status": "requires_clarification",
        "pending_action": None,
    })()

    calls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr("cli.main.print_nickel", lambda message: calls.append(("nickel", (message,))))
    monkeypatch.setattr(
        "cli.main.print_uncertainty_notice",
        lambda message: calls.append(("uncertainty", (message,))),
    )
    monkeypatch.setattr(
        "cli.main.print_user_action_instruction",
        lambda message: calls.append(("action", (message,))),
    )

    _render_agent_response(response, state)

    assert state.pending_action is None
    assert calls[1] == (
        "uncertainty",
        ("Não tenho certeza suficiente para executar isso sozinho.",),
    )
    assert calls[2] == ("action", (response.reply,))


def test_render_response_pending_confirmation(monkeypatch) -> None:
    pending_action = type("Pending", (), {"action_id": "act-1", "tool": "calendar.create_event"})()
    state = SessionState(pending_action=None, history=[])
    response = type("Response", (), {
        "reply": "Posso criar esse evento.",
        "status": "pending_confirmation",
        "pending_action": pending_action,
    })()

    calls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr("cli.main.print_nickel", lambda message: calls.append(("nickel", (message,))))
    monkeypatch.setattr(
        "cli.main.print_pending",
        lambda tool, action_id: calls.append(("pending", (tool, action_id))),
    )
    monkeypatch.setattr(
        "cli.main.print_user_action_instruction",
        lambda message: calls.append(("action", (message,))),
    )

    _render_agent_response(response, state)

    assert state.pending_action is pending_action
    assert calls[1] == ("pending", ("calendar.create_event", "act-1"))
    assert calls[2] == (
        "action",
        ("Se estiver tudo certo, responda com /confirm ou use /cancel para abortar.",),
    )
