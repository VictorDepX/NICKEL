from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class PendingAction:
    action_id: str
    tool: str


@dataclass
class AgentResponse:
    reply: str
    pending_action: PendingAction | None


@dataclass
class ActionResponse:
    result_text: str


class NickelAPIClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return self._base_url

    def send_message(self, message: str, history: list[dict[str, str]]) -> AgentResponse:
        payload = {"message": message, "history": history}
        data = self._request("POST", "/chat", json=payload)
        return AgentResponse(
            reply=str(data.get("response", "")),
            pending_action=_parse_pending_action(data.get("pending_action")),
        )

    def confirm_action(self, action_id: str) -> ActionResponse:
        data = self._request(
            "POST",
            "/confirm",
            json={"action_id": action_id, "confirmed": True},
        )
        return ActionResponse(result_text=_extract_result_text(data))

    def cancel_action(self, action_id: str) -> ActionResponse:
        data = self._request(
            "POST",
            "/cancel",
            json={"action_id": action_id, "confirmed": True},
        )
        status = str(data.get("status", "cancelled"))
        return ActionResponse(result_text=f"Ação cancelada ({status}).")

    def _request(self, method: str, path: str, json: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        response = requests.request(method, url, json=json, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid response format")
        return data


def _parse_pending_action(payload: Any) -> PendingAction | None:
    if not isinstance(payload, dict):
        return None
    action_id = payload.get("action_id")
    tool = payload.get("tool")
    if not action_id or not tool:
        return None
    return PendingAction(action_id=str(action_id), tool=str(tool))


def _extract_result_text(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        if "message" in data and isinstance(data["message"], str):
            return data["message"]
        keys = ", ".join(sorted(data.keys()))
        return f"Ação confirmada. Resultado: {keys or 'ok'}."
    return "Ação confirmada."
