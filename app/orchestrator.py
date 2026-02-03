from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrchestrationDecision:
    tool: str | None
    reason: str


def decide_tool(message: str) -> OrchestrationDecision:
    normalized = message.lower()
    if _mentions_email(normalized):
        if _mentions_send(normalized):
            return OrchestrationDecision(tool="email.send", reason="email_send_keyword")
        if _mentions_draft(normalized):
            return OrchestrationDecision(tool="email.draft", reason="email_draft_keyword")
        if _mentions_read(normalized):
            return OrchestrationDecision(tool="email.read", reason="email_read_keyword")
        if _mentions_search(normalized):
            return OrchestrationDecision(tool="email.search", reason="email_search_keyword")
    if _mentions_calendar(normalized):
        if _mentions_modify(normalized):
            return OrchestrationDecision(
                tool="calendar.modify_event", reason="calendar_modify_keyword"
            )
        if _mentions_create(normalized):
            return OrchestrationDecision(
                tool="calendar.create_event", reason="calendar_create_keyword"
            )
        if _mentions_list(normalized):
            return OrchestrationDecision(
                tool="calendar.list_events", reason="calendar_list_keyword"
            )
    if _mentions_notes(normalized):
        if _mentions_create(normalized):
            return OrchestrationDecision(tool="notes.create", reason="notes_create_keyword")
    if _mentions_tasks(normalized):
        if _mentions_create(normalized):
            return OrchestrationDecision(tool="tasks.create", reason="tasks_create_keyword")
        if _mentions_list(normalized):
            return OrchestrationDecision(tool="tasks.list", reason="tasks_list_keyword")
    if _mentions_spotify(normalized):
        if _mentions_pause(normalized):
            return OrchestrationDecision(tool="spotify.pause", reason="spotify_pause_keyword")
        if _mentions_skip(normalized):
            return OrchestrationDecision(tool="spotify.skip", reason="spotify_skip_keyword")
        if _mentions_play(normalized):
            return OrchestrationDecision(tool="spotify.play", reason="spotify_play_keyword")
    return OrchestrationDecision(tool=None, reason="no_tool_match")


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
