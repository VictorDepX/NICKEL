from __future__ import annotations

import base64
from typing import Any

from fastapi import HTTPException
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import Settings
from app.oauth import ensure_google_ready, require_google_connection

GMAIL_READ_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
)

GMAIL_COMPOSE_SCOPES = (
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
)


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


def _google_not_ready_response(settings: Settings, required_scopes: tuple[str, ...]) -> dict[str, Any] | None:
    check = ensure_google_ready(settings, required_scopes)
    if check.status == "ready":
        return None
    return check.to_response()


def search(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    readiness = _google_not_ready_response(settings, GMAIL_READ_SCOPES)
    if readiness is not None:
        return readiness
    credentials = require_google_connection(settings, GMAIL_READ_SCOPES)
    query = payload.get("query", "")
    max_results = payload.get("max_results", 10)
    user_id = payload.get("user_id", "me")

    try:
        service = build("gmail", "v1", credentials=credentials)
        response = (
            service.users()
            .messages()
            .list(userId=user_id, q=query, maxResults=max_results)
            .execute()
        )
    except HttpError as exc:
        raise _handle_http_error(exc, "email_search_failed", "Failed to search emails.") from exc

    return {
        "status": "ok",
        "data": {
            "results": response.get("messages", []),
            "query": query,
        },
    }


def read(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    readiness = _google_not_ready_response(settings, GMAIL_READ_SCOPES)
    if readiness is not None:
        return readiness
    credentials = require_google_connection(settings, GMAIL_READ_SCOPES)
    user_id = payload.get("user_id", "me")
    message_id = payload.get("message_id")
    if not message_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_message_id",
                    "message": "message_id is required.",
                }
            },
        )

    try:
        service = build("gmail", "v1", credentials=credentials)
        message = (
            service.users()
            .messages()
            .get(userId=user_id, id=message_id, format="full")
            .execute()
        )
    except HttpError as exc:
        raise _handle_http_error(exc, "email_read_failed", "Failed to read email.") from exc

    payload_body = message.get("payload", {})
    body = payload_body.get("body", {})
    data = body.get("data")
    decoded_body = None
    if data:
        decoded_body = base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8")

    return {
        "status": "ok",
        "data": {
            "message": message,
            "decoded_body": decoded_body,
        },
    }


def _require_raw_message(payload: dict[str, Any]) -> str:
    raw = payload.get("raw_base64")
    if raw:
        return raw
    if payload.get("raw_text"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "raw_text_not_allowed",
                    "message": "raw_text is not allowed. Provide raw_base64 instead.",
                }
            },
        )
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "missing_raw_message",
                "message": "raw_base64 is required.",
            }
        },
    )


def draft(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    readiness = _google_not_ready_response(settings, GMAIL_COMPOSE_SCOPES)
    if readiness is not None:
        return readiness
    credentials = require_google_connection(settings, GMAIL_COMPOSE_SCOPES)
    user_id = payload.get("user_id", "me")
    raw = _require_raw_message(payload)

    try:
        service = build("gmail", "v1", credentials=credentials)
        draft_response = (
            service.users()
            .drafts()
            .create(userId=user_id, body={"message": {"raw": raw}})
            .execute()
        )
    except HttpError as exc:
        raise _handle_http_error(exc, "email_draft_failed", "Failed to create draft.") from exc

    return {
        "status": "ok",
        "data": {
            "draft": draft_response,
        },
    }


def send(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    readiness = _google_not_ready_response(settings, GMAIL_COMPOSE_SCOPES)
    if readiness is not None:
        return readiness
    credentials = require_google_connection(settings, GMAIL_COMPOSE_SCOPES)
    user_id = payload.get("user_id", "me")
    raw = _require_raw_message(payload)

    try:
        service = build("gmail", "v1", credentials=credentials)
        message_response = (
            service.users()
            .messages()
            .send(userId=user_id, body={"raw": raw})
            .execute()
        )
    except HttpError as exc:
        raise _handle_http_error(exc, "email_send_failed", "Failed to send email.") from exc

    return {
        "status": "ok",
        "data": {
            "message": message_response,
        },
    }
