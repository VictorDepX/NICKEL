from __future__ import annotations

from typing import Any

import pytest

from nickel.core.agent import Agent, Turn, classify_confirmation
from nickel.core.llm import LLMError
from nickel.core.skills import ToolContext, ToolRegistry, ToolResult

from conftest import call, run, say


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    executed: list[dict[str, Any]] = []
    registry.executed = executed  # type: ignore[attr-defined]

    @registry.add("echo", "Repete", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
    async def echo(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        executed.append({"tool": "echo", **args})
        return ToolResult(True, f"eco: {args['text']}")

    @registry.add(
        "send",
        "Envia algo (precisa de confirmação)",
        {"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
        confirm=True,
        describe=lambda a: f"enviar para {a['to']}",
    )
    async def send(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        executed.append({"tool": "send", **args})
        return ToolResult(True, f"Enviado para {args['to']}.")

    @registry.add("boom", "Quebra")
    async def boom(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        raise RuntimeError("falha simulada")

    return registry


def test_plain_reply_is_stored(services, llm, registry):
    llm.queue(say("Oi."))
    reply = run(Agent(services, registry).handle(Turn(channel="whatsapp", text="olá")))
    assert reply.text == "Oi."
    history = services.conversations.recent(10)
    assert [(m.role, m.content, m.channel) for m in history] == [
        ("user", "olá", "whatsapp"),
        ("assistant", "Oi.", "whatsapp"),
    ]


def test_tool_result_goes_back_to_model(services, llm, registry):
    llm.queue(call("echo", text="abc"), say("Pronto: abc."))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="repete abc")))
    assert reply.text == "Pronto: abc."
    second_call = llm.calls[1]["messages"]
    assert second_call[-2]["role"] == "assistant" and second_call[-2]["tool_calls"][0]["function"]["name"] == "echo"
    assert second_call[-1]["role"] == "tool" and "eco: abc" in second_call[-1]["content"]
    assert registry.executed == [{"tool": "echo", "text": "abc"}]
    # O resumo da ação entra no histórico para o próximo turno
    llm.queue(say("ok"))
    run(Agent(services, registry).handle(Turn(channel="ui", text="e agora?")))
    history_text = " ".join(m["content"] for m in llm.calls[2]["messages"] if m["role"] == "assistant")
    assert "echo: eco: abc" in history_text


def test_confirmation_flow_yes(services, llm, registry):
    agent = Agent(services, registry)
    llm.queue(call("send", to="ana@x.com"))
    reply = run(agent.handle(Turn(channel="whatsapp", text="manda pra ana")))
    assert reply.pending_action_id
    assert "enviar para ana@x.com" in reply.text and "sim ou não" in reply.text
    assert registry.executed == []

    reply = run(agent.handle(Turn(channel="whatsapp", text="Sim, pode")))
    assert reply.text == "Enviado para ana@x.com."
    assert registry.executed == [{"tool": "send", "to": "ana@x.com"}]
    assert services.pending.current() is None
    assert len(llm.calls) == 1  # a confirmação não passa pelo modelo


def test_confirmation_flow_no(services, llm, registry):
    agent = Agent(services, registry)
    llm.queue(call("send", to="ana@x.com"))
    run(agent.handle(Turn(channel="whatsapp", text="manda")))
    reply = run(agent.handle(Turn(channel="whatsapp", text="não")))
    assert reply.text == "Cancelado."
    assert registry.executed == []


def test_unrelated_message_drops_pending(services, llm, registry):
    agent = Agent(services, registry)
    llm.queue(call("send", to="ana@x.com"), say("Tudo bem."))
    run(agent.handle(Turn(channel="whatsapp", text="manda")))
    run(agent.handle(Turn(channel="whatsapp", text="na verdade, que horas são?")))
    assert services.pending.current() is None
    reply = run(agent.handle(Turn(channel="whatsapp", text="sim")))
    assert registry.executed == []  # "sim" tardio não executa nada
    assert reply.text  # vai para o modelo como mensagem comum


def test_confirm_from_ui(services, llm, registry):
    agent = Agent(services, registry)
    llm.queue(call("send", to="bob@x.com"))
    reply = run(agent.handle(Turn(channel="whatsapp", text="manda pro bob")))
    result = run(agent.confirm(reply.pending_action_id, "ui"))
    assert result.text == "Enviado para bob@x.com."
    assert run(agent.confirm(reply.pending_action_id, "ui")).text == "Essa ação não está mais pendente."


def test_unknown_tool_and_bad_arguments_are_reported_to_model(services, llm, registry):
    llm.queue(call("inexistente"), call("echo"), say("Desisto."))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="x")))
    assert reply.text == "Desisto."
    tool_messages = [m for m in llm.calls[2]["messages"] if m["role"] == "tool"]
    assert "Tool desconhecida" in tool_messages[0]["content"]
    assert "'text' é obrigatório" in tool_messages[1]["content"]


def test_tool_exception_becomes_error_result(services, llm, registry):
    llm.queue(call("boom"), say("Deu erro."))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="x")))
    assert reply.tools[0]["ok"] is False and "falha simulada" in reply.tools[0]["summary"]
    assert services.audit.recent(5)[0]["status"] == "error"


def test_llm_error_is_friendly(services, registry):
    class Broken:
        async def chat(self, messages, tools=None):
            raise LLMError("conexão recusada")

    services.llm = Broken()
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="oi")))
    assert "modelo local não respondeu" in reply.text


def test_max_steps(services, llm, registry):
    services.settings = services.settings.with_overrides(agent_max_steps=2)
    llm.queue(call("echo", text="1"), call("echo", text="2"), call("echo", text="3"))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="loop")))
    assert reply.text.startswith("Parei após 2 passos")


def test_images_only_in_current_turn(services, llm, registry):
    llm.queue(say("Um gato."), say("Ok."))
    agent = Agent(services, registry)
    run(agent.handle(Turn(channel="whatsapp", text="o que é isso?", images=["AAAA"],
                          attachments=[{"type": "image", "path": "/tmp/x.jpg"}])))
    assert llm.calls[0]["messages"][-1]["images"] == ["AAAA"]
    run(agent.handle(Turn(channel="whatsapp", text="e a cor?")))
    past = llm.calls[1]["messages"]
    assert all("images" not in m for m in past[:-1])
    assert any("[imagem enviada]" in m["content"] for m in past)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sim", "yes"),
        ("Sim!", "yes"),
        ("pode mandar", "yes"),
        ("ok, pode", "yes"),
        ("confirmo", "yes"),
        ("não", "no"),
        ("Nao, cancela", "no"),
        ("sim mas troca o assunto", None),
        ("que horas são", None),
        ("", None),
    ],
)
def test_classify_confirmation(text, expected):
    assert classify_confirmation(text) == expected
