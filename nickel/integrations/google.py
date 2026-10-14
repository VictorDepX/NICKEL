"""Google OAuth + Gmail + Agenda (portado do v1, agora assíncrono via threads)."""

from __future__ import annotations

import asyncio
import base64
import html
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from nickel.config import Settings
from nickel.core.stores import TokenStore

SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
)
TOKEN_NAME = "google"
TOKEN_URI = "https://oauth2.googleapis.com/token"


class NotConnected(RuntimeError):
    def __init__(self, status: dict[str, Any]) -> None:
        super().__init__(status.get("message", "Google não conectado."))
        self.status = status


class GoogleAuth:
    def __init__(self, settings: Settings, tokens: TokenStore) -> None:
        self.settings = settings
        self.tokens = tokens
        self._flows: dict[str, Any] = {}

    # ------------------------------------------------------------ status
    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.google_client_id:
            missing.append("GOOGLE_CLIENT_ID")
        if not self.settings.google_client_secret:
            missing.append("GOOGLE_CLIENT_SECRET")
        if not self.tokens.available:
            missing.append("OAUTH_TOKEN_KEY")
        return missing

    def status(self) -> dict[str, Any]:
        missing = self.missing_config()
        if missing:
            return {"status": "needs_configuration", "missing": missing,
                    "message": f"Configure {', '.join(missing)} no .env."}
        token = self.tokens.get(TOKEN_NAME)
        if not token:
            return {"status": "needs_connection", "connect_url": "/auth/google/start",
                    "message": "Conecte sua conta Google pela UI local (Conexões)."}
        granted = set(token.get("scopes") or [])
        missing_scopes = [scope for scope in SCOPES if scope not in granted]
        if missing_scopes:
            return {"status": "needs_connection", "connect_url": "/auth/google/start",
                    "message": "Reconecte o Google: faltam permissões."}
        return {"status": "ready"}

    # ------------------------------------------------------------ OAuth
    def _flow(self):
        from google_auth_oauthlib.flow import Flow

        config = {
            "web": {
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "redirect_uris": [self.settings.google_redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URI,
            }
        }
        flow = Flow.from_client_config(config, scopes=list(SCOPES))
        flow.redirect_uri = self.settings.google_redirect_uri
        return flow

    def start(self) -> str:
        missing = self.missing_config()
        if missing:
            raise NotConnected(self.status())
        flow = self._flow()
        url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
        # O mesmo objeto Flow precisa trocar o código (guarda o code_verifier do PKCE).
        self._flows[state] = flow
        return url

    def finish(self, code: str, state: str) -> None:
        flow = self._flows.pop(state, None)
        if flow is None:
            raise ValueError("Estado OAuth inválido ou expirado. Recomece a conexão.")
        flow.fetch_token(code=code)
        self._save(flow.credentials)

    def _save(self, credentials) -> None:
        self.tokens.put(
            TOKEN_NAME,
            {
                "access_token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "expiry": credentials.expiry.replace(tzinfo=timezone.utc).isoformat() if credentials.expiry else None,
                "scopes": list(credentials.scopes or SCOPES),
            },
        )

    def credentials(self):
        status = self.status()
        if status["status"] != "ready":
            raise NotConnected(status)
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        token = self.tokens.get(TOKEN_NAME) or {}
        expiry = None
        if token.get("expiry"):
            expiry = datetime.fromisoformat(token["expiry"]).astimezone(timezone.utc).replace(tzinfo=None)
        credentials = Credentials(
            token=token.get("access_token"),
            refresh_token=token.get("refresh_token"),
            token_uri=TOKEN_URI,
            client_id=self.settings.google_client_id,
            client_secret=self.settings.google_client_secret,
            scopes=token.get("scopes"),
            expiry=expiry,
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._save(credentials)
        return credentials

    def service(self, name: str, version: str):
        from googleapiclient.discovery import build

        return build(name, version, credentials=self.credentials(), cache_discovery=False)


def _header(headers: list[dict[str, str]], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def extract_text(payload: dict[str, Any]) -> str:
    """Pega o corpo text/plain (ou text/html sem tags) de uma mensagem do Gmail."""
    plain: list[str] = []
    rich: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_decode(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    if rich:
        text = re.sub(r"<(script|style).*?</\1>", "", "\n".join(rich), flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        return html.unescape(re.sub(r"\n{3,}", "\n\n", text)).strip()
    return ""


def build_mime(to: str, subject: str, body: str) -> str:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


class GmailService:
    def __init__(self, auth: GoogleAuth) -> None:
        self.auth = auth

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._search, query, max_results)

    def _search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        service = self.auth.service("gmail", "v1")
        listing = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        results = []
        for item in listing.get("messages", []):
            message = (
                service.users().messages()
                .get(userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            headers = message.get("payload", {}).get("headers", [])
            results.append(
                {
                    "id": message["id"],
                    "from": _header(headers, "From"),
                    "subject": _header(headers, "Subject"),
                    "date": _header(headers, "Date"),
                    "snippet": html.unescape(message.get("snippet", "")),
                }
            )
        return results

    async def read(self, message_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._read, message_id)

    def _read(self, message_id: str) -> dict[str, Any]:
        service = self.auth.service("gmail", "v1")
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        body = extract_text(payload)
        return {
            "id": message_id,
            "from": _header(headers, "From"),
            "to": _header(headers, "To"),
            "subject": _header(headers, "Subject"),
            "date": _header(headers, "Date"),
            "body": body[:6000],
        }

    async def draft(self, to: str, subject: str, body: str) -> dict[str, Any]:
        raw = build_mime(to, subject, body)
        return await asyncio.to_thread(
            lambda: self.auth.service("gmail", "v1").users().drafts()
            .create(userId="me", body={"message": {"raw": raw}}).execute()
        )

    async def send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        raw = build_mime(to, subject, body)
        return await asyncio.to_thread(
            lambda: self.auth.service("gmail", "v1").users().messages().send(userId="me", body={"raw": raw}).execute()
        )


class CalendarService:
    def __init__(self, auth: GoogleAuth, calendar_id: str, timezone_name: str) -> None:
        self.auth = auth
        self.calendar_id = calendar_id
        self.timezone = timezone_name

    async def list(self, time_min: str, time_max: str | None, max_results: int = 10) -> list[dict[str, Any]]:
        def run() -> list[dict[str, Any]]:
            response = (
                self.auth.service("calendar", "v3").events()
                .list(calendarId=self.calendar_id, timeMin=time_min, timeMax=time_max, maxResults=max_results,
                      singleEvents=True, orderBy="startTime")
                .execute()
            )
            return [
                {
                    "id": item.get("id"),
                    "summary": item.get("summary", "(sem título)"),
                    "start": (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date"),
                    "end": (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date"),
                    "location": item.get("location"),
                }
                for item in response.get("items", [])
            ]

        return await asyncio.to_thread(run)

    def _event_body(
        self,
        *,
        summary: str,
        start: str,
        end: str,
        description: str | None = None,
        location: str | None = None,
        popup_minutes: int | None = None,
        recurrence: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": self.timezone},
            "end": {"dateTime": end, "timeZone": self.timezone},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if popup_minutes is not None:
            body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": popup_minutes}]}
        if recurrence:
            body["recurrence"] = [recurrence]
        return body

    async def create(self, **fields: Any) -> dict[str, Any]:
        body = self._event_body(**fields)
        return await asyncio.to_thread(
            lambda: self.auth.service("calendar", "v3").events().insert(calendarId=self.calendar_id, body=body).execute()
        )

    async def patch(self, event_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {}
        for key in ("summary", "description", "location"):
            if changes.get(key) is not None:
                body[key] = changes[key]
        for key in ("start", "end"):
            if changes.get(key):
                body[key] = {"dateTime": changes[key], "timeZone": self.timezone}
        return await asyncio.to_thread(
            lambda: self.auth.service("calendar", "v3").events()
            .patch(calendarId=self.calendar_id, eventId=event_id, body=body).execute()
        )

    async def delete(self, event_id: str) -> None:
        await asyncio.to_thread(
            lambda: self.auth.service("calendar", "v3").events()
            .delete(calendarId=self.calendar_id, eventId=event_id).execute()
        )
