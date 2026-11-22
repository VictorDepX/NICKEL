"""Afirmação de ação sem chamada de ferramenta: uma nova tentativa antes do aviso."""

from __future__ import annotations

import pytest

from nickel.core.agent import Agent, Turn, claims_unexecuted_action
from nickel.core.skills import ToolRegistry
from nickel.skills import reminders

from conftest import call, run, say

WARNING = "(Atenção: nenhuma ação foi executada.)"
RETRY = (
    "Sistema: sua última resposta afirmou uma ação, mas nenhuma ferramenta foi chamada e nada foi executado. "
    "Se a ação é necessária, chame a ferramenta agora. Se não, responda sem afirmar que fez algo."
)
RETRY_DETAIL = {"detail": "modelo afirmou ação sem chamar a ferramenta; pedindo nova tentativa"}
FINAL_DETAIL = {"detail": "modelo afirmou ação sem chamar a ferramenta"}


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    reminders.register(registry)
    return registry


def _fakes(services):
    return [e for e in services.audit.since(0) if e["kind"] == "tool" and e["name"] == "<fake>"]


@pytest.mark.parametrize(
    "text",
    [
        "Lembrete #2 criado: Alongar.",
        "Criei o lembrete.",
        "Memória salva.",
        "E-mail enviado para Ana.",
        "Pronto! O compromisso foi agendado para amanhã às 9h.",
        "Lembrete #3: Alongar — sáb 21/11 às 15:11.",
        "PREFERÊNCIA REGISTRADA.",
    ],
)
def test_claims_unexecuted_action_positives(text):
    assert claims_unexecuted_action(text)


@pytest.mark.parametrize(
    "text",
    [
        "Quer que eu crie um lembrete?",
        "Posso agendar se quiser.",
        "O lembrete será criado quando você confirmar.",
        "Oi! Tudo bem?",
        "A nota. Criado em 2020, o livro é ótimo.",  # particípio em outra frase
        "Ainda não salvei nada.",
        "",
    ],
)
def test_claims_unexecuted_action_negatives(text):
    assert not claims_unexecuted_action(text)


def test_claims_unexecuted_action_patterns():
    for text in ("Lembrete #2 criado: Alongar.", "Criei o lembrete.", "Memória salva.", "E-mail enviado para Ana."):
        assert claims_unexecuted_action(text), text
    for text in ("Quer que eu crie um lembrete?", "Posso agendar se quiser.", "O lembrete será criado quando você confirmar."):
        assert not claims_unexecuted_action(text), text


def test_fake_claim_triggers_one_retry_and_tool_call_succeeds(services, llm, registry):
    llm.queue(
        say("Lembrete #2 criado: Alongar — sáb 21/11 às 15:11."),
        call("reminder_create", text="Alongar", when="2099-11-21T15:11:00-03:00"),
        say("Prontinho, vou te lembrar de alongar."),
    )
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="me lembre de alongar")))

    assert reply.text == "Prontinho, vou te lembrar de alongar."
    assert WARNING not in reply.text
    assert [t["name"] for t in reply.tools] == ["reminder_create"] and reply.tools[0]["ok"]
    fakes = _fakes(services)
    assert len(fakes) == 1 and fakes[0]["status"] == "error" and fakes[0]["detail"] == RETRY_DETAIL
    ok = [e for e in services.audit.since(0) if e["kind"] == "tool" and e["status"] == "ok"]
    assert [e["name"] for e in ok] == ["reminder_create"]

    second = llm.calls[1]["messages"]
    assert second[-2] == {"role": "assistant", "content": "Lembrete #2 criado: Alongar — sáb 21/11 às 15:11."}
    assert second[-1] == {"role": "user", "content": RETRY}

    stored = services.conversations.recent(10)
    assert [m.role for m in stored] == ["user", "assistant"]
    assert all(RETRY not in m.content for m in stored)
    assert stored[-1].content == reply.text


def test_fake_claim_persisting_after_retry_gets_warning(services, llm, registry):
    llm.queue(say("Lembrete #2 criado."), say("Criei o lembrete, pode deixar."))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="me lembre de alongar")))

    assert reply.text == f"Criei o lembrete, pode deixar.\n{WARNING}"
    assert reply.tools == []
    assert len(llm.calls) == 2
    assert [e["detail"] for e in _fakes(services)] == [RETRY_DETAIL, FINAL_DETAIL]
    pairs = [(e["kind"], e["status"]) for e in services.audit.since(0)]
    assert pairs.count(("llm", "start")) == 2
    assert pairs[-2:] == [("tool", "error"), ("turn", "done")]
    stored = services.conversations.recent(10)
    assert all(RETRY not in m.content for m in stored)
    assert stored[-1].content == reply.text


def test_fake_claim_retry_answered_without_claim_has_no_warning(services, llm, registry):
    llm.queue(say("Memória salva."), say("Ainda não salvei nada. Quer que eu salve?"))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="lembra que gosto de chá")))
    assert reply.text == "Ainda não salvei nada. Quer que eu salve?"
    assert [e["detail"] for e in _fakes(services)] == [RETRY_DETAIL]


def test_marker_without_tool_also_retries_first(services, llm, registry):
    llm.queue(say("Feito.\n[ações executadas: reminder_create: Lembrete #2]"), say("Ok, me diga o horário."))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="me lembre")))
    assert reply.text == "Ok, me diga o horário."
    assert llm.calls[1]["messages"][-2] == {"role": "assistant", "content": "Feito."}
    assert [e["detail"] for e in _fakes(services)] == [RETRY_DETAIL]


def test_retry_respects_max_steps(services, llm, registry):
    services.settings = services.settings.with_overrides(agent_max_steps=1)
    llm.queue(say("Lembrete #2 criado."), say("não deveria ser pedido"))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="me lembre de alongar")))

    assert len(llm.calls) == 1  # sem passo sobrando, não há nova tentativa
    assert reply.text == f"Lembrete #2 criado.\n{WARNING}"
    assert [e["detail"] for e in _fakes(services)] == [FINAL_DETAIL]


def test_retry_counts_a_step(services, llm, registry):
    services.settings = services.settings.with_overrides(agent_max_steps=2)
    llm.queue(say("Lembrete #2 criado."), say("Criei o lembrete."), say("não deveria ser pedido"))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="me lembre de alongar")))
    assert len(llm.calls) == 2
    assert reply.text.endswith(WARNING)
    done = [e for e in services.audit.since(0) if e["kind"] == "turn" and e["status"] == "done"][0]
    assert done["detail"]["steps"] == 2


def test_llm_start_records_effective_think(services, llm, registry):
    llm.queue(say("a"), say("b"))
    agent = Agent(services, registry)
    run(agent.handle(Turn(channel="ui", text="oi", think=True)))
    run(agent.handle(Turn(channel="ui", text="oi de novo")))
    starts = [e for e in services.audit.since(0) if e["kind"] == "llm" and e["status"] == "start"]
    assert starts[0]["detail"]["think"] is True
    assert starts[1]["detail"]["think"] is services.settings.llm_think is False


def test_llm_start_think_uses_server_default(services, llm, registry):
    services.settings = services.settings.with_overrides(llm_think=True)
    llm.queue(say("a"))
    run(Agent(services, registry).handle(Turn(channel="ui", text="oi")))
    start = [e for e in services.audit.since(0) if e["kind"] == "llm" and e["status"] == "start"][0]
    assert start["detail"]["think"] is True


def test_catalog_lists_think_for_llm():
    from nickel.core.events import CATALOG

    assert "think" in CATALOG["llm"].fields
