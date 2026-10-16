"""Clientes de LLM.

O agente produz mensagens num formato neutro:
  - {"role": "system"|"user"|"assistant", "content": str, "images": [base64, ...]?}
  - {"role": "assistant", "content": str, "tool_calls": [{"id", "type": "function",
                                                        "function": {"name", "arguments": dict}}]}
  - {"role": "tool", "tool_call_id": str, "tool_name": str, "content": str}
Cada cliente converte para o formato do seu servidor.

- OllamaClient: `/api/chat` nativo do Ollama (GPU local).
- OpenAICompatClient: `/chat/completions` (vLLM no RunPod Serverless, ou outro provedor compatível).
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from nickel.config import Settings

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_RUNPOD_RE = re.compile(r"^https://api\.runpod\.ai/v2/([^/]+)/openai/v1/?$")
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")


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


def _parse_message(message: dict[str, Any], raw: dict[str, Any]) -> LLMReply:
    content = message.get("content") or ""
    if isinstance(content, list):  # alguns servidores devolvem partes
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    content = _THINK_RE.sub("", content).strip()
    calls: list[ToolCall] = []
    for item in message.get("tool_calls") or []:
        function = item.get("function", item) if isinstance(item, dict) else {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        call = ToolCall(name=name, arguments=_parse_arguments(function.get("arguments")))
        if isinstance(item, dict) and item.get("id"):
            call.id = str(item["id"])
        calls.append(call)
    return LLMReply(content=content, tool_calls=calls, raw=raw)


def parse_reply(data: dict[str, Any]) -> LLMReply:
    """Resposta do Ollama (`{"message": {...}}`)."""
    return _parse_message(data.get("message") or {}, data)


def parse_openai_reply(data: dict[str, Any]) -> LLMReply:
    """Resposta OpenAI (`{"choices": [{"message": {...}}]}`)."""
    choices = data.get("choices") or []
    if not choices:
        raise LLMError(f"Resposta sem choices: {str(data)[:200]}")
    return _parse_message(choices[0].get("message") or {}, data)


def image_mime(b64: str) -> str:
    head = base64.b64decode(b64[:64] + "=" * (-len(b64[:64]) % 4), validate=False)[:12]
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


# --------------------------------------------------------------------------- Ollama
class OllamaClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=settings.llm_timeout_seconds,
            transport=transport,
        )

    @staticmethod
    def convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role == "tool":
                converted.append({"role": "tool", "tool_name": message.get("tool_name", ""), "content": message["content"]})
            elif role == "assistant" and message.get("tool_calls"):
                converted.append(
                    {
                        "role": "assistant",
                        "content": message.get("content") or "",
                        "tool_calls": [
                            {"type": "function", "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                            for c in message["tool_calls"]
                        ],
                    }
                )
            else:
                item = {"role": role, "content": message.get("content") or ""}
                if message.get("images"):
                    item["images"] = message["images"]
                converted.append(item)
        return converted

    def build_payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": self.convert_messages(messages),
            "stream": False,
            "think": self.settings.llm_think,
            "keep_alive": self.settings.llm_keep_alive,
            "options": {
                "num_ctx": self.settings.llm_num_ctx,
                "num_predict": self.settings.llm_max_tokens,
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
            return {"ok": False, "provider": "ollama", "detail": str(exc)}
        present = self.settings.llm_model in models or any(
            (name or "").split(":")[0] == self.settings.llm_model for name in models
        )
        return {"ok": True, "provider": "ollama", "model": self.settings.llm_model, "model_present": present}

    async def aclose(self) -> None:
        await self._client.aclose()


# --------------------------------------------------------------------------- OpenAI-compatível
class OpenAICompatClient:
    """Fala `/chat/completions`. Pensado para o worker vLLM do RunPod Serverless.

    Partidas a frio podem levar minutos: o timeout é longo e erros transitórios
    (timeout, 429, 5xx) são repetidos `llm_retries` vezes.
    """

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_seconds: tuple[float, ...] = (3.0, 10.0, 20.0),
    ) -> None:
        if not settings.llm_api_key:
            raise LLMError("LLM_API_KEY ausente (chave do RunPod ou do provedor).")
        self.settings = settings
        self.base_url = settings.llm_base_url.rstrip("/")
        self.backoff = backoff_seconds
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds, transport=transport, headers=headers)

    @property
    def runpod_endpoint_id(self) -> str | None:
        match = _RUNPOD_RE.match(self.base_url + "/")
        return match.group(1) if match else None

    @staticmethod
    def convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role == "tool":
                converted.append(
                    {"role": "tool", "tool_call_id": message.get("tool_call_id", ""), "content": message["content"]}
                )
            elif role == "assistant" and message.get("tool_calls"):
                converted.append(
                    {
                        "role": "assistant",
                        "content": message.get("content") or None,
                        "tool_calls": [
                            {
                                "id": c.get("id") or f"call_{index}",
                                "type": "function",
                                "function": {
                                    "name": c["function"]["name"],
                                    "arguments": json.dumps(c["function"]["arguments"], ensure_ascii=False),
                                },
                            }
                            for index, c in enumerate(message["tool_calls"])
                        ],
                    }
                )
            elif message.get("images"):
                parts: list[dict[str, Any]] = [{"type": "text", "text": message.get("content") or ""}]
                for image in message["images"]:
                    parts.append(
                        {"type": "image_url", "image_url": {"url": f"data:{image_mime(image)};base64,{image}"}}
                    )
                converted.append({"role": role, "content": parts})
            else:
                converted.append({"role": role, "content": message.get("content") or ""})
        return converted

    def build_payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": self.convert_messages(messages),
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
            "stream": False,
            # Qwen3.x pensa por padrão; vLLM aceita este campo extra no corpo.
            "chat_template_kwargs": {"enable_thinking": self.settings.llm_think},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMReply:
        payload = self.build_payload(messages, tools)
        attempts = max(0, self.settings.llm_retries) + 1
        last_error = "erro desconhecido"
        for attempt in range(attempts):
            try:
                response = await self._client.post(f"{self.base_url}/chat/completions", json=payload)
            except httpx.TimeoutException:
                last_error = f"sem resposta em {self.settings.llm_timeout_seconds:.0f}s (partida a frio longa?)"
            except httpx.HTTPError as exc:
                last_error = f"falha de rede: {exc}"
            else:
                if response.status_code < 400:
                    try:
                        return parse_openai_reply(response.json())
                    except ValueError as exc:
                        raise LLMError("Resposta do provedor não é JSON.") from exc
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code not in _RETRY_STATUS:
                    raise LLMError(last_error)
            if attempt < attempts - 1:
                await asyncio.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        raise LLMError(f"{last_error} após {attempts} tentativa(s)")

    async def health(self) -> dict[str, Any]:
        """Não gera job: no RunPod usa /health do endpoint; noutros provedores, /models."""
        endpoint = self.runpod_endpoint_id
        try:
            if endpoint:
                response = await self._client.get(f"https://api.runpod.ai/v2/{endpoint}/health", timeout=8)
                response.raise_for_status()
                data = response.json()
                workers = data.get("workers") or {}
                jobs = data.get("jobs") or {}
                active = int(workers.get("running", 0) or 0) + int(workers.get("idle", 0) or 0)
                detail = (
                    f"RunPod: {workers.get('running', 0)} em uso, {workers.get('idle', 0)} ocioso(s), "
                    f"{jobs.get('inQueue', 0)} na fila"
                )
                return {
                    "ok": True,
                    "provider": "runpod",
                    "model": self.settings.llm_model,
                    "model_present": True,
                    "warm": active > 0,
                    "detail": detail,
                }
            response = await self._client.get(f"{self.base_url}/models", timeout=8)
            response.raise_for_status()
            models = [item.get("id") for item in response.json().get("data", [])]
            return {
                "ok": True,
                "provider": "openai",
                "model": self.settings.llm_model,
                "model_present": self.settings.llm_model in models,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "provider": "runpod" if endpoint else "openai", "detail": str(exc)}

    async def aclose(self) -> None:
        await self._client.aclose()


def make_llm(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return OllamaClient(settings)
    if provider in {"openai", "runpod", "vllm"}:
        return OpenAICompatClient(settings)
    raise LLMError(f"LLM_PROVIDER desconhecido: {settings.llm_provider} (use ollama ou openai).")
