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
        _spec("whatsapp", "Mensagens recebidas e respondidas pelo canal WhatsApp.", ("received", "replied", "error"), ("type", "id", "chars", "voice", "detail"), "nickel/channels/whatsapp.py"),
        _spec("outbound", "Envio de mensagens proativas por um canal.", ("ok", "undelivered"), ("text",), "nickel/core/outbound.py"),
        _spec("confirmation", "Ciclo de confirmação de ações sensíveis.", ("requested", "confirmed", "cancelled", "dropped"), ("id", "channel"), "nickel/core/agent.py"),
        _spec("tool", "Execução de ferramentas pelo agente.", ("start", "ok", "error"), ("arguments", "summary", "detail"), "nickel/core/agent.py"),
        _spec("llm", "Chamadas ao modelo de linguagem.", ("start", "done", "error"), ("step", "model", "backend", "requested_backend", "think", "duration_ms", "prompt_tokens", "completion_tokens", "tokens_per_second", "tool_calls", "detail"), "nickel/core/agent.py"),
        _spec("turn", "Ciclo completo de um turno de conversa.", ("start", "done", "error"), ("channel", "workspace", "chars", "duration_ms", "steps", "reply_chars", "detail"), "nickel/core/agent.py"),
        _spec("route", "Resolução da rota (workspace/skill) de um turno.", ("resolved",), ("command", "workspace", "switched", "auto"), "nickel/core/agent.py"),
        _spec("prompt", "Montagem do prompt enviado ao modelo.", ("built",), ("messages", "history", "tools", "system_chars", "est_tokens"), "nickel/core/agent.py"),
        _spec("reasoning", "Raciocínio do modelo (parcial e final) e o início da resposta.", ("progress", "answering", "final"), ("step", "chars", "tokens_est", "headline", "tail", "content_chars", "text", "conclusion", "tools_mentioned"), "nickel/core/reasoning.py"),
        _spec("voice", "Estados do pipeline de voz.", ("listening", "transcribing", "thinking", "speaking", "idle", "error"), ("chars", "detail"), "nickel/channels/voice.py"),
        _spec("tts", "Fala (síntese e reprodução) de uma resposta: GUI, voz, botão Ouvir e nota de voz do WhatsApp; `skipped` = nota de voz pulada porque já havia uma fala.", ("start", "done", "error", "skipped"), ("source", "chars", "provider", "voice", "interrupted", "detail"), "nickel/services.py"),
        _spec("system", "Ciclo de vida e saúde do sistema.", ("startup", "shutdown", "health"), ("version", "llm", "workspace_count", "whatsapp", "google", "spotify", "obsidian", "voice"), "nickel/app.py"),
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
    "transcribing": "Transcrevendo",
    "speaking": "Falando",
    "error": "Erro",
}

PHASES: dict[tuple[str, str], str] = {
    ("turn", "start"): "routing",
    ("route", "resolved"): "prompting",
    ("prompt", "built"): "thinking",
    ("llm", "start"): "thinking",
    ("reasoning", "progress"): "thinking",
    ("reasoning", "answering"): "answering",
    ("tool", "start"): "tool",
    ("tool", "ok"): "thinking",
    ("tool", "error"): "thinking",
    ("confirmation", "requested"): "confirming",
    ("turn", "done"): "idle",
    ("turn", "error"): "error",
    ("llm", "error"): "error",
    ("voice", "listening"): "listening",
    ("voice", "transcribing"): "transcribing",
    ("voice", "speaking"): "speaking",
    ("voice", "idle"): "idle",
    # A UI só aplica estas três se a fase permite (monitor-core.js `ttsMayChangePhase`):
    # a fala roda em segundo plano e pode cruzar o turno seguinte.
    ("tts", "start"): "speaking",
    ("tts", "done"): "idle",
    ("tts", "error"): "error",
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
    ("reasoning", "answering"),
    ("llm", "done"),
    ("turn", "done"),
)


def phase_for(kind: str, status: str) -> str | None:
    """Fase da interface para o par (kind, status), ou None se não muda a fase."""
    return PHASES.get((kind, status))
