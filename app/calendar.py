from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import Settings
from app.oauth import get_credentials


def _handle_http_error(exc: HttpError, code: str, message: str) -> HTTPException:
    status = getattr(exc, "status_code", 500)
    if status in {401, 403}:
        return HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "token_expired",
                    "message": "OAuth token rejected by Google.",
                }
            },
        )
    return HTTPException(
        status_code=502,
        detail={
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


def list_events(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    credentials = get_credentials(settings)
    calendar_id = payload.get("calendar_id", "primary")
    max_results = payload.get("max_results", 10)
    time_min = payload.get("time_min")
    time_max = payload.get("time_max")

    try:
        service = build("calendar", "v3", credentials=credentials)
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                maxResults=max_results,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except HttpError as exc:
        raise _handle_http_error(
            exc, "calendar_list_failed", "Failed to list calendar events."
        ) from exc

    items = events_result.get("items", [])
    return {
        "status": "ok",
        "data": {
            "events": items,
            "calendar_id": calendar_id,
        },
    }


def create_event(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    credentials = get_credentials(settings)
    calendar_id = payload.get("calendar_id")
    event = payload.get("event")
    if not calendar_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_calendar_id",
                    "message": "calendar_id is required.",
                }
            },
        )
    if not event:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_event",
                    "message": "event is required.",
                }
            },
        )

    try:
        service = build("calendar", "v3", credentials=credentials)
        created = (
            service.events()
            .insert(
                calendarId=calendar_id,
                body=event,
            )
            .execute()
        )
    except HttpError as exc:
        raise _handle_http_error(
            exc, "calendar_create_failed", "Failed to create calendar event."
        ) from exc

    return {
        "status": "ok",
        "data": {
            "calendar_id": calendar_id,
            "event": created,
        },
    }


def modify_event(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    credentials = get_credentials(settings)
    calendar_id = payload.get("calendar_id")
    event_id = payload.get("event_id")
    event = payload.get("event")
    if not calendar_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_calendar_id",
                    "message": "calendar_id is required.",
                }
            },
        )
    if not event_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_event_id",
                    "message": "event_id is required.",
                }
            },
        )
    if not event:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_event",
                    "message": "event is required.",
                }
            },
        )

    try:
        service = build("calendar", "v3", credentials=credentials)
        updated = (
            service.events()
            .patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
            )
            .execute()
        )
    except HttpError as exc:
        raise _handle_http_error(
            exc, "calendar_modify_failed", "Failed to modify calendar event."
        ) from exc

    return {
        "status": "ok",
        "data": {
            "calendar_id": calendar_id,
            "event": updated,
        },
    }
