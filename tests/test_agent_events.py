"""Eventos de auditoria emitidos pelo agente durante um turno."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nickel.core.agent import Agent, Turn
from nickel.core.llm import LLMError, LLMReply
from nickel.core.skills import ToolContext, ToolRegistry, ToolResult
from nickel.core.stores import StateStore
from nickel.core.workspaces import WorkspaceManager

from conftest import FakeLLM, StreamingFakeLLM, call, run, say


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()

    @registry.add("echo", "Repete", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
    async def echo(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(True, f"eco: {args['text']}")

    @registry.add(
        "login",
        "Entra numa conta",
        {
            "type": "object",
            "properties": {"user": {"type": "string"}, "password": {"type": "string"}},
            "required": ["user", "password"],
        },
    )
    async def login(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(True, f"logado como {args['user']}")

    @registry.add(
        "send",
        "Envia algo (precisa de confirmação)",
        {"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
        confirm=True,
        describe=lambda a: f"enviar para {a['to']}",
    )
    async def send(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(True, f"Enviado para {args['to']}.")

    return registry


def _events(services) -> list[dict[str, Any]]:
    return services.audit.since(0)


def _pairs(events) -> list[tuple[str, str]]:
    return [(e["kind"], e["status"]) for e in events]


def _only(events, kind: str, status: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == kind and e["status"] == status]


def test_turn_emits_ordered_events_with_single_run_id(services, llm, registry):
    llm.queue(call("echo", text="abc"), say("Pronto: abc."))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="repete abc")))
    assert reply.text == "Pronto: abc."

    events = _events(services)
    assert _pairs(events) == [
        ("turn", "start"),
        ("route", "resolved"),
        ("prompt", "built"),
        ("llm", "start"),
        ("llm", "done"),
        ("tool", "start"),
        ("tool", "ok"),
        ("llm", "start"),
        ("llm", "done"),
        ("turn", "done"),
    ]
    run_ids = {e["run_id"] for e in events}
    assert len(run_ids) == 1 and None not in run_ids

    start = events[0]
    assert start["name"] == "ui"
    assert start["detail"] == {"channel": "ui", "workspace": services.workspaces.active().id, "chars": len("repete abc")}
    route = events[1]["detail"]
    assert route == {"command": None, "workspace": services.workspaces.active().id, "switched": False, "auto": False}
    prompt = events[2]["detail"]
    assert prompt["messages"] == 2 and prompt["history"] == 0 and prompt["tools"] >= 1
    assert prompt["system_chars"] > 0
    chars = sum(len(m["content"]) for m in llm.calls[0]["messages"])
    assert prompt["est_tokens"] == -(-chars // 4)
    llm_start = events[3]
    assert llm_start["name"] == services.settings.llm_model
    assert llm_start["detail"] == {
        "step": 0,
        "model": services.settings.llm_model,
        "backend": "local",
        "requested_backend": "local",
        "think": False,
    }
    first_done = events[4]["detail"]
    assert first_done["step"] == 0 and first_done["tool_calls"] == ["echo"]
    assert "prompt_tokens" not in first_done  # sem usage do servidor: chave omitida
    assert events[7]["detail"]["step"] == 1
    done = events[-1]
    assert done["detail"]["steps"] == 2 and done["detail"]["reply_chars"] == len(reply.text)
    assert isinstance(done["duration_ms"], int) and done["duration_ms"] >= 0


def test_llm_done_carries_usage_when_present(services, llm, registry):
    llm.queue(LLMReply(content="Oi.", usage={"prompt_tokens": 12, "completion_tokens": 3, "tokens_per_second": 9.5}))
    run(Agent(services, registry).handle(Turn(channel="ui", text="oi")))
    done = _only(_events(services), "llm", "done")[0]["detail"]
    assert done["prompt_tokens"] == 12 and done["completion_tokens"] == 3 and done["tokens_per_second"] == 9.5
    assert done["tool_calls"] == [] and isinstance(done["duration_ms"], int)


def test_reasoning_events_only_when_model_streams_reasoning(services, registry):
    streaming = StreamingFakeLLM(
        [say("Oi.")],
        deltas=[("reasoning", "Vou cumprimentar o usuário. "), ("reasoning", "Respondo oi."), ("content", "Oi.")],
    )
    services.llm = streaming
    run(Agent(services, registry).handle(Turn(channel="ui", text="olá")))
    finals = _only(_events(services), "reasoning", "final")
    assert len(finals) == 1
    assert finals[0]["detail"]["headline"] == "Vou cumprimentar o usuário."
    pairs = _pairs(_events(services))
    assert pairs.index(("llm", "start")) < pairs.index(("reasoning", "final")) < pairs.index(("llm", "done"))


def test_plain_llm_emits_no_reasoning(services, llm, registry):
    llm.queue(say("Oi."))
    run(Agent(services, registry).handle(Turn(channel="ui", text="olá")))
    assert not [e for e in _events(services) if e["kind"] == "reasoning"]


def test_streamed_turn_with_real_audit_log_keeps_full_text_and_short_tail(services, registry):
    long_reasoning = "Primeiro penso no pedido. " + "x" * 1500 + " Então respondo."
    services.llm = StreamingFakeLLM([say("Ok.")], deltas=[("reasoning", long_reasoning)])
    live: list[dict[str, Any]] = []
    original = services.audit.record
    services.audit.record = lambda *a, **k: live.append(original(*a, **k)) or live[-1]
    run(Agent(services, registry).handle(Turn(channel="ui", text="pense")))
    stored = services.audit.since(0)  # lido de volta do SQLite
    final = _only(stored, "reasoning", "final")[0]["detail"]
    assert final["text"] == long_reasoning
    progress = _only(live, "reasoning", "progress")  # entregue ao vivo...
    assert progress and all(len(p["detail"]["tail"]) <= 600 for p in progress)
    assert not _only(stored, "reasoning", "progress")  # ...e apagado do banco quando o final chega
    assert len({e["run_id"] for e in stored}) == 1


def test_tool_events_carry_duration_and_redacted_arguments(services, llm, registry):
    llm.queue(call("login", user="ana", password="hunter2"), say("Entrei."))
    run(Agent(services, registry).handle(Turn(channel="ui", text="entra")))
    events = _events(services)
    start = _only(events, "tool", "start")[0]
    assert start["name"] == "login"
    assert start["detail"]["arguments"] == {"user": "ana", "password": "***"}
    ok = _only(events, "tool", "ok")[0]
    assert ok["detail"]["arguments"] == {"user": "ana", "password": "***"}
    assert ok["detail"]["summary"] == "logado como ana"
    assert isinstance(ok["duration_ms"], int) and ok["duration_ms"] >= 0
    assert "hunter2" not in str(events)


def test_llm_error_records_llm_error_and_turn_error_and_returns_reply(services, registry):
    class Broken:
        async def chat(self, messages, tools=None):
            raise LLMError("conexão recusada")

    services.llm = Broken()
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="oi")))
    assert reply.text == "O modelo local não respondeu (conexão recusada)."
    events = _events(services)
    error = _only(events, "llm", "error")[0]
    assert error["name"] == services.settings.llm_model
    assert error["detail"] == {"step": 0, "detail": "conexão recusada"}
    assert _only(events, "turn", "error")[0]["detail"] == {"detail": "conexão recusada"}
    assert not _only(events, "turn", "done")


def test_unexpected_exception_records_turn_error_and_reraises(services, registry):
    class Exploding:
        async def chat(self, messages, tools=None):
            raise RuntimeError("bug inesperado")

    services.llm = Exploding()
    with pytest.raises(RuntimeError, match="bug inesperado"):
        run(Agent(services, registry).handle(Turn(channel="ui", text="oi")))
    events = _events(services)
    pairs = _pairs(events)
    assert pairs[-3:] == [("llm", "start"), ("llm", "error"), ("turn", "error")]
    assert _only(events, "llm", "error")[0]["detail"] == {"step": 0, "detail": "bug inesperado"}
    assert _only(events, "turn", "error")[0]["detail"] == {"detail": "bug inesperado"}
    assert not _only(events, "turn", "done")


def test_stream_dropping_midway_closes_reasoning_and_turn(services, registry):
    class DroppingStream(StreamingFakeLLM):
        async def chat(self, messages, tools=None, options=None, on_delta=None):
            assert on_delta is not None
            on_delta("reasoning", "Vou procurar a resposta. ")
            on_delta("reasoning", "Talvez")
            raise LLMError("conexão caiu no meio do stream")

    services.llm = DroppingStream()
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="oi")))
    assert reply.text == "O modelo local não respondeu (conexão caiu no meio do stream)."
    events = _events(services)
    llm_side = [p for p in _pairs(events) if p[0] in {"llm", "reasoning", "turn"} and p != ("reasoning", "progress")]
    assert llm_side == [
        ("turn", "start"),
        ("llm", "start"),
        ("reasoning", "final"),
        ("llm", "error"),
        ("turn", "error"),
    ]
    assert _only(events, "reasoning", "final")[0]["detail"]["text"] == "Vou procurar a resposta. Talvez"
    assert not _only(events, "turn", "done")


def test_cancelled_turn_records_turn_error_and_propagates(services, registry):
    class Hanging:
        def __init__(self) -> None:
            self.entered = asyncio.Event()

        async def chat(self, messages, tools=None):
            self.entered.set()
            await asyncio.Event().wait()  # nunca responde

    hanging = Hanging()
    services.llm = hanging

    async def scenario():
        task = asyncio.create_task(Agent(services, registry).handle(Turn(channel="ui", text="oi")))
        await hanging.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    events = _events(services)
    assert _pairs(events)[-1] == ("turn", "error")
    assert events[-1]["detail"] == {"detail": "cancelado"}
    assert not _only(events, "turn", "done")


def test_turn_think_override_reaches_llm_options(services, llm, registry):
    llm.queue(say("a"), say("b"))
    agent = Agent(services, registry)
    run(agent.handle(Turn(channel="ui", text="oi", think=True)))
    assert llm.calls[0]["options"]["think"] is True
    run(agent.handle(Turn(channel="ui", text="oi de novo")))
    assert not (llm.calls[1]["options"] or {}).get("think")


def test_confirm_and_cancel_share_a_run_scope(services, llm, registry):
    agent = Agent(services, registry)
    llm.queue(call("send", to="bob@x.com"), call("send", to="eva@x.com"))
    first = run(agent.handle(Turn(channel="whatsapp", text="manda pro bob")))
    first_run = _events(services)[0]["run_id"]

    before = len(_events(services))
    assert run(agent.confirm(first.pending_action_id, "ui")).text == "Enviado para bob@x.com."
    confirm_events = _events(services)[before:]
    assert _pairs(confirm_events) == [
        ("turn", "start"),
        ("tool", "start"),
        ("tool", "ok"),
        ("confirmation", "confirmed"),
        ("turn", "done"),
    ]
    confirm_runs = {e["run_id"] for e in confirm_events}
    assert len(confirm_runs) == 1 and None not in confirm_runs and first_run not in confirm_runs
    assert confirm_events[0]["name"] == "ui"

    second = run(agent.handle(Turn(channel="whatsapp", text="manda pra eva")))
    before = len(_events(services))
    assert run(agent.cancel(second.pending_action_id, "ui")).text == "Cancelado: enviar para eva@x.com."
    cancel_events = _events(services)[before:]
    assert _pairs(cancel_events) == [("turn", "start"), ("confirmation", "cancelled"), ("turn", "done")]
    cancel_runs = {e["run_id"] for e in cancel_events}
    assert len(cancel_runs) == 1 and None not in cancel_runs and not cancel_runs & confirm_runs


def test_pending_yes_inside_handle_is_one_traced_turn(services, llm, registry):
    agent = Agent(services, registry)
    llm.queue(call("send", to="ana@x.com"))
    run(agent.handle(Turn(channel="whatsapp", text="manda pra ana")))
    before = len(_events(services))
    assert run(agent.handle(Turn(channel="whatsapp", text="sim"))).text == "Enviado para ana@x.com."
    events = _events(services)[before:]
    assert _pairs(events) == [
        ("turn", "start"),
        ("route", "resolved"),
        ("tool", "start"),
        ("tool", "ok"),
        ("confirmation", "confirmed"),
        ("turn", "done"),
    ]
    assert len({e["run_id"] for e in events}) == 1


def test_command_only_turn_emits_turn_and_route_only(services, llm, registry):
    run(Agent(services, registry).handle(Turn(channel="ui", text="/ws")))
    events = _events(services)
    assert _pairs(events) == [("turn", "start"), ("route", "resolved"), ("turn", "done")]
    assert events[1]["detail"]["command"] == "list"
    assert events[-1]["detail"]["steps"] == 0
    assert llm.calls == []


def test_non_stream_llm_never_gets_on_delta(services, llm, registry):
    llm.queue(say("a"))
    agent = Agent(services, registry)
    run(agent.handle(Turn(channel="ui", text="oi")))
    assert llm.calls[0]["on_delta"] is None

    streaming = StreamingFakeLLM([say("b"), say("c")])
    services.llm = streaming
    services.settings = services.settings.with_overrides(llm_stream=False)
    run(agent.handle(Turn(channel="ui", text="oi")))
    assert streaming.calls[0]["on_delta"] is None

    services.settings = services.settings.with_overrides(llm_stream=True)
    run(agent.handle(Turn(channel="ui", text="oi")))
    assert callable(streaming.calls[1]["on_delta"])


def test_llm_events_name_the_cloud_model_when_cloud_backend_is_used(services, llm, registry, settings):
    settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
    (settings.workspaces_dir / "pesado.md").write_text("---\nname: Pesado\nbackend: cloud\n---\nLongo.\n", encoding="utf-8")
    services.settings = services.settings.with_overrides(llm_cloud_model="modelo-nuvem")
    services.workspaces = WorkspaceManager.from_settings(services.settings, StateStore(services.db))
    services.llm_cloud = FakeLLM([say("nuvem")])
    run(Agent(services, registry).handle(Turn(channel="ui", text="/pesado oi")))
    start = _only(_events(services), "llm", "start")[0]
    assert start["name"] == "modelo-nuvem"
    assert start["detail"] == {"step": 0, "model": "modelo-nuvem", "backend": "cloud", "requested_backend": "cloud", "think": False}


def test_cloud_workspace_without_cloud_client_records_local_backend(services, llm, registry, settings):
    settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
    (settings.workspaces_dir / "pesado.md").write_text("---\nname: Pesado\nbackend: cloud\n---\nLongo.\n", encoding="utf-8")
    services.settings = services.settings.with_overrides(llm_cloud_model="modelo-nuvem")
    services.workspaces = WorkspaceManager.from_settings(services.settings, StateStore(services.db))
    services.llm_cloud = None
    llm.queue(say("local"))
    assert run(Agent(services, registry).handle(Turn(channel="ui", text="/pesado oi"))).text == "local"
    start = _only(_events(services), "llm", "start")[0]
    assert start["name"] == services.settings.llm_model
    assert start["detail"] == {
        "step": 0,
        "model": services.settings.llm_model,
        "backend": "local",
        "requested_backend": "cloud",
        "think": False,
    }


class PerCallStream(StreamingFakeLLM):
    """Streaming com deltas diferentes em cada chamada."""

    def __init__(self, replies, per_call):
        super().__init__(replies)
        self.per_call = list(per_call)

    async def chat(self, messages, tools=None, options=None, on_delta=None):
        self.deltas = self.per_call.pop(0) if self.per_call else []
        return await super().chat(messages, tools, options, on_delta)


def test_answering_is_a_real_event_only_on_the_step_that_streams_content(services, registry):
    services.llm = PerCallStream(
        [call("echo", text="a"), say("Pronto.")],
        [[("reasoning", "Vou usar echo.")], [("reasoning", "Agora respondo."), ("content", "Pronto.")]],
    )
    run(Agent(services, registry).handle(Turn(channel="ui", text="repete a")))
    events = _events(services)
    answering = _only(events, "reasoning", "answering")
    assert len(answering) == 1 and answering[0]["detail"] == {"step": 1}
    pairs = _pairs(events)
    second_start = len(pairs) - 1 - pairs[::-1].index(("llm", "start"))
    assert pairs.index(("tool", "ok")) < second_start < pairs.index(("reasoning", "answering"))
    assert pairs.index(("reasoning", "answering")) < len(pairs) - 1 - pairs[::-1].index(("llm", "done"))
