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


def test_stable_window_moves_in_steps():
    from nickel.core.agent import stable_window
    starts = []
    for total in range(20, 32, 2):  # 6 turnos (usuário + assistente) com limite 20
        recent = list(range(total - 20, total))
        window = stable_window(recent, total, 20)
        assert 10 <= len(window) <= 20 and window[-1] == total - 1 and window[0] % 2 == 0
        starts.append(window[0])
    assert starts == [0, 10, 10, 10, 10, 10]  # o prefixo só muda a cada 5 turnos
    assert stable_window([1, 2, 3], 3, 20) == [1, 2, 3]
