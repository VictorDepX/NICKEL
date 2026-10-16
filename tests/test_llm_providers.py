from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from nickel.channels.whatsapp import SLOW_NOTICE, WhatsAppChannel
from nickel.core.agent import Agent, Turn
from nickel.core.host import is_oracle_cloud, memory_used_percent
from nickel.core.llm import (
    LLMError,
    LLMReply,
    OllamaClient,
    OpenAICompatClient,
    ToolCall,
    image_mime,
    make_llm,
)
from nickel.core.skills import ToolContext, ToolRegistry, ToolResult
from nickel.skills import build_registry

from conftest import run, say

RUNPOD_URL = "https://api.runpod.ai/v2/abc123/openai/v1"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 32).decode()


def runpod_settings(settings, **extra):
    return settings.with_overrides(
        llm_provider="openai", llm_base_url=RUNPOD_URL, llm_api_key="rp_key", llm_model="qwen3.6-27b", **extra
    )


AGENT_MESSAGES = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "o que é isso?", "images": [PNG]},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "notes_capture", "arguments": {"title": "Á"}}}],
    },
    {"role": "tool", "tool_call_id": "call_1", "tool_name": "notes_capture", "content": '{"ok": true}'},
]


def test_factory(settings):
    assert isinstance(make_llm(settings), OllamaClient)
    assert isinstance(make_llm(runpod_settings(settings)), OpenAICompatClient)
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        make_llm(settings.with_overrides(llm_provider="openai"))
    with pytest.raises(LLMError, match="desconhecido"):
        make_llm(settings.with_overrides(llm_provider="xyz"))


def test_image_mime():
    assert image_mime(PNG) == "image/png"
    assert image_mime(JPEG) == "image/jpeg"


def test_openai_payload_conversion(settings):
    client = OpenAICompatClient(runpod_settings(settings))
    tools = [{"type": "function", "function": {"name": "notes_capture", "parameters": {}}}]
    payload = client.build_payload(AGENT_MESSAGES, tools)
    assert payload["model"] == "qwen3.6-27b" and payload["tool_choice"] == "auto" and payload["tools"] == tools
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    user = payload["messages"][1]
    assert user["content"][0] == {"type": "text", "text": "o que é isso?"}
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    call = payload["messages"][2]["tool_calls"][0]
    assert call["id"] == "call_1" and json.loads(call["function"]["arguments"]) == {"title": "Á"}
    assert payload["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'}


def test_ollama_conversion_keeps_native_format(settings):
    payload = OllamaClient(settings).build_payload(AGENT_MESSAGES, None)
    assert payload["messages"][1]["images"] == [PNG]
    assert payload["messages"][2]["tool_calls"][0] == {
        "type": "function", "function": {"name": "notes_capture", "arguments": {"title": "Á"}}
    }
    assert payload["messages"][3] == {"role": "tool", "tool_name": "notes_capture", "content": '{"ok": true}'}
    assert payload["options"]["num_predict"] == 2048


def test_openai_chat_parses_tool_calls_and_auth(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "abc", "type": "function",
                            "function": {"name": "spotify_play", "arguments": '{"query": "Djavan"}'}}],
        }}]})

    client = OpenAICompatClient(runpod_settings(settings), transport=httpx.MockTransport(handler))
    reply = run(client.chat([{"role": "user", "content": "toca djavan"}]))
    assert seen["url"] == f"{RUNPOD_URL}/chat/completions" and seen["auth"] == "Bearer rp_key"
    assert reply.content == "" and reply.tool_calls[0].id == "abc"
    assert reply.tool_calls[0].arguments == {"query": "Djavan"}


def test_openai_retries_transient_errors(settings):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("frio", request=request)
        if calls["n"] == 2:
            return httpx.Response(503, text="worker starting")
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>x</think>Pronto."}}]})

    client = OpenAICompatClient(runpod_settings(settings), transport=httpx.MockTransport(handler), backoff_seconds=(0,))
    assert run(client.chat([{"role": "user", "content": "oi"}])).content == "Pronto."
    assert calls["n"] == 3


def test_openai_gives_up_and_does_not_retry_client_errors(settings):
    always_503 = httpx.MockTransport(lambda r: httpx.Response(503, text="no"))
    client = OpenAICompatClient(runpod_settings(settings, llm_retries=1), transport=always_503, backoff_seconds=(0,))
    with pytest.raises(LLMError, match="após 2 tentativa"):
        run(client.chat([{"role": "user", "content": "oi"}]))

    calls = {"n": 0}

    def bad_request(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad tool schema")

    client = OpenAICompatClient(runpod_settings(settings), transport=httpx.MockTransport(bad_request), backoff_seconds=(0,))
    with pytest.raises(LLMError, match="HTTP 400"):
        run(client.chat([{"role": "user", "content": "oi"}]))
    assert calls["n"] == 1


def test_runpod_health_uses_control_endpoint(settings):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(str(request.url))
        return httpx.Response(200, json={"jobs": {"inQueue": 1}, "workers": {"idle": 0, "running": 1}})

    client = OpenAICompatClient(runpod_settings(settings), transport=httpx.MockTransport(handler))
    health = run(client.health())
    assert paths == ["https://api.runpod.ai/v2/abc123/health"]
    assert health["ok"] and health["provider"] == "runpod" and health["warm"] is True
    assert "1 em uso" in health["detail"] and "1 na fila" in health["detail"]


def test_generic_openai_health_lists_models(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "qwen3.6-27b"}]})

    configured = runpod_settings(settings).with_overrides(llm_base_url="https://example.com/v1")
    health = run(OpenAICompatClient(configured, transport=httpx.MockTransport(handler)).health())
    assert health == {"ok": True, "provider": "openai", "model": "qwen3.6-27b", "model_present": True}


def test_agent_tool_call_ids_round_trip(services, llm):
    registry = ToolRegistry()

    @registry.add("ping", "ping")
    async def ping(ctx: ToolContext, args):
        return ToolResult(True, "pong")

    llm.queue(LLMReply(content="", tool_calls=[ToolCall(name="ping", arguments={}, id="xyz")]), say("ok"))
    run(Agent(services, registry).handle(Turn(channel="ui", text="ping")))
    sent = llm.calls[1]["messages"]
    assert sent[-2]["tool_calls"][0]["id"] == "xyz"
    assert sent[-1]["tool_call_id"] == "xyz" and sent[-1]["tool_name"] == "ping"


class SlowLLM:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def chat(self, messages, tools=None):
        await asyncio.sleep(self.delay)
        return say("Resposta.")


def test_whatsapp_slow_notice(services):
    services.settings = services.settings.with_overrides(wa_slow_notice_seconds=0.05)
    services.llm = SlowLLM(0.2)
    channel = WhatsAppChannel(services, Agent(services, build_registry()))
    run(channel.handle_inbound({"id": "s1", "type": "chat", "body": "oi"}))
    assert services.whatsapp.sent == [SLOW_NOTICE, "Resposta."]


def test_whatsapp_no_notice_when_fast_or_disabled(services):
    services.llm = SlowLLM(0)
    channel = WhatsAppChannel(services, Agent(services, build_registry()))
    run(channel.handle_inbound({"id": "f1", "type": "chat", "body": "oi"}))
    services.settings = services.settings.with_overrides(wa_slow_notice_seconds=0)
    services.llm = SlowLLM(0.1)
    run(channel.handle_inbound({"id": "f2", "type": "chat", "body": "oi"}))
    assert services.whatsapp.sent == ["Resposta.", "Resposta."]


def test_host_helpers(tmp_path):
    tag = tmp_path / "tag"
    tag.write_text("OracleCloud.com\n")
    assert is_oracle_cloud(tag) is True
    tag.write_text("Default string\n")
    assert is_oracle_cloud(tag) is False
    assert is_oracle_cloud(tmp_path / "missing") is False
    meminfo = "MemTotal:       8000000 kB\nMemFree:  100 kB\nMemAvailable:   6000000 kB\n"
    assert memory_used_percent(meminfo) == pytest.approx(25.0)
    assert memory_used_percent("lixo") is None
