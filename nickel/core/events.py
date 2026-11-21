"""Catálogo de eventos de auditoria do NICKEL.

Fonte única de verdade para kinds, estados, fases da interface e o fluxo
esperado de um turno. A UI, a documentação gerada e o teste de completude
(tests/test_event_catalog.py) leem daqui.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventSpec:
    kind: str
    description: str
    statuses: tuple[str, ...]
    fields: tuple[str, ...]
    source: str


def _spec(kind: str, description: str, statuses: tuple[str, ...], fields: tuple[str, ...], source: str) -> tuple[str, EventSpec]:
    return kind, EventSpec(kind, description, statuses, fields, source)


CATALOG: dict[str, EventSpec] = dict(
    [
        _spec("oauth", "Conexão de contas externas via OAuth (Google, Spotify).", ("connected",), (), "nickel/app.py"),
        _spec("whatsapp", "Mensagens recebidas e respondidas pelo canal WhatsApp.", ("received", "replied", "error"), ("type", "id"), "nickel/channels/whatsapp.py"),
        _spec("outbound", "Envio de mensagens proativas por um canal.", ("ok", "undelivered"), ("text",), "nickel/core/outbound.py"),
        _spec("confirmation", "Ciclo de confirmação de ações sensíveis.", ("requested", "confirmed", "cancelled", "dropped"), ("id", "channel"), "nickel/core/agent.py"),
        _spec("tool", "Execução de ferramentas pelo agente.", ("start", "ok", "error"), ("args", "result", "detail"), "nickel/core/agent.py"),
        _spec("llm", "Chamadas ao modelo de linguagem.", ("start", "done", "error"), ("provider", "tokens", "detail"), "nickel/core/agent.py"),
        _spec("turn", "Ciclo completo de um turno de conversa.", ("start", "done", "error"), ("channel", "text", "detail"), "nickel/core/agent.py"),
        _spec("route", "Resolução da rota (workspace/skill) de um turno.", ("resolved",), ("workspace", "skill"), "nickel/core/agent.py"),
        _spec("prompt", "Montagem do prompt enviado ao modelo.", ("built",), ("chars", "sections"), "nickel/core/agent.py"),
        _spec("reasoning", "Raciocínio do modelo, parcial e final.", ("progress", "final"), ("text",), "nickel/core/reasoning.py"),
        _spec("voice", "Estados do pipeline de voz.", ("listening", "transcribing", "thinking", "speaking", "idle", "error"), ("detail",), "nickel/voice"),
        _spec("system", "Ciclo de vida e saúde do sistema.", ("startup", "shutdown", "health"), ("detail",), "nickel/app.py"),
    ]
)

PHASE_LABELS: dict[str, str] = {
    "idle": "Ocioso",
    "routing": "Roteando",
    "prompting": "Montando prompt",
    "thinking": "Pensando",
    "answering": "Respondendo",
    "tool": "Executando ferramenta",
    "confirming": "Aguardando confirmação",
    "listening": "Ouvindo",
    "speaking": "Falando",
    "error": "Erro",
}

PHASES: dict[tuple[str, str], str] = {
    ("turn", "start"): "routing",
    ("route", "resolved"): "prompting",
    ("prompt", "built"): "thinking",
    ("llm", "start"): "thinking",
    ("reasoning", "progress"): "thinking",
    ("llm", "done"): "answering",
    ("tool", "start"): "tool",
    ("tool", "ok"): "thinking",
    ("tool", "error"): "thinking",
    ("confirmation", "requested"): "confirming",
    ("turn", "done"): "idle",
    ("turn", "error"): "error",
    ("llm", "error"): "error",
    ("voice", "listening"): "listening",
    ("voice", "speaking"): "speaking",
    ("voice", "idle"): "idle",
}

TURN_FLOW: tuple[tuple[str, str], ...] = (
    ("turn", "start"),
    ("route", "resolved"),
    ("prompt", "built"),
    ("llm", "start"),
    ("reasoning", "final"),
    ("llm", "done"),
    ("tool", "start"),
    ("tool", "ok"),
    ("llm", "start"),
    ("llm", "done"),
    ("turn", "done"),
)


def phase_for(kind: str, status: str) -> str | None:
    """Fase da interface para o par (kind, status), ou None se não muda a fase."""
    return PHASES.get((kind, status))
