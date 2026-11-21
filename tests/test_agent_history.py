"""Histórico com tool calls reais e bloqueio de ação inventada pelo modelo."""

from __future__ import annotations

from typing import Any

import pytest

from nickel.core.agent import Agent, Turn, strip_fake_action_marker
from nickel.core.llm import OllamaClient, OpenAICompatClient
from nickel.core.skills import ToolContext, ToolRegistry, ToolResult

from conftest import call, run, say

MARKER = "[ações executadas"
WARNING = "(Atenção: nenhuma ação foi executada.)"


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()

    @registry.add("echo", "Repete", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
    async def echo(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(True, f"eco: {args['text']}")

    return registry


def _store_turn(services, user: str, assistant: str, items: list[dict[str, Any]]) -> None:
    store = services.conversations
    store.add("user", user, channel="ui")
    store.add("assistant", assistant, channel="ui", attachments=[{"type": "tools", "items": items}])


def _sent(llm) -> list[dict[str, Any]]:
    return llm.calls[-1]["messages"]


def _no_marker(messages) -> bool:
    return all(MARKER not in (m.get("content") or "") for m in messages)


def test_history_replays_past_actions_as_real_tool_calls(services, llm, registry):
    item = {
        "name": "reminder_create",
        "ok": True,
        "summary": "Lembrete #1: Alongar — sáb 21/11 às 15:11.",
        "arguments": {"text": "Alongar", "when": "daqui a 20 minutos"},
        "id": "c1",
    }
    _store_turn(services, "me lembre de alongar", "Lembrete #1 criado.", [item])
    llm.queue(say("ok"))
    run(Agent(services, registry).handle(Turn(channel="ui", text="e agora?")))
    messages = _sent(llm)
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "user"]
    calling, tool, text = messages[2], messages[3], messages[4]
    assert calling["content"] == ""
    assert calling["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "reminder_create", "arguments": item["arguments"]}}
    ]
    assert tool == {
        "role": "tool",
        "tool_call_id": "c1",
        "tool_name": "reminder_create",
        "content": "ok: Lembrete #1: Alongar — sáb 21/11 às 15:11.",
    }
    assert text == {"role": "assistant", "content": "Lembrete #1 criado."}
    assert _no_marker(messages)


def test_history_handles_legacy_tool_items_without_arguments(services, llm, registry):
    _store_turn(
        services,
        "faça duas coisas",
        "Feito.",
        [{"name": "echo", "ok": True, "summary": "eco: a"}, {"name": "echo", "ok": False, "summary": "falhou"}],
    )
    message_id = services.conversations.recent(10)[-1].id
    llm.queue(say("ok"))
    run(Agent(services, registry).handle(Turn(channel="ui", text="e agora?")))
    messages = _sent(llm)
    calls = messages[2]["tool_calls"]
    assert [c["id"] for c in calls] == [f"hist-{message_id}-0", f"hist-{message_id}-1"]
    assert all(c["function"]["arguments"] == {} for c in calls)
    assert [m["tool_call_id"] for m in messages[3:5]] == [f"hist-{message_id}-0", f"hist-{message_id}-1"]
    assert [m["content"] for m in messages[3:5]] == ["ok: eco: a", "erro: falhou"]
    assert messages[5] == {"role": "assistant", "content": "Feito."}
    assert _no_marker(messages)


def test_history_strips_marker_from_stored_assistant_text(services, llm, registry):
    store = services.conversations
    store.add("user", "me lembre de alongar", channel="ui")
    store.add(
        "assistant",
        "Lembrete #2 criado: Alongar.\n[ações executadas: reminder_create: Lembrete #2: Alongar —\nsáb 21/11.]",
        channel="ui",
    )
    llm.queue(say("ok"))
    run(Agent(services, registry).handle(Turn(channel="ui", text="e agora?")))
    messages = _sent(llm)
    assert messages[2] == {"role": "assistant", "content": "Lembrete #2 criado: Alongar."}
    assert _no_marker(messages)


def test_strip_fake_action_marker_variants():
    assert strip_fake_action_marker("Oi.") == "Oi."
    assert strip_fake_action_marker("A.\n[AÇÕES EXECUTADAS: x: y]") == "A."
    assert strip_fake_action_marker("A.\n[ações executadas: x:\n y; z: w]\nB.") == "A.\nB."
    assert strip_fake_action_marker("[ações executadas: x]") == ""


def test_reply_with_marker_but_no_tool_is_flagged(services, llm, registry):
    llm.queue(say("Lembrete #2 criado.\n[ações executadas: reminder_create: Lembrete #2]"))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="me lembre de alongar")))
    assert MARKER not in reply.text
    assert reply.text == f"Lembrete #2 criado.\n{WARNING}"
    stored = services.conversations.recent(10)[-1]
    assert stored.content == reply.text
    events = services.audit.since(0)
    fake = [e for e in events if e["kind"] == "tool" and e["name"] == "<fake>"]
    assert len(fake) == 1 and fake[0]["status"] == "error"
    assert fake[0]["detail"] == {"detail": "modelo afirmou ação sem chamar a ferramenta"}
    pairs = [(e["kind"], e["status"]) for e in events]
    assert pairs.index(("tool", "error")) < pairs.index(("turn", "done"))


def test_reply_with_marker_after_real_tool_is_only_stripped(services, llm, registry):
    llm.queue(call("echo", text="abc"), say("Pronto.\n[ações executadas: echo: eco: abc]"))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="repete abc")))
    assert reply.text == "Pronto."
    assert not [e for e in services.audit.since(0) if e["name"] == "<fake>"]


def test_executed_items_store_arguments_and_id(services, llm, registry):
    reply_call = call("echo", text="abc")
    call_id = reply_call.tool_calls[0].id
    llm.queue(reply_call, say("Pronto: abc."))
    run(Agent(services, registry).handle(Turn(channel="ui", text="repete abc")))
    stored = services.conversations.recent(10)[-1]
    tools = [a for a in stored.attachments if a["type"] == "tools"]
    assert tools == [
        {
            "type": "tools",
            "items": [{"name": "echo", "ok": True, "summary": "eco: abc", "arguments": {"text": "abc"}, "id": call_id}],
        }
    ]
    # o turno seguinte reenvia a ação como tool call real, com o mesmo id
    llm.queue(say("ok"))
    run(Agent(services, registry).handle(Turn(channel="ui", text="e agora?")))
    messages = _sent(llm)
    assert messages[2]["tool_calls"][0]["id"] == call_id
    assert messages[3]["tool_call_id"] == call_id and messages[3]["content"] == "ok: eco: abc"
    assert _no_marker(messages)


@pytest.mark.parametrize("client", [OllamaClient, OpenAICompatClient])
def test_replayed_history_converts_in_both_clients(services, llm, registry, client):
    _store_turn(
        services,
        "me lembre de alongar",
        "Lembrete #1 criado.",
        [
            {"name": "reminder_create", "ok": True, "summary": "Lembrete #1", "arguments": {"text": "Alongar"}, "id": "c1"},
            {"name": "echo", "ok": False, "summary": "falhou"},
        ],
    )
    llm.queue(say("ok"))
    run(Agent(services, registry).handle(Turn(channel="ui", text="e agora?")))
    converted = client.convert_messages(_sent(llm))
    assert [m["role"] for m in converted] == ["system", "user", "assistant", "tool", "tool", "assistant", "user"]
    assert converted[2]["tool_calls"][0]["function"]["name"] == "reminder_create"
    assert all(MARKER not in str(m.get("content") or "") for m in converted)


def test_strip_fake_action_marker_singular_and_plural():
    assert strip_fake_action_marker("Nota criada.\n[ação executada: note_add]") == "Nota criada."
    assert strip_fake_action_marker("Nota criada.\n[Acao executada: note_add]") == "Nota criada."
    assert strip_fake_action_marker("Ok.\n[ações executada: x]") == "Ok."
    assert strip_fake_action_marker("Ok.\n[ação executadas: x]") == "Ok."


def test_strip_fake_action_marker_tolerates_brackets_inside_summary():
    assert strip_fake_action_marker("A.\n[ações executadas: nota [rascunho] salva]") == "A."
    assert strip_fake_action_marker("A.\n[ações executadas: x:\n lista [1] e [2]]\nB.") == "A.\nB."


def test_strip_fake_action_marker_unclosed_runs_to_end():
    assert strip_fake_action_marker("A.\n[ações executadas: nota criada") == "A."
    assert strip_fake_action_marker("A.\n[ação executada: x\nmais texto") == "A."


def test_strip_fake_action_marker_drops_surrounding_bold():
    assert strip_fake_action_marker("A.\n**[ações executadas: x]**") == "A."
    assert strip_fake_action_marker("**[ação executada: x [y]]**\nB.") == "B."
    assert strip_fake_action_marker("A.\n**[ações executadas: sem fim") == "A."
