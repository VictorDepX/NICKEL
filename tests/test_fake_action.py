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
        # bloqueio por oração: o "se"/"posso" de outra oração não salva a afirmação
        "Lembrete criado, se precisar me avise.",
        "Pronto, lembrete agendado para 15h, qualquer coisa é só falar.",
        "Memória salva; se quiser, posso listar.",
        "Criei o lembrete, mas se quiser eu mudo o horário.",
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
        # I-1: pergunta, negação ou modal também no ramo `#N`
        "Quer que eu apague o lembrete #2?",
        "Não encontrei o lembrete #3.",
        "Posso cancelar o lembrete #4 se quiser.",
        "O lembrete #2 foi criado?",
        # I-2: negação/futuro antes do substantivo ou fora da lacuna
        "Nenhum lembrete foi criado.",
        "Não há lembretes agendados para amanhã.",
        "Você não tem nenhum evento marcado hoje.",
        "Se o e-mail for enviado agora, chega antes das 9h.",
        "O lembrete fica agendado assim que você confirmar.",
        "Vou deixar o lembrete agendado para 15h, ok?",
        "O e-mail ficará salvo como rascunho.",
        # M-3: primeira pessoa negada
        "Nunca criei esse lembrete.",
        "Não, eu não salvei a memória.",
    ],
)
def test_claims_unexecuted_action_negatives(text):
    assert not claims_unexecuted_action(text)


def test_claims_unexecuted_action_ignores_ids_already_known():
    known = {("lembrete", 1), ("lembrete", 2)}
    assert not claims_unexecuted_action("Seu lembrete #1 foi criado para 15:11.", known)
    assert not claims_unexecuted_action("Lembrete #1: Alongar (sáb 15:11) e Lembrete #2: Café.", known)
    assert claims_unexecuted_action("Lembrete #3 criado: Alongar.", known)  # id novo
    assert claims_unexecuted_action("Lembrete #1 e lembrete #3 criados.", known)  # um dos ids é novo
    assert claims_unexecuted_action("Seu lembrete #1 foi criado para 15:11.")  # sem histórico
    assert not claims_unexecuted_action("Os lembretes #1 e #2 foram criados.", known)  # plural e id solto


def test_known_ids_are_keyed_by_noun_type():
    known = {("lembrete", 1)}
    assert claims_unexecuted_action("Nota #1 salva.", known)
    assert claims_unexecuted_action("E-mail #1 enviado.", known)
    assert not claims_unexecuted_action("LEMBRETES #1 criado.", known)
    assert not claims_unexecuted_action("Memória #4 salva.", {("memoria", 4)})  # acento normalizado


def test_known_action_ids_reads_tool_summaries_by_type(services):
    from nickel.core.agent import known_action_ids

    store = services.conversations
    store.add("assistant", "ok", channel="ui", attachments=[{"type": "tools", "items": [
        {"name": "reminder_create", "ok": True, "summary": "Lembrete #1: Alongar — sáb 15:11."},
        {"name": "reminder_list", "ok": True, "summary": "#2 Café — sáb 16:00; #3 Água — sáb 17:00"},
    ]}])
    store.add("user", "Lembrete #9 criado", channel="ui")  # mensagem do usuário não conta
    ids = known_action_ids(store.recent(10))
    assert ids == {("lembrete", 1), ("lembrete", 2), ("lembrete", 3)}


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


def _no_fake(services, reply):
    assert WARNING not in reply.text
    assert _fakes(services) == []


def test_recap_of_real_earlier_action_is_not_flagged(services, llm, registry):
    llm.queue(
        call("reminder_create", text="Alongar", when="2099-11-21T15:11:00-03:00"),
        say("Pronto."),
        say("Seu lembrete #1 foi criado para 15:11."),
    )
    agent = Agent(services, registry)
    first = run(agent.handle(Turn(channel="ui", text="me lembre de alongar às 15:11")))
    assert first.tools and first.tools[0]["summary"].startswith("Lembrete #1:")
    reply = run(agent.handle(Turn(channel="ui", text="qual lembrete você criou?")))
    assert reply.text == "Seu lembrete #1 foi criado para 15:11."
    assert len(llm.calls) == 3  # sem nova tentativa
    _no_fake(services, reply)


def test_listing_known_reminders_is_not_flagged(services, llm, registry):
    llm.queue(
        call("reminder_create", text="Alongar", when="2099-11-21T15:11:00-03:00"),
        call("reminder_create", text="Café", when="2099-11-21T16:00:00-03:00"),
        say("Pronto."),
        say("Lembrete #1: Alongar (sáb 15:11) e Lembrete #2: Café."),
    )
    agent = Agent(services, registry)
    run(agent.handle(Turn(channel="ui", text="me lembre de alongar e do café")))
    reply = run(agent.handle(Turn(channel="ui", text="quais são?")))
    assert reply.text == "Lembrete #1: Alongar (sáb 15:11) e Lembrete #2: Café."
    _no_fake(services, reply)


@pytest.mark.parametrize(
    "text",
    [
        "Quer que eu apague o lembrete #2?",
        "Não encontrei o lembrete #3.",
        "Nenhum lembrete foi criado.",
        "Não há lembretes agendados para amanhã.",
        "Você não tem nenhum evento marcado hoje.",
        "Se o e-mail for enviado agora, chega antes das 9h.",
        "O lembrete fica agendado assim que você confirmar.",
        "Vou deixar o lembrete agendado para 15h, ok?",
        "O e-mail ficará salvo como rascunho.",
    ],
)
def test_honest_or_question_replies_are_not_flagged(services, llm, registry, text):
    llm.queue(say(text))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="e aí?")))
    assert reply.text == text
    assert len(llm.calls) == 1
    _no_fake(services, reply)


def test_honest_reply_after_retry_has_no_warning(services, llm, registry):
    llm.queue(say("Lembrete #2 criado."), say("Nenhum lembrete foi criado. Quer que eu crie agora?"))
    reply = run(Agent(services, registry).handle(Turn(channel="ui", text="me lembre de alongar")))
    assert reply.text == "Nenhum lembrete foi criado. Quer que eu crie agora?"
    assert [e["detail"] for e in _fakes(services)] == [RETRY_DETAIL]  # só a nova tentativa, sem aviso
