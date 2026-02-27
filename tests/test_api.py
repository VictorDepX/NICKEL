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
from app.audit import configure_audit_store
from app.memory import configure_memory_store
from app.tasks import configure_tasks_store
from app.config import get_settings
import app.main as main_module
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


class SpyCalendarEvents:
    def __init__(self) -> None:
        self.list_kwargs: dict[str, object] | None = None

    def list(self, **kwargs: object) -> FakeEventsList:
        self.list_kwargs = kwargs
        return FakeEventsList([{"id": "evt1"}])


class SpyCalendarService:
    def __init__(self) -> None:
        self.events_resource = SpyCalendarEvents()

    def events(self) -> SpyCalendarEvents:
        return self.events_resource


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


def test_calendar_list_events_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    spy_service = SpyCalendarService()
    monkeypatch.setattr(calendar, "build", lambda *_args, **_kwargs: spy_service)

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

    payload = {
        "calendar_id": "primary",
        "max_results": 5,
        "time_min": "2024-01-01T00:00:00Z",
        "time_max": "2024-01-31T23:59:59Z",
    }
    response = client.post("/tools/calendar/list_events", json=payload)
    assert response.status_code == 200
    assert spy_service.events_resource.list_kwargs == {
        "calendarId": "primary",
        "maxResults": 5,
        "timeMin": "2024-01-01T00:00:00Z",
        "timeMax": "2024-01-31T23:59:59Z",
        "singleEvents": True,
        "orderBy": "startTime",
    }


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


class SpyGmailMessages:
    def __init__(self) -> None:
        self.list_kwargs: dict[str, object] | None = None

    def list(self, **kwargs: object) -> FakeGmailMessagesList:
        self.list_kwargs = kwargs
        return FakeGmailMessagesList([{"id": "msg1"}])


class SpyGmailUsers:
    def __init__(self) -> None:
        self.messages_resource = SpyGmailMessages()

    def messages(self) -> SpyGmailMessages:
        return self.messages_resource


class SpyGmailService:
    def __init__(self) -> None:
        self.users_resource = SpyGmailUsers()

    def users(self) -> SpyGmailUsers:
        return self.users_resource


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


def test_email_search_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth._token_store = None
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("OAUTH_TOKEN_KEY", Fernet.generate_key().decode("utf-8"))
    spy_service = SpyGmailService()
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: spy_service)

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

    response = client.post(
        "/tools/email/search",
        json={"query": "subject:report", "max_results": 3, "user_id": "me"},
    )
    assert response.status_code == 200
    assert spy_service.users_resource.messages_resource.list_kwargs == {
        "userId": "me",
        "q": "subject:report",
        "maxResults": 3,
    }


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


def test_configure_stores_configures_each_store_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, int] = {
        "pending": 0,
        "notes": 0,
        "tasks": 0,
        "memory": 0,
        "audit": 0,
    }

    monkeypatch.setattr(main_module, "configure_pending_actions", lambda _path: calls.__setitem__("pending", calls["pending"] + 1))
    monkeypatch.setattr(main_module, "configure_notes_store", lambda _path: calls.__setitem__("notes", calls["notes"] + 1))
    monkeypatch.setattr(main_module, "configure_tasks_store", lambda _path: calls.__setitem__("tasks", calls["tasks"] + 1))
    monkeypatch.setattr(main_module, "configure_memory_store", lambda _path: calls.__setitem__("memory", calls["memory"] + 1))
    monkeypatch.setattr(main_module, "configure_audit_store", lambda _path: calls.__setitem__("audit", calls["audit"] + 1))

    main_module.configure_stores()
    assert calls == {"pending": 1, "notes": 1, "tasks": 1, "memory": 1, "audit": 1}


def test_routes_call_underlying_handlers_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"tasks": 0, "play": 0, "pause": 0, "skip": 0, "audit": 0}

    def fake_list_tasks(_settings: object, _payload: dict[str, object]) -> dict[str, object]:
        calls["tasks"] += 1
        return {"status": "ok", "data": {"tasks": []}}

    def fake_spotify_play(_settings: object, _payload: dict[str, object]) -> dict[str, object]:
        calls["play"] += 1
        return {"status": "ok", "data": {}}

    def fake_spotify_pause(_settings: object, _payload: dict[str, object]) -> dict[str, object]:
        calls["pause"] += 1
        return {"status": "ok", "data": {}}

    def fake_spotify_skip(_settings: object, _payload: dict[str, object]) -> dict[str, object]:
        calls["skip"] += 1
        return {"status": "ok", "data": {}}

    def fake_list_audit_events(_filters: dict[str, object]) -> dict[str, object]:
        calls["audit"] += 1
        return {"status": "ok", "data": {"events": []}}

    monkeypatch.setattr(main_module, "list_tasks", fake_list_tasks)
    monkeypatch.setattr(main_module, "spotify_play", fake_spotify_play)
    monkeypatch.setattr(main_module, "spotify_pause", fake_spotify_pause)
    monkeypatch.setattr(main_module, "spotify_skip", fake_spotify_skip)
    monkeypatch.setattr(main_module, "list_audit_events", fake_list_audit_events)

    assert client.post("/tools/tasks/list", json={}).status_code == 200
    assert client.post("/tools/spotify/play", json={}).status_code == 200
    assert client.post("/tools/spotify/pause", json={}).status_code == 200
    assert client.post("/tools/spotify/skip", json={}).status_code == 200
    assert client.get("/audit").status_code == 200

    assert calls == {"tasks": 1, "play": 1, "pause": 1, "skip": 1, "audit": 1}


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


def test_spotify_pause_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        timeout: int | float | None = None,
    ) -> FakeResponse:
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "token")
    monkeypatch.setenv("SPOTIFY_BASE_URL", "https://spotify.local")
    monkeypatch.setenv("SPOTIFY_DEVICE_ID", "device123")
    monkeypatch.setattr("app.spotify.httpx.request", fake_request)

    response = client.post("/tools/spotify/pause", json={})
    assert response.status_code == 200
    assert calls
    first_call = calls[0]
    assert first_call["method"] == "PUT"
    assert first_call["url"] == "https://spotify.local/me/player/pause"
    assert first_call["headers"] == {"Authorization": "Bearer token"}
    assert first_call["params"] == {"device_id": "device123"}
    assert first_call["json"] is None


def test_spotify_pause_discovers_phone_device(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object] | None = None) -> None:
            self._payload = payload or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        timeout: int | float | None = None,
    ) -> FakeResponse:
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
        if url.endswith("/me/player/devices"):
            return FakeResponse(
                {
                    "devices": [
                        {"id": "phone123", "is_active": True, "type": "Smartphone"}
                    ]
                }
            )
        return FakeResponse()

    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "token")
    monkeypatch.setenv("SPOTIFY_BASE_URL", "https://spotify.local")
    monkeypatch.setattr("app.spotify.httpx.request", fake_request)

    response = client.post("/tools/spotify/pause", json={})
    assert response.status_code == 200
    assert len(calls) >= 2
    assert calls[0]["url"] == "https://spotify.local/me/player/devices"
    assert calls[1]["url"] == "https://spotify.local/me/player/pause"
    assert calls[1]["params"] == {"device_id": "phone123"}


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


def test_audit_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_audit_store(tmp_path / "audit.json")
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
    listing = client.get("/audit")
    assert listing.status_code == 200
    events = listing.json()["data"]["events"]
    assert events and events[-1]["tool"] == "email.search"
