from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from app.actions import execute_action
from app.calendar import list_events
from app.config import get_settings
from app.gmail import draft as email_draft
from app.gmail import read as email_read
from app.gmail import search as email_search
from app.oauth import exchange_code, start_oauth
from app.pending_actions import cancel_action, confirm_action, require_confirmation

app = FastAPI(title="Nickel API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/google/start")
def google_oauth_start() -> dict[str, str]:
    session = start_oauth(get_settings())
    return {"authorization_url": session.authorization_url, "state": session.state}


@app.get("/auth/google/callback")
def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> dict[str, str]:
    return exchange_code(get_settings(), code=code, state=state)


@app.post("/tools/calendar/list_events")
def calendar_list_events(payload: dict[str, object]) -> dict[str, object]:
    return list_events(get_settings(), payload)


@app.post("/tools/email/search")
def email_search_messages(payload: dict[str, object]) -> dict[str, object]:
    return email_search(get_settings(), payload)


@app.post("/tools/email/read")
def email_read_message(payload: dict[str, object]) -> dict[str, object]:
    return email_read(get_settings(), payload)


@app.post("/tools/calendar/create_event")
def calendar_create_event(payload: dict[str, object]) -> dict[str, object]:
    return require_confirmation("calendar.create_event", payload)


@app.post("/tools/calendar/modify_event")
def calendar_modify_event(payload: dict[str, object]) -> dict[str, object]:
    return require_confirmation("calendar.modify_event", payload)


@app.post("/tools/email/draft")
def email_draft_message(payload: dict[str, object]) -> dict[str, object]:
    return email_draft(get_settings(), payload)


@app.post("/tools/email/send")
def email_send_message(payload: dict[str, object]) -> dict[str, object]:
    return require_confirmation("email.send", payload)


@app.post("/tools/notes/create")
def notes_create(payload: dict[str, object]) -> dict[str, object]:
    return require_confirmation("notes.create", payload)


@app.post("/tools/tasks/create")
def tasks_create(payload: dict[str, object]) -> dict[str, object]:
    return require_confirmation("tasks.create", payload)


@app.post("/confirm")
def confirm_pending_action(payload: dict[str, object]) -> dict[str, object]:
    action_id = payload.get("action_id")
    confirmed = payload.get("confirmed") is True
    if not action_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_action_id",
                    "message": "action_id is required.",
                }
            },
        )
    action = confirm_action(str(action_id), confirmed)
    return execute_action(get_settings(), action)


@app.post("/cancel")
def cancel_pending_action(payload: dict[str, object]) -> dict[str, object]:
    action_id = payload.get("action_id")
    confirmed = payload.get("confirmed") is True
    if not action_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_action_id",
                    "message": "action_id is required.",
                }
            },
        )
    return cancel_action(str(action_id), confirmed)
