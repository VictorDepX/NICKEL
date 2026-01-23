from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class PendingAction:
    id: str
    summary: str


@dataclass
class AgentResponse:
    reply: str
    session_id: str
    pending_action: PendingAction | None


@dataclass
class ActionResponse:
    result_text: str
    pending_action: PendingAction | None


class NickelAPIClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return self._base_url

    def send_message(self, message: str, session_id: str | None) -> AgentResponse:
        payload = {"message": message, "session_id": session_id}
        data = self._request("POST", "/agent/text", json=payload)
        return AgentResponse(
            reply=str(data.get("reply", "")),
            session_id=str(data.get("session_id", "")),
            pending_action=_parse_pending_action(data.get("pending_action")),
        )

    def confirm_action(self, action_id: str) -> ActionResponse:
        data = self._request("POST", f"/actions/{action_id}/confirm", json={})
        return ActionResponse(
            result_text=str(data.get("result_text", "")),
            pending_action=_parse_pending_action(data.get("pending_action")),
        )

    def cancel_action(self, action_id: str) -> ActionResponse:
        data = self._request("POST", f"/actions/{action_id}/cancel", json={})
        return ActionResponse(
            result_text=str(data.get("result_text", "")),
            pending_action=_parse_pending_action(data.get("pending_action")),
        )

    def _request(self, method: str, path: str, json: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        response = requests.request(method, url, json=json, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid response format")
        return data


def _parse_pending_action(payload: Any) -> PendingAction | None:
    if not payload:
        return None
    action_id = payload.get("id") if isinstance(payload, dict) else None
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not action_id or not summary:
        return None
    return PendingAction(id=str(action_id), summary=str(summary))
