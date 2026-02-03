from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from pathlib import Path

from app import calendar, gmail, oauth, pending_actions
from app.notes import configure_notes_store
from app.memory import configure_memory_store
from app.tasks import configure_tasks_store
from app.config import get_settings
from app.main import app


client = TestClient(app)


@dataclass
class FakeCredentials:
    token: str = "access"
    refresh_token: str = "refresh"
    expiry: datetime | None = datetime(2030, 1, 1, tzinfo=timezone.utc)
    scopes: tuple[str, ...] = ("scope.a",)


class FakeFlow:
    def __init__(self) -> None:
        self.credentials = FakeCredentials()
        self.redirect_uri = ""

    def authorization_url(self, **_kwargs: str) -> tuple[str, str]:
        return ("https://example.com/oauth", "state-123")

    def fetch_token(self, code: str) -> None:
        self.credentials.token = f"access-{code}"


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_oauth_start(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(oauth, "build_flow", lambda _settings: FakeFlow())
    oauth.state_store._states.clear()

    response = client.get("/auth/google/start")
    body = response.json()
    assert response.status_code == 200
    assert body["authorization_url"] == "https://example.com/oauth"
    assert body["state"] == "state-123"


def test_oauth_callback_stores_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(oauth, "build_flow", lambda _settings: FakeFlow())
    oauth.state_store._states.clear()

    start_response = client.get("/auth/google/start")
    state = start_response.json()["state"]
    response = client.get(f"/auth/google/callback?code=xyz&state={state}")
    assert response.status_code == 200
    assert response.json()["status"] == "connected"


class FakeEventsList:
    def __init__(self, events: list[dict[str, str]]) -> None:
        self._events = events

    def execute(self) -> dict[str, list[dict[str, str]]]:
        return {"items": self._events}


class FakeEventsResource:
    def __init__(self, events: list[dict[str, str]]) -> None:
        self._events = events

    def list(self, **_kwargs: object) -> FakeEventsList:
        return FakeEventsList(self._events)

    def insert(self, **_kwargs: object) -> "FakeCalendarWrite":
        return FakeCalendarWrite({"id": "created"})

    def patch(self, **_kwargs: object) -> "FakeCalendarWrite":
        return FakeCalendarWrite({"id": "updated"})


class FakeCalendarService:
    def __init__(self, events: list[dict[str, str]]) -> None:
        self._events = events

    def events(self) -> FakeEventsResource:
        return FakeEventsResource(self._events)


class FakeCalendarWrite:
    def __init__(self, payload: dict[str, str]) -> None:
        self._payload = payload

    def execute(self) -> dict[str, str]:
        return self._payload


def test_calendar_list_events_returns_items(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(calendar, "build", lambda *_args, **_kwargs: FakeCalendarService([{"id": "1"}]))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    response = client.post("/tools/calendar/list_events", json={"calendar_id": "primary"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["data"]["events"] == [{"id": "1"}]


def test_calendar_list_events_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": None,
            "expiry": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    response = client.post("/tools/calendar/list_events", json={"calendar_id": "primary"})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "token_expired"


def test_calendar_create_event_after_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(calendar, "build", lambda *_args, **_kwargs: FakeCalendarService([]))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    pending = client.post(
        "/tools/calendar/create_event",
        json={"calendar_id": "primary", "event": {"summary": "A"}},
    ).json()
    response = client.post("/confirm", json={"action_id": pending["action_id"], "confirmed": True})
    assert response.status_code == 200
    assert response.json()["data"]["event"]["id"] == "created"


def test_calendar_modify_event_after_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(calendar, "build", lambda *_args, **_kwargs: FakeCalendarService([]))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    pending = client.post(
        "/tools/calendar/modify_event",
        json={"calendar_id": "primary", "event_id": "evt1", "event": {"summary": "B"}},
    ).json()
    response = client.post("/confirm", json={"action_id": pending["action_id"], "confirmed": True})
    assert response.status_code == 200
    assert response.json()["data"]["event"]["id"] == "updated"


class FakeGmailMessages:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    def list(self, **_kwargs: object) -> "FakeGmailMessagesList":
        return FakeGmailMessagesList(self._messages)

    def get(self, **_kwargs: object) -> "FakeGmailMessageGet":
        return FakeGmailMessageGet(self._messages[0])

    def send(self, **_kwargs: object) -> "FakeGmailMessageSend":
        return FakeGmailMessageSend({"id": "sent"})


class FakeGmailMessagesList:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    def execute(self) -> dict[str, list[dict[str, str]]]:
        return {"messages": self._messages}


class FakeGmailMessageGet:
    def __init__(self, message: dict[str, str]) -> None:
        self._message = message

    def execute(self) -> dict[str, object]:
        return self._message


class FakeGmailMessageSend:
    def __init__(self, message: dict[str, str]) -> None:
        self._message = message

    def execute(self) -> dict[str, str]:
        return self._message


class FakeGmailDrafts:
    def __init__(self, draft: dict[str, str]) -> None:
        self._draft = draft

    def create(self, **_kwargs: object) -> "FakeGmailDraftCreate":
        return FakeGmailDraftCreate(self._draft)


class FakeGmailDraftCreate:
    def __init__(self, draft: dict[str, str]) -> None:
        self._draft = draft

    def execute(self) -> dict[str, str]:
        return self._draft


class FakeGmailUsers:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    def messages(self) -> FakeGmailMessages:
        return FakeGmailMessages(self._messages)

    def drafts(self) -> FakeGmailDrafts:
        return FakeGmailDrafts({"id": "draft1"})


class FakeGmailService:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    def users(self) -> FakeGmailUsers:
        return FakeGmailUsers(self._messages)


def test_email_search_returns_results(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: FakeGmailService([{"id": "msg1"}]))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    response = client.post("/tools/email/search", json={"query": "from:test"})
    assert response.status_code == 200
    assert response.json()["data"]["results"] == [{"id": "msg1"}]


def test_email_read_requires_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    response = client.post("/tools/email/read", json={})
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "missing_message_id"


def test_email_read_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))

    message = {
        "id": "msg1",
        "payload": {"body": {"data": "aGVsbG8="}},
    }
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: FakeGmailService([message]))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    response = client.post("/tools/email/read", json={"message_id": "msg1"})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["message"]["id"] == "msg1"
    assert body["data"]["decoded_body"] == "hello"


def test_email_draft_requires_raw_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    response = client.post("/tools/email/draft", json={"raw_text": "hi"})
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "raw_text_not_allowed"


def test_email_draft_creates_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: FakeGmailService([{"id": "msg1"}]))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    response = client.post("/tools/email/draft", json={"raw_base64": "aGVsbG8="})
    assert response.status_code == 200
    assert response.json()["data"]["draft"]["id"] == "draft1"


def test_email_send_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: FakeGmailService([{"id": "msg1"}]))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    pending = client.post("/tools/email/send", json={"raw_base64": "aGVsbG8="}).json()
    response = client.post("/confirm", json={"action_id": pending["action_id"], "confirmed": True})
    assert response.status_code == 200
    assert response.json()["data"]["message"]["id"] == "sent"


def test_write_tool_creates_pending_action() -> None:
    response = client.post("/tools/email/send", json={"to": "user@example.com"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "pending_confirmation"
    assert body["tool"] == "email.send"
    assert "action_id" in body


def test_confirm_requires_explicit_true() -> None:
    response = client.post("/tools/calendar/create_event", json={"title": "A"})
    action_id = response.json()["action_id"]
    confirm_response = client.post(
        "/confirm", json={"action_id": action_id, "confirmed": False}
    )
    assert confirm_response.status_code == 400
    assert confirm_response.json()["detail"]["error"]["code"] == "confirmation_required"


def test_cancel_requires_explicit_true() -> None:
    response = client.post("/tools/tasks/create", json={"title": "Task"})
    action_id = response.json()["action_id"]
    cancel_response = client.post("/cancel", json={"action_id": action_id, "confirmed": False})
    assert cancel_response.status_code == 400
    assert cancel_response.json()["detail"]["error"]["code"] == "confirmation_required"


def test_confirm_executes_action_stub() -> None:
    response = client.post("/tools/notes/create", json={"body": "Note"})
    action_id = response.json()["action_id"]
    confirm_response = client.post("/confirm", json={"action_id": action_id, "confirmed": True})
    assert confirm_response.status_code == 200
    assert confirm_response.json()["data"]["note"]["body"] == "Note"


def test_write_tool_does_not_execute_without_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("write tool executed without confirmation")

    monkeypatch.setattr(calendar, "build", _fail)
    response = client.post("/tools/calendar/create_event", json={"calendar_id": "primary"})
    assert response.status_code == 200
    assert response.json()["status"] == "pending_confirmation"


def test_no_pending_action_for_read_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    pending_actions.pending_actions._pending.clear()
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: FakeGmailService([]))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    response = client.post("/tools/email/search", json={"query": "from:test"})
    assert response.status_code == 200
    assert pending_actions.pending_actions._pending == {}


def test_responses_not_emotional_language() -> None:
    response = client.get("/health")
    text = str(response.json()).lower()
    forbidden = ["sorry", "apolog", "regret", "feel", "hope", "happy"]
    assert all(word not in text for word in forbidden)


def test_token_store_persists_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    token_path = tmp_path / "tokens.json"
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("TOKEN_STORE_PATH", str(token_path))

    token_store = oauth.get_token_store(get_settings())
    token_store.store(
        "default",
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expiry": datetime(2030, 1, 1, tzinfo=timezone.utc).isoformat(),
            "scopes": ["scope.a"],
        },
    )

    oauth._token_store = None
    token_store = oauth.get_token_store(get_settings())
    token = token_store.get("default")
    assert token is not None
    assert token["access_token"] == "access"


def test_pending_actions_persist_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "pending.json"
    pending_actions.configure_pending_actions(path)
    pending = pending_actions.require_confirmation("email.send", {"raw_base64": "aGVsbG8="})

    pending_actions.configure_pending_actions(path)
    action = pending_actions.confirm_action(pending["action_id"], True)
    assert action.tool == "email.send"


def test_tasks_create_and_list(tmp_path: Path) -> None:
    configure_tasks_store(tmp_path / "tasks.json")
    pending = client.post("/tools/tasks/create", json={"title": "Task"}).json()
    response = client.post("/confirm", json={"action_id": pending["action_id"], "confirmed": True})
    assert response.status_code == 200
    list_response = client.post("/tools/tasks/list", json={})
    assert list_response.status_code == 200
    tasks = list_response.json()["data"]["tasks"]
    assert tasks and tasks[0]["title"] == "Task"


def test_notes_persist_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    configure_notes_store(path)
    pending = client.post("/tools/notes/create", json={"body": "Note body"}).json()
    response = client.post("/confirm", json={"action_id": pending["action_id"], "confirmed": True})
    assert response.status_code == 200
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data


def test_spotify_requires_token() -> None:
    response = client.post("/tools/spotify/pause", json={})
    assert response.status_code == 500
    assert response.json()["detail"]["error"]["code"] == "spotify_not_configured"


def test_memory_flow(tmp_path: Path) -> None:
    configure_memory_store(tmp_path / "memory.json")
    propose = client.post("/memory/ask", json={"key": "timezone", "value": "America/Sao_Paulo"})
    assert propose.status_code == 200
    memory_id = propose.json()["memory_id"]
    confirm = client.post("/memory/confirm", json={"memory_id": memory_id, "confirmed": True})
    assert confirm.status_code == 200
    listing = client.get("/memory")
    assert listing.status_code == 200
    memories = listing.json()["data"]["memories"]
    assert memories and memories[0]["key"] == "timezone"
