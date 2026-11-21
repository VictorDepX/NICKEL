"""Clientes de LLM.

O agente produz mensagens num formato neutro:
  - {"role": "system"|"user"|"assistant", "content": str, "images": [base64, ...]?}
  - {"role": "assistant", "content": str, "tool_calls": [{"id", "type": "function",
                                                        "function": {"name", "arguments": dict}}]}
  - {"role": "tool", "tool_call_id": str, "tool_name": str, "content": str}
Cada cliente converte para o formato do seu servidor.

- OllamaClient: `/api/chat` nativo do Ollama (GPU local).
- OpenAICompatClient: `/chat/completions` (vLLM no RunPod Serverless, `llama-server` do llama.cpp
  ou outro provedor compatível).

`chat(..., options=...)` aceita sobrescritas por chamada (workspaces): think, temperature, max_tokens.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import httpx

from nickel.config import Settings

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_RUNPOD_RE = re.compile(r"^https://api\.runpod\.ai/v2/([^/]+)/openai/v1/?$")
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}


DeltaCallback = Callable[[str, str], None]
"""Recebe `(canal, texto)` a cada pedaço do streaming; canal é "reasoning" ou "content"."""


class LLMError(RuntimeError):
    pass


class _Retryable(Exception):
    """Falha transitória antes do primeiro byte do streaming."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


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
    reasoning: str = ""
    usage: dict[str, float] = field(default_factory=dict)


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMReply: ...


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


class ThinkSplitter:
    """Separa `<think>…</think>` inline em canais `reasoning` e `content`, pedaço a pedaço.

    Segura o final do buffer enquanto ele puder ser o começo de uma tag partida entre chunks.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self._buffer += chunk
        out: list[tuple[str, str]] = []
        while True:
            tag = self._CLOSE if self._inside else self._OPEN
            channel = "reasoning" if self._inside else "content"
            index = self._buffer.lower().find(tag)
            if index >= 0:
                if index:
                    out.append((channel, self._buffer[:index]))
                self._buffer = self._buffer[index + len(tag) :]
                self._inside = not self._inside
                continue
            keep = 0
            for size in range(min(len(tag) - 1, len(self._buffer)), 0, -1):
                if tag.startswith(self._buffer[-size:].lower()):
                    keep = size
                    break
            emit = self._buffer[: len(self._buffer) - keep]
            if emit:
                out.append((channel, emit))
            self._buffer = self._buffer[len(self._buffer) - keep :]
            return out

    def flush(self) -> list[tuple[str, str]]:
        rest, self._buffer = self._buffer, ""
        if not rest:
            return []
        return [("reasoning" if self._inside else "content", rest)]


class _StreamState:
    """Acumula os pedaços de um streaming e avisa o `on_delta` a cada um."""

    def __init__(self, on_delta: DeltaCallback) -> None:
        self.on_delta = on_delta
        self.reasoning: list[str] = []
        self.content: list[str] = []
        self.dedicated_reasoning = False
        self.splitter = ThinkSplitter()

    def _emit(self, channel: str, text: str) -> None:
        if not text:
            return
        (self.reasoning if channel == "reasoning" else self.content).append(text)
        self.on_delta(channel, text)

    def add_reasoning(self, text: str) -> None:
        self.dedicated_reasoning = True
        self._emit("reasoning", text)

    def add_content(self, text: str) -> None:
        if self.dedicated_reasoning:
            self._emit("content", text)
        else:
            for channel, part in self.splitter.feed(text):
                self._emit(channel, part)

    def finish(self) -> tuple[str, str]:
        for channel, part in self.splitter.flush():
            self._emit(channel, part)
        return "".join(self.content), "".join(self.reasoning)


def _json_lines_error(exc: Exception) -> LLMError:
    return LLMError(f"Streaming interrompido: {exc}")


def _openai_usage(usage: dict[str, Any], timings: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    prompt = usage.get("prompt_tokens", timings.get("prompt_n"))
    completion = usage.get("completion_tokens", timings.get("predicted_n"))
    if prompt is not None:
        out["prompt_tokens"] = prompt
    if completion is not None:
        out["completion_tokens"] = completion
    if timings.get("predicted_per_second") is not None:
        out["tokens_per_second"] = timings["predicted_per_second"]
    if timings.get("prompt_ms") is not None or timings.get("predicted_ms") is not None:
        out["duration_ms"] = float(timings.get("prompt_ms") or 0) + float(timings.get("predicted_ms") or 0)
    return out


def _ollama_usage(data: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    if data.get("prompt_eval_count") is not None:
        out["prompt_tokens"] = data["prompt_eval_count"]
    if data.get("eval_count") is not None:
        out["completion_tokens"] = data["eval_count"]
        if data.get("eval_duration"):
            out["tokens_per_second"] = data["eval_count"] / (data["eval_duration"] / 1e9)
    if data.get("total_duration") is not None:
        out["duration_ms"] = data["total_duration"] / 1e6
    return out


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
    supports_stream = True

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

    def build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        options: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        options = options or {}
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": self.convert_messages(messages),
            "stream": stream,
            "think": options.get("think", self.settings.llm_think),
            "keep_alive": self.settings.llm_keep_alive,
            "options": {
                "num_ctx": self.settings.llm_num_ctx,
                "num_predict": options.get("max_tokens", self.settings.llm_max_tokens),
                "temperature": options.get("temperature", self.settings.llm_temperature),
            },
        }
        if tools:
            payload["tools"] = tools
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMReply:
        if on_delta is not None:
            return await self._chat_stream(messages, tools, options, on_delta)
        payload = self.build_payload(messages, tools, options)
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

    async def _chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        options: dict[str, Any] | None,
        on_delta: DeltaCallback,
    ) -> LLMReply:
        """NDJSON do `/api/chat` com `stream: true`; `message.thinking` é o raciocínio."""
        payload = self.build_payload(messages, tools, options, stream=True)
        state = _StreamState(on_delta)
        tool_calls: list[Any] = []
        usage: dict[str, float] = {}
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", "replace")[:300]
                    raise LLMError(f"Ollama respondeu {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError as exc:
                        raise LLMError(f"Linha de streaming inválida: {line[:200]}") from exc
                    message = data.get("message") or {}
                    if message.get("thinking"):
                        state.add_reasoning(message["thinking"])
                    if message.get("content"):
                        state.add_content(message["content"])
                    tool_calls.extend(message.get("tool_calls") or [])
                    if data.get("done"):
                        usage = _ollama_usage(data)
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama inacessível em {self.settings.llm_base_url}: {exc}") from exc
        content, reasoning = state.finish()
        reply = _parse_message({"content": content, "tool_calls": tool_calls}, {})
        reply.reasoning = reasoning
        reply.usage = usage
        return reply

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
_KEYLESS_PROVIDERS = {"llamacpp", "llama.cpp", "llama-server"}


class OpenAICompatClient:
    """Fala `/chat/completions`: worker vLLM do RunPod Serverless, `llama-server` local ou outro compatível.

    Partidas a frio podem levar minutos: o timeout é longo e erros transitórios
    (timeout, 429, 5xx) são repetidos `llm_retries` vezes. O `llama-server` local não exige chave.
    """

    supports_stream = True

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_seconds: tuple[float, ...] = (3.0, 10.0, 20.0),
    ) -> None:
        self.local = settings.llm_provider.lower() in _KEYLESS_PROVIDERS
        if not settings.llm_api_key and not self.local:
            raise LLMError("LLM_API_KEY ausente (chave do RunPod ou do provedor).")
        self.settings = settings
        self.base_url = settings.llm_base_url.rstrip("/")
        self.backoff = backoff_seconds
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
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

    def build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        options: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        options = options or {}
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": self.convert_messages(messages),
            "temperature": options.get("temperature", self.settings.llm_temperature),
            "max_tokens": options.get("max_tokens", self.settings.llm_max_tokens),
            "stream": stream,
            # Qwen3.x pensa por padrão; vLLM e llama-server aceitam este campo extra no corpo.
            "chat_template_kwargs": {"enable_thinking": options.get("think", self.settings.llm_think)},
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMReply:
        payload = self.build_payload(messages, tools, options, stream=on_delta is not None)
        attempts = max(0, self.settings.llm_retries) + 1
        last_error = "erro desconhecido"
        for attempt in range(attempts):
            try:
                if on_delta is not None:
                    return await self._stream_once(payload, on_delta)
                response = await self._client.post(f"{self.base_url}/chat/completions", json=payload)
            except _Retryable as exc:
                last_error = exc.detail
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

    async def _stream_once(self, payload: dict[str, Any], on_delta: DeltaCallback) -> LLMReply:
        """Uma tentativa de SSE. Só falhas antes do primeiro byte (status/conexão) são repetíveis."""
        state = _StreamState(on_delta)
        calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        timings: dict[str, Any] = {}
        async with self._client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as response:
            if response.status_code >= 400:
                detail = (await response.aread()).decode("utf-8", "replace")[:200]
                message = f"HTTP {response.status_code}: {detail}"
                if response.status_code in _RETRY_STATUS:
                    raise _Retryable(message)
                raise LLMError(message)
            try:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                    except ValueError:
                        continue
                    usage.update(chunk.get("usage") or {})
                    timings.update(chunk.get("timings") or {})
                    for choice in chunk.get("choices") or []:
                        part = choice.get("delta") or {}
                        reasoning = part.get("reasoning_content") or part.get("reasoning")
                        if reasoning:
                            state.add_reasoning(reasoning)
                        if part.get("content"):
                            state.add_content(part["content"])
                        for item in part.get("tool_calls") or []:
                            slot = calls.setdefault(item.get("index", 0), {"function": {"name": "", "arguments": ""}})
                            if item.get("id"):
                                slot["id"] = item["id"]
                            function = item.get("function") or {}
                            if function.get("name"):
                                slot["function"]["name"] += function["name"]
                            slot["function"]["arguments"] += function.get("arguments") or ""
            except httpx.HTTPError as exc:
                raise _json_lines_error(exc) from exc
        content, reasoning = state.finish()
        reply = _parse_message(
            {"content": content, "tool_calls": [calls[key] for key in sorted(calls)]}, {}
        )
        reply.reasoning = reasoning
        reply.usage = _openai_usage(usage, timings)
        return reply

    async def health(self) -> dict[str, Any]:
        """Não gera job: no RunPod usa /health do endpoint; noutros provedores, /models."""
        endpoint = self.runpod_endpoint_id
        try:
            if self.local:
                return await self._llamacpp_health()
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

    async def _llamacpp_health(self) -> dict[str, Any]:
        root = self.base_url[: -len("/v1")] if self.base_url.endswith("/v1") else self.base_url
        try:
            response = await self._client.get(f"{root}/health", timeout=5)
            if response.status_code == 503:
                return {"ok": False, "provider": "llamacpp", "detail": "llama-server ainda carregando o modelo"}
            response.raise_for_status()
            models_response = await self._client.get(f"{self.base_url}/models", timeout=5)
            models_response.raise_for_status()
            served = [item.get("id") for item in models_response.json().get("data", []) if item.get("id")]
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "provider": "llamacpp", "detail": f"llama-server inacessível: {exc}"}
        return {
            "ok": True,
            "provider": "llamacpp",
            "model": self.settings.llm_model,
            # O llama-server serve um único modelo e ignora o campo "model" da requisição.
            "model_present": True,
            "detail": f"servindo: {', '.join(served) or 'modelo sem nome'}",
        }

    async def aclose(self) -> None:
        await self._client.aclose()


def make_llm(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return OllamaClient(settings)
    if provider in {"openai", "runpod", "vllm", *_KEYLESS_PROVIDERS}:
        return OpenAICompatClient(settings)
    raise LLMError(f"LLM_PROVIDER desconhecido: {settings.llm_provider} (use ollama, llamacpp ou openai).")


def make_cloud_llm(settings: Settings) -> LLMClient | None:
    """Backend `cloud` opcional (RunPod) para workspaces que pedem mais raciocínio. None se não configurado."""
    if not settings.llm_cloud_base_url:
        return None
    return OpenAICompatClient(
        settings.with_overrides(
            llm_provider="openai",
            llm_base_url=settings.llm_cloud_base_url,
            llm_api_key=settings.llm_cloud_api_key,
            llm_model=settings.llm_cloud_model or settings.llm_model,
            llm_timeout_seconds=settings.llm_cloud_timeout_seconds,
        )
    )
