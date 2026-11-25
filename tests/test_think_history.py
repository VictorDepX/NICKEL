"""Com pensar ligado, o histórico vai como transcrição (o Gemma 4 parava de pensar com turnos)."""

from __future__ import annotations

from nickel.core.agent import Agent, Turn, history_transcript
from nickel.core.skills import ToolRegistry
from nickel.skills import reminders

from conftest import run, say


def _agent(services):
    registry = ToolRegistry()
    reminders.register(registry)
    return Agent(services, registry)


def test_think_on_folds_history_into_current_message(services, llm):
    llm.queue(say("Oi."), say("400"))
    agent = _agent(services)
    run(agent.handle(Turn(channel="ui", text="oi")))
    run(agent.handle(Turn(channel="ui", text="quanto guardo?", think=True)))
    messages = llm.calls[1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    content = messages[1]["content"]
    assert content.startswith("Conversa anterior (só contexto):\nUsuário: oi\nNICKEL: Oi.\n\nMensagem atual:\n[agora: ")
    assert content.endswith("\nquanto guardo?")


def test_think_off_keeps_history_as_turns(services, llm):
    llm.queue(say("Oi."), say("ok"))
    agent = _agent(services)
    run(agent.handle(Turn(channel="ui", text="oi")))
    run(agent.handle(Turn(channel="ui", text="tudo bem?", think=False)))
    assert [m["role"] for m in llm.calls[1]["messages"]] == ["system", "user", "assistant", "user"]


def test_transcript_keeps_past_actions_with_real_results():
    past = [
        {"role": "user", "content": "me lembre"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "reminder_create", "arguments": {"text": "x"}}}]},
        {"role": "tool", "tool_call_id": "c1", "tool_name": "reminder_create", "content": "ok: Lembrete #3 criado"},
        {"role": "assistant", "content": "Criado."},
    ]
    text = history_transcript(past, "e agora?")
    assert '[NICKEL executou reminder_create {"text": "x"} (id c1)]' in text
    assert "[resultado de reminder_create: ok: Lembrete #3 criado]" in text
    assert text.endswith("NICKEL: Criado.\n\nMensagem atual:\ne agora?")
