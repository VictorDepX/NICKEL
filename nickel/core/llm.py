"""Cliente do Ollama (`/api/chat`) com tool calling nativo e imagens."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from nickel.config import Settings

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMReply: ...


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw in (None, ""):
        return {}
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Argumentos de tool inválidos: {raw[:200]}") from exc
        if isinstance(decoded, dict):
            return decoded
    raise LLMError(f"Formato de argumentos não suportado: {type(raw).__name__}")


def parse_reply(data: dict[str, Any]) -> LLMReply:
    message = data.get("message") or {}
    content = _THINK_RE.sub("", message.get("content") or "").strip()
    calls: list[ToolCall] = []
    for item in message.get("tool_calls") or []:
        function = item.get("function", item) if isinstance(item, dict) else {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        calls.append(ToolCall(name=name, arguments=_parse_arguments(function.get("arguments"))))
    return LLMReply(content=content, tool_calls=calls, raw=data)


class OllamaClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=settings.llm_timeout_seconds,
            transport=transport,
        )

    def build_payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": False,
            "think": self.settings.llm_think,
            "keep_alive": self.settings.llm_keep_alive,
            "options": {
                "num_ctx": self.settings.llm_num_ctx,
                "temperature": self.settings.llm_temperature,
            },
        }
        if tools:
            payload["tools"] = tools
        return payload

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMReply:
        payload = self.build_payload(messages, tools)
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            raise LLMError(f"Ollama respondeu {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama inacessível em {self.settings.llm_base_url}: {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("Resposta do Ollama não é JSON.") from exc
        return parse_reply(data)

    async def health(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/api/tags", timeout=5)
            response.raise_for_status()
            models = [m.get("name") or m.get("model") for m in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "detail": str(exc)}
        present = self.settings.llm_model in models or any(
            (name or "").split(":")[0] == self.settings.llm_model for name in models
        )
        return {"ok": True, "model": self.settings.llm_model, "model_present": present}

    async def aclose(self) -> None:
        await self._client.aclose()
