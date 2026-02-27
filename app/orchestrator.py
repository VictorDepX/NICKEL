from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrchestrationDecision:
    tool: str | None
    reason: str
    confidence: float


_HIGH_CONFIDENCE_THRESHOLD = 0.75


def is_high_confidence(decision: OrchestrationDecision) -> bool:
    return decision.confidence >= _HIGH_CONFIDENCE_THRESHOLD


def decide_tool(message: str) -> OrchestrationDecision:
    normalized = message.lower()
    matched_tools: list[tuple[str, str, float]] = []

    if _mentions_email(normalized):
        if _mentions_send(normalized):
            matched_tools.append(("email.send", "email_send_keyword", 0.85))
        if _mentions_draft(normalized):
            matched_tools.append(("email.draft", "email_draft_keyword", 0.85))
        if _mentions_read(normalized):
            matched_tools.append(("email.read", "email_read_keyword", 0.8))
        if _mentions_search(normalized):
            matched_tools.append(("email.search", "email_search_keyword", 0.8))
    if _mentions_calendar(normalized):
        if _mentions_modify(normalized):
            matched_tools.append(("calendar.modify_event", "calendar_modify_keyword", 0.85))
        if _mentions_create(normalized):
            matched_tools.append(("calendar.create_event", "calendar_create_keyword", 0.85))
        if _mentions_list(normalized):
            matched_tools.append(("calendar.list_events", "calendar_list_keyword", 0.8))
    if _mentions_notes(normalized):
        if _mentions_create(normalized):
            matched_tools.append(("notes.create", "notes_create_keyword", 0.8))
    if _mentions_tasks(normalized):
        if _mentions_create(normalized):
            matched_tools.append(("tasks.create", "tasks_create_keyword", 0.8))
        if _mentions_list(normalized):
            matched_tools.append(("tasks.list", "tasks_list_keyword", 0.75))
    if _mentions_spotify(normalized):
        if _mentions_pause(normalized):
            matched_tools.append(("spotify.pause", "spotify_pause_keyword", 0.85))
        if _mentions_skip(normalized):
            matched_tools.append(("spotify.skip", "spotify_skip_keyword", 0.85))
        if _mentions_play(normalized):
            matched_tools.append(("spotify.play", "spotify_play_keyword", 0.85))

    if not matched_tools:
        return OrchestrationDecision(tool=None, reason="no_tool_match", confidence=0.0)

    if len(matched_tools) > 1:
        tools = ",".join(tool for tool, _, _ in matched_tools)
        return OrchestrationDecision(
            tool=None,
            reason=f"ambiguous_tool_match:{tools}",
            confidence=0.45,
        )

    tool, reason, confidence = matched_tools[0]
    return OrchestrationDecision(tool=tool, reason=reason, confidence=confidence)


def _mentions_email(text: str) -> bool:
    return any(keyword in text for keyword in ("email", "e-mail", "gmail", "mensagem"))


def _mentions_search(text: str) -> bool:
    return any(keyword in text for keyword in ("buscar", "procurar", "pesquisar", "encontr"))


def _mentions_draft(text: str) -> bool:
    return any(keyword in text for keyword in ("rascunho", "draft", "esboço"))


def _mentions_send(text: str) -> bool:
    return any(keyword in text for keyword in ("enviar", "mande", "dispare", "envie"))


def _mentions_read(text: str) -> bool:
    return any(keyword in text for keyword in ("ler", "abrir", "mostrar", "ver"))


def _mentions_calendar(text: str) -> bool:
    return any(keyword in text for keyword in ("agenda", "calendario", "calendário"))


def _mentions_list(text: str) -> bool:
    return any(keyword in text for keyword in ("listar", "mostrar", "ver", "próxim"))


def _mentions_create(text: str) -> bool:
    return any(keyword in text for keyword in ("criar", "agendar", "marcar"))


def _mentions_modify(text: str) -> bool:
    return any(keyword in text for keyword in ("alterar", "mudar", "remarcar", "editar"))


def _mentions_notes(text: str) -> bool:
    return any(keyword in text for keyword in ("nota", "notas", "anotação", "anotacoes"))


def _mentions_tasks(text: str) -> bool:
    return any(keyword in text for keyword in ("tarefa", "tarefas", "to-do", "todo"))


def _mentions_spotify(text: str) -> bool:
    return any(keyword in text for keyword in ("spotify", "música", "musica", "som"))


def _mentions_play(text: str) -> bool:
    return any(keyword in text for keyword in ("tocar", "play", "reproduzir", "iniciar"))


def _mentions_pause(text: str) -> bool:
    return any(keyword in text for keyword in ("pausar", "pause", "parar"))


def _mentions_skip(text: str) -> bool:
    return any(keyword in text for keyword in ("pular", "próxima", "proxima", "skip"))
