"""Testes de completude do catálogo de eventos de auditoria."""
from __future__ import annotations

import ast
from pathlib import Path

from nickel.core.events import CATALOG, PHASE_LABELS, PHASES, TURN_FLOW, phase_for

ROOT = Path(__file__).resolve().parent.parent / "nickel"


def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _receiver_ends_in_audit(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "audit"
    if isinstance(node, ast.Name):
        return node.id == "audit"
    return False


def _calls(method: str, audit_only: bool):
    """Gera (arquivo, linha, kind, status) de cada chamada `X.method(...)`."""
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != method:
                continue
            if audit_only and not _receiver_ends_in_audit(node.func.value):
                continue
            args = node.args
            kind = _literal(args[0]) if len(args) > 0 else None
            status = _literal(args[2]) if len(args) > 2 else None
            yield path.relative_to(ROOT.parent), node.lineno, kind, status


def test_phase_for_known_and_unknown():
    assert phase_for("llm", "start") == "thinking"
    assert phase_for("oauth", "connected") is None


def test_every_phase_value_has_a_label():
    assert set(PHASES.values()) <= set(PHASE_LABELS)
    assert set(PHASE_LABELS) == {
        "idle", "routing", "prompting", "thinking", "answering",
        "tool", "confirming", "listening", "speaking", "error",
    }
    for kind, status in list(PHASES) + list(TURN_FLOW):
        assert kind in CATALOG and status in CATALOG[kind].statuses


def test_all_record_calls_use_cataloged_kind_and_status():
    errors = []
    for path, line, kind, status in _calls("record", audit_only=True):
        if kind is None:
            continue
        if kind not in CATALOG:
            errors.append(f"{path}:{line} kind desconhecido: {kind!r}")
        elif status is not None and status not in CATALOG[kind].statuses:
            errors.append(f"{path}:{line} status {status!r} fora do catálogo de {kind!r}")
    assert not errors, "\n".join(errors)


def test_every_cataloged_kind_is_emitted_somewhere():
    emitted = {k for _, _, k, _ in _calls("record", True) if k}
    emitted |= {k for _, _, k, _ in _calls("emit", False) if k}
    missing = sorted(set(CATALOG) - emitted)
    assert not missing, f"kinds nunca emitidos: {missing}"


def test_answering_phase_comes_from_a_real_event():
    assert "answering" in CATALOG["reasoning"].statuses
    assert phase_for("reasoning", "answering") == "answering"
    assert phase_for("llm", "done") is None


# ---------------------------------------------------------------- campos reais


def _coverage_registry():
    from typing import Any

    from nickel.core.skills import ToolContext, ToolRegistry, ToolResult

    registry = ToolRegistry()

    @registry.add("echo", "Repete", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
    async def echo(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(True, f"eco: {args['text']}")

    @registry.add("quebra", "Falha", {"type": "object", "properties": {}})
    async def quebra(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        raise RuntimeError("falhou")

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


def test_every_recorded_detail_key_is_in_the_catalog(services, settings):
    from fastapi.testclient import TestClient

    from conftest import StreamingFakeLLM, call, run, say
    from nickel.app import create_app
    from nickel.channels.whatsapp import WhatsAppChannel
    from nickel.core.agent import Agent, Turn
    from nickel.core.llm import LLMError
    from test_system_events import FakeSTT, FakeTTS, _voice

    # O `reasoning/progress` sai do banco quando chega o `final`: captura o que foi gravado, como a UI ao vivo vê.
    recorded: list[dict] = []
    original = services.audit.record

    def capture(*args, **kwargs):
        event = original(*args, **kwargs)
        recorded.append(event)
        return event

    services.audit.record = capture

    deltas = [("reasoning", "Penso no pedido. Vou usar echo."), ("content", "Pronto.")]
    services.llm = StreamingFakeLLM(
        [
            call("echo", text="a"), say("Pronto."),  # streaming + raciocínio + ferramenta
            call("quebra"), say("Falhou."),  # ferramenta com erro
            call("send", to="ana"),  # confirmação pedida (depois confirmada pela API)
            call("send", to="bia"),  # confirmação pedida (depois cancelada com "não")
            call("send", to="cia"), say("Outra coisa."),  # confirmação descartada por mensagem nova
            say("Feito.\n[ações executadas: echo: x]"),  # marcador inventado
        ],
        deltas=deltas,
    )
    agent = Agent(services, _coverage_registry())

    async def turns():
        await agent.handle(Turn(channel="ui", text="repete a"))
        await agent.handle(Turn(channel="ui", text="quebra"))
        first = await agent.handle(Turn(channel="ui", text="manda pra ana"))
        await agent.confirm(first.pending_action_id, "ui")
        await agent.handle(Turn(channel="ui", text="manda pra bia"))
        await agent.handle(Turn(channel="ui", text="não"))
        await agent.handle(Turn(channel="ui", text="manda pra cia"))
        await agent.handle(Turn(channel="ui", text="esquece, outra coisa"))
        await agent.handle(Turn(channel="ui", text="anota"))

    run(turns())

    class Broken:
        async def chat(self, *args, **kwargs):
            raise LLMError("fora do ar")

    services.llm = Broken()
    run(agent.handle(Turn(channel="ui", text="oi")))

    services.llm = StreamingFakeLLM([say("Olá!"), say("Recebido.")], deltas=deltas)
    run(_voice(services, services.llm, tts=FakeTTS())._session())
    run(_voice(services, services.llm, stt=FakeSTT(fail=True))._session())
    whatsapp = WhatsAppChannel(services, Agent(services, _coverage_registry()))
    run(whatsapp.handle_inbound({"id": "w1", "type": "chat", "body": "oi"}))

    async def boom(payload):
        raise RuntimeError("falhou geral")

    whatsapp.build_turn = boom
    run(whatsapp.handle_inbound({"id": "w2", "type": "chat", "body": "x"}))
    run(services.outbound.notify("Beber água", channel="lembrete"))

    services.llm = StreamingFakeLLM()
    with TestClient(create_app(services=services, registry=_coverage_registry(), background=False)):
        import time

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not [
            e for e in recorded if (e["kind"], e["status"]) == ("system", "health")
        ]:
            time.sleep(0.01)

    events = recorded
    seen = {(e["kind"], e["status"]) for e in events}
    for expected in [
        ("reasoning", "progress"), ("reasoning", "answering"), ("reasoning", "final"),
        ("tool", "ok"), ("tool", "error"), ("llm", "error"), ("turn", "error"),
        ("confirmation", "requested"), ("confirmation", "confirmed"),
        ("confirmation", "cancelled"), ("confirmation", "dropped"),
        ("voice", "thinking"), ("voice", "error"), ("whatsapp", "replied"), ("whatsapp", "error"),
        ("outbound", "ok"), ("system", "startup"), ("system", "health"), ("system", "shutdown"),
    ]:
        assert expected in seen, expected
    assert any(e["name"] == "<fake>" for e in events)

    errors = []
    for e in events:
        extra = set(e["detail"]) - set(CATALOG[e["kind"]].fields)
        if extra:
            errors.append(f"{e['kind']}/{e['status']} ({e['name']}): {sorted(extra)}")
    assert not errors, "\n".join(sorted(set(errors)))
