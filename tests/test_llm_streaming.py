from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from nickel.core.llm import LLMError, OllamaClient, OpenAICompatClient, ThinkSplitter

from conftest import run

FIXTURES = Path(__file__).parent / "fixtures"
MSGS = [{"role": "user", "content": "oi"}]


def sse(*events) -> bytes:
    out = ""
    for event in events:
        out += "data: " + (event if isinstance(event, str) else json.dumps(event)) + "\n\n"
    return out.encode()


def delta(**fields):
    return {"choices": [{"index": 0, "delta": fields, "finish_reason": None}]}


def oai(settings, handler, **extra):
    cfg = settings.with_overrides(
        llm_provider="openai", llm_base_url="http://x/v1", llm_api_key="k", llm_model="m", **extra
    )
    return OpenAICompatClient(cfg, transport=httpx.MockTransport(handler), backoff_seconds=(0.0,))


def collect():
    got: list[tuple[str, str]] = []
    return got, lambda channel, text: got.append((channel, text))


class FailingStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        raise httpx.ReadError("conexão caiu")


def test_without_on_delta_payload_stays_non_streaming(settings):
    client = oai(settings, lambda r: httpx.Response(200))
    assert client.build_payload(MSGS, None)["stream"] is False
    assert "stream_options" not in client.build_payload(MSGS, None)
    assert OllamaClient(settings).build_payload(MSGS, None)["stream"] is False
    assert client.build_payload(MSGS, None, stream=True)["stream_options"] == {"include_usage": True}
    assert OllamaClient(settings).build_payload(MSGS, None, stream=True)["stream"] is True


def test_openai_stream_collects_content_reasoning_and_usage(settings):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=sse(
                delta(content=None),
                delta(reasoning_content="penso"),
                delta(reasoning_content=" ok"),
                delta(content="Olá"),
                delta(content=" mundo"),
                {
                    "choices": [],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    "timings": {"prompt_ms": 100.0, "predicted_ms": 400.0, "predicted_per_second": 12.5},
                },
                "[DONE]",
            ),
        )

    got, on_delta = collect()
    reply = run(oai(settings, handler).chat(MSGS, on_delta=on_delta))
    assert seen["body"]["stream"] is True
    assert seen["body"]["stream_options"] == {"include_usage": True}
    assert [c for c, _ in got] == ["reasoning", "reasoning", "content", "content"]
    assert reply.reasoning == "penso ok"
    assert reply.content == "Olá mundo"
    assert reply.usage["completion_tokens"] == 5
    assert reply.usage["prompt_tokens"] == 10
    assert reply.usage["tokens_per_second"] == 12.5
    assert reply.usage["duration_ms"] == 500.0


def test_openai_stream_assembles_tool_call_arguments_split_in_deltas(settings):
    def handler(request):
        first = {"index": 0, "id": "call_9", "type": "function", "function": {"name": "note", "arguments": '{"a"'}}
        return httpx.Response(
            200,
            content=sse(
                delta(tool_calls=[first]),
                delta(tool_calls=[{"index": 0, "function": {"arguments": ': "x", "b"'}}]),
                delta(tool_calls=[{"index": 0, "function": {"arguments": ": 2}"}}]),
                "[DONE]",
            ),
        )

    reply = run(oai(settings, handler).chat(MSGS, on_delta=lambda c, t: None))
    assert reply.tool_calls[0].name == "note"
    assert reply.tool_calls[0].arguments == {"a": "x", "b": 2}
    assert reply.tool_calls[0].id == "call_9"


def test_openai_stream_splits_inline_think_when_no_reasoning_field(settings):
    def handler(request):
        return httpx.Response(200, content=sse(delta(content="<think>hm"), delta(content="m</think>resp"), "[DONE]"))

    got, on_delta = collect()
    reply = run(oai(settings, handler).chat(MSGS, on_delta=on_delta))
    assert reply.reasoning == "hmm"
    assert reply.content == "resp"
    assert ("reasoning", "hm") in got and ("content", "resp") in got


def test_ollama_stream_reads_thinking_and_eval_counts(settings):
    lines = [
        {"message": {"role": "assistant", "thinking": "hmm"}, "done": False},
        {"message": {"role": "assistant", "content": "Oi"}, "done": False},
        {
            "message": {"role": "assistant", "content": "!"},
            "done": True,
            "prompt_eval_count": 7,
            "eval_count": 20,
            "eval_duration": 2_000_000_000,
            "total_duration": 3_000_000_000,
        },
    ]
    body = ("\n".join(json.dumps(x) for x in lines) + "\n").encode()
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=body)

    got, on_delta = collect()
    reply = run(OllamaClient(settings, transport=httpx.MockTransport(handler)).chat(MSGS, on_delta=on_delta))
    assert seen["body"]["stream"] is True
    assert got == [("reasoning", "hmm"), ("content", "Oi"), ("content", "!")]
    assert reply.reasoning == "hmm"
    assert reply.content == "Oi!"
    assert reply.usage["completion_tokens"] == 20
    assert reply.usage["prompt_tokens"] == 7
    assert reply.usage["tokens_per_second"] == 10.0
    assert reply.usage["duration_ms"] == 3000.0


def test_think_splitter_handles_tag_split_across_chunks():
    splitter = ThinkSplitter()
    parts = splitter.feed("<thi") + splitter.feed("nk>ab</th") + splitter.feed("ink>ok") + splitter.flush()
    assert "".join(t for c, t in parts if c == "reasoning") == "ab"
    assert "".join(t for c, t in parts if c == "content") == "ok"


def test_think_splitter_flushes_pending_partial_tag():
    splitter = ThinkSplitter()
    parts = splitter.feed("a <th") + splitter.flush()
    assert "".join(t for c, t in parts if c == "content") == "a <th"


def test_stream_cut_midway_raises_llm_error_with_partial_reasoning(settings):
    def handler(request):
        return httpx.Response(200, stream=FailingStream([sse(delta(reasoning_content="a")), sse(delta(reasoning_content="b"))]))

    got, on_delta = collect()
    with pytest.raises(LLMError):
        run(oai(settings, handler).chat(MSGS, on_delta=on_delta))
    assert got == [("reasoning", "a"), ("reasoning", "b")]


def test_retry_only_before_first_byte(settings):
    calls = {"n": 0}

    def retry_ok(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, content=sse(delta(content="ok"), "[DONE]"))

    reply = run(oai(settings, retry_ok, llm_retries=2).chat(MSGS, on_delta=lambda c, t: None))
    assert reply.content == "ok" and calls["n"] == 2

    calls["n"] = 0

    def fail_after_bytes(request):
        calls["n"] += 1
        return httpx.Response(200, stream=FailingStream([sse(delta(content="x"))]))

    with pytest.raises(LLMError):
        run(oai(settings, fail_after_bytes, llm_retries=2).chat(MSGS, on_delta=lambda c, t: None))
    assert calls["n"] == 1


def test_openai_stream_in_band_error_chunk_raises(settings):
    body = sse(delta(content="Ol"), {"error": {"message": "boom"}}, "[DONE]")
    got, on_delta = collect()
    with pytest.raises(LLMError, match="boom"):
        run(oai(settings, lambda r: httpx.Response(200, content=body)).chat(MSGS, on_delta=on_delta))
    assert got == [("content", "Ol")]


def test_openai_stream_error_event_line_raises(settings):
    body = sse(delta(content="Ol")) + b'error: {"message": "oom"}\n\n'
    with pytest.raises(LLMError, match="oom"):
        run(oai(settings, lambda r: httpx.Response(200, content=body)).chat(MSGS, on_delta=lambda c, t: None))


def test_openai_stream_without_done_raises(settings):
    body = sse(delta(content="Ol"))
    with pytest.raises(LLMError, match="sem \\[DONE\\]"):
        run(oai(settings, lambda r: httpx.Response(200, content=body)).chat(MSGS, on_delta=lambda c, t: None))


def test_ollama_stream_in_band_error_raises(settings):
    body = (json.dumps({"message": {"content": "Ol"}, "done": False}) + "\n" + json.dumps({"error": "model crashed"}) + "\n").encode()
    client = OllamaClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)))
    with pytest.raises(LLMError, match="model crashed"):
        run(client.chat(MSGS, on_delta=lambda c, t: None))


def test_ollama_stream_without_done_raises(settings):
    body = (json.dumps({"message": {"content": "Ol"}, "done": False}) + "\n").encode()
    client = OllamaClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)))
    with pytest.raises(LLMError, match="done"):
        run(client.chat(MSGS, on_delta=lambda c, t: None))


def _real(name: str, settings):
    body = (FIXTURES / name).read_bytes()
    got, on_delta = collect()
    client = oai(settings, lambda r: httpx.Response(200, content=body))
    return run(client.chat(MSGS, on_delta=on_delta)), got


def test_parses_real_llamacpp_stream(settings):
    reply, got = _real("llamacpp-stream-content.sse", settings)
    assert len(reply.reasoning) == 1780
    assert len(reply.content) == 32
    assert reply.usage["completion_tokens"] == 509
    assert reply.usage["prompt_tokens"] == 38
    assert reply.usage["tokens_per_second"] == pytest.approx(10.6233, rel=1e-3)
    assert reply.usage["duration_ms"] == pytest.approx(2841.039 + 47819.418)
    assert got[0][0] == "reasoning" and got[-1][0] == "content"
    assert not reply.tool_calls


def test_parses_real_llamacpp_tool_stream(settings):
    reply, _ = _real("llamacpp-stream-tool.sse", settings)
    assert len(reply.reasoning) == 469
    assert reply.content == ""
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].name == "reminder_create"
    assert isinstance(reply.tool_calls[0].arguments, dict) and reply.tool_calls[0].arguments


def test_parses_real_llamacpp_stream_cut_by_length(settings):
    reply, _ = _real("llamacpp-stream.sse", settings)
    assert reply.reasoning and reply.content == ""
    assert reply.usage["completion_tokens"] == 400


def test_openai_stream_strips_literal_think_tags_from_reasoning(settings):
    def handler(request):
        return httpx.Response(200, content=sse(delta(reasoning_content="<think>\n"), delta(content="Feito."), "[DONE]"))

    got, on_delta = collect()
    reply = run(oai(settings, handler).chat(MSGS, on_delta=on_delta))
    assert reply.reasoning == "\n"
    assert "<think>" not in "".join(t for _, t in got)
    assert reply.content == "Feito."


def test_reasoning_tags_split_across_chunks_are_stripped(settings):
    def handler(request):
        return httpx.Response(
            200,
            content=sse(
                delta(reasoning_content="<thi"),
                delta(reasoning_content="nk>Vou ver a < hora</th"),
                delta(reasoning_content="ink>"),
                delta(content="Ok"),
                "[DONE]",
            ),
        )

    got, on_delta = collect()
    reply = run(oai(settings, handler).chat(MSGS, on_delta=on_delta))
    assert reply.reasoning == "Vou ver a < hora"
    assert "".join(t for c, t in got if c == "reasoning") == "Vou ver a < hora"
    assert [c for c, _ in got][-1] == "content"


def test_ollama_thinking_tags_are_stripped(settings):
    lines = [
        {"message": {"role": "assistant", "thinking": "<think>\n"}, "done": False},
        {"message": {"role": "assistant", "content": "Oi"}, "done": True},
    ]
    body = ("\n".join(json.dumps(x) for x in lines) + "\n").encode()
    got, on_delta = collect()
    client = OllamaClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)))
    reply = run(client.chat(MSGS, on_delta=on_delta))
    assert "<think>" not in reply.reasoning
    assert all("<think>" not in t for _, t in got)
