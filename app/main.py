from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from app.actions import execute_action
from app.calendar import list_events
from app.chat import handle_chat
from app.config import get_settings
from app.gmail import draft as email_draft
from app.gmail import read as email_read
from app.gmail import search as email_search
from app.notes import configure_notes_store
from app.oauth import exchange_code, start_oauth
from app.spotify import pause as spotify_pause
from app.spotify import play as spotify_play
from app.spotify import skip as spotify_skip
from app.tasks import configure_tasks_store, list_tasks
from pathlib import Path

from app.pending_actions import (
    cancel_action,
    confirm_action,
    configure_pending_actions,
    require_confirmation,
)

app = FastAPI(title="Nickel API", version="0.1.0")


@app.on_event("startup")
def configure_stores() -> None:
    settings = get_settings()
    pending_path = (
        Path(settings.pending_actions_path) if settings.pending_actions_path else None
    )
    notes_path = Path(settings.notes_store_path) if settings.notes_store_path else None
    tasks_path = Path(settings.tasks_store_path) if settings.tasks_store_path else None
    configure_pending_actions(pending_path)
    configure_notes_store(notes_path)
    configure_tasks_store(tasks_path)
    configure_pending_actions(pending_path)
    configure_notes_store(notes_path)


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


@app.post("/tools/tasks/list")
def tasks_list(payload: dict[str, object]) -> dict[str, object]:
    return list_tasks(get_settings(), payload)


@app.post("/tools/spotify/play")
def spotify_play_track(payload: dict[str, object]) -> dict[str, object]:
    return spotify_play(get_settings(), payload)


@app.post("/tools/spotify/pause")
def spotify_pause_track(payload: dict[str, object]) -> dict[str, object]:
    return spotify_pause(get_settings(), payload)


@app.post("/tools/spotify/skip")
def spotify_skip_track(payload: dict[str, object]) -> dict[str, object]:
    return spotify_skip(get_settings(), payload)


@app.post("/chat")
def chat(payload: dict[str, object]) -> dict[str, object]:
    return handle_chat(get_settings(), payload)


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
