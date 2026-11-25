"""Loop do agente: histórico + tools nativas + confirmações."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nickel.core.llm import LLMError
from nickel.core.persona import build_system_prompt, now_stamp
from nickel.core.reasoning import ReasoningTracker
from nickel.core.skills import ToolContext, ToolRegistry, ToolResult, validate_arguments
from nickel.core.stores import PendingAction, StoredMessage
from nickel.core.trace import current_run_id, new_run_id, run_scope
from nickel.core.workspaces import Resolution, Workspace

if TYPE_CHECKING:  # pragma: no cover
    from nickel.services import Services

log = logging.getLogger(__name__)

_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "tokens_per_second")

_YES = {
    "sim", "s", "confirmo", "confirma", "confirmado", "pode", "ok", "okay", "manda", "envia", "faz",
    "isso", "claro", "yes", "y", "positivo", "beleza", "blz", "bora", "certo", "fechado", "vai",
    "mandar", "enviar", "fazer", "ser",
}
_NO = {"nao", "n", "cancela", "cancelar", "cancelado", "deixa", "esquece", "no", "negativo", "para", "nem"}
_FILLER = {"pode", "por", "favor", "pfv", "pf", "e", "isso", "mesmo", "precisa", "agora", "ai", "la"}

# Marcador textual que versões antigas punham no histórico; o modelo aprendeu a imitá-lo sem chamar a tool.
# Singular ou plural, com ou sem `**` em volta. O fim é o último `]` da linha em que o marcador fecha
# (o resumo pode ter `]` dentro); sem `]`, vai até o fim do texto.
_FAKE_ACTION_MARKER = re.compile(
    r"[ \t]*\n?[ \t]*(?:\*\*)?\[\s*a[çc](?:[õo]es|[ãa]o)\s+executadas?\s*:"
    r"(?:(?:[^\]\n]*\n)*?[^\n]*\](?:\*\*)?|[\s\S]*\Z)",
    re.IGNORECASE,
)
_FAKE_ACTION_WARNING = "(Atenção: nenhuma ação foi executada.)"
_FAKE_ACTION_RETRY = (
    "Sistema: sua última resposta afirmou uma ação, mas nenhuma ferramenta foi chamada e nada foi executado. "
    "Se a ação é necessária, chame a ferramenta agora. Se não, responda sem afirmar que fez algo."
)

# Afirmação de ação concluída sem marcador (ex.: "Lembrete #2 criado: Alongar."). Padrão PT-BR estrito,
# oração a oração: substantivo de recurso + particípio em até 60 caracteres, ou o id `#N` do resumo de tool,
# ou a primeira pessoa no passado. Não contam: perguntas, orações com negação, futuro, condicional ou modal
# ("Nenhum lembrete foi criado.", "O lembrete será criado…", "Se o e-mail for enviado…") e orações cujos
# `#N` já apareceram, do mesmo tipo, em resumos de tools do histórico (recapitulação de ação real).
_RESOURCE = r"(?:lembretes?|mem[óo]rias?|prefer[êe]ncias?|notas?|eventos?|e-?mails?|mensage(?:m|ns)|compromissos?|tarefas?)"
_PARTICIPLE = r"(?:criad|salv|agendad|enviad|cancelad|apagad|removid|registrad|anotad|marcad)[oa]s?"
_CLAIM_RE = re.compile(
    rf"\b{_RESOURCE}\b(?:\s*#\d+|[^.!?\n]{{0,60}}?\b{_PARTICIPLE}\b)"
    r"|\b(?:criei|salvei|agendei|enviei|cancelei|apaguei|removi|anotei|marquei|registrei)\b",
    re.IGNORECASE,
)
_NOT_DONE_RE = re.compile(
    r"\b(?:n[ãa]o|nunca|nenhum|nenhuma|ser|ser[áa]|ser[ãa]o|seria|seriam|vai|v[ãa]o|vou|pode|podem|posso|"
    r"quer|deseja|h[áa]|tem|for|fica|ficar[áa]|estar[áa]|se)\b",
    re.IGNORECASE,
)
_IDIOMS_RE = re.compile(r"\bpode deixar\b", re.IGNORECASE)  # "pode deixar" confirma, não é modal
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
# Orações: , ; : — (um "e"/"mas"/"porém" depois da vírgula fica no começo da oração seguinte).
_CLAUSE_SPLIT = re.compile(r"\s*[,;:—]\s*")
_ID_RE = re.compile(rf"(?:\b({_RESOURCE})\s*)?#(\d+)", re.IGNORECASE)
# Tools cujos resumos citam `#N` sem o substantivo (ex.: reminder_list: "#2 Café — …").
_TOOL_NOUN = {"reminder": "lembrete", "notes": "nota", "memory": "memoria", "email": "email", "calendar": "evento"}


def _noun_key(noun: str) -> str:
    """'Lembretes' → 'lembrete', 'Memória' → 'memoria', 'E-mails' → 'email', 'mensagens' → 'mensagem'."""
    key = unicodedata.normalize("NFKD", noun.lower())
    key = "".join(ch for ch in key if not unicodedata.combining(ch)).replace("-", "")
    if key.endswith("ns"):
        return key[:-2] + "m"
    return key[:-1] if key.endswith("s") else key


def _cited_ids(text: str, default: str | None = None) -> set[tuple[str | None, int]]:
    return {(_noun_key(noun) if noun else default, int(n)) for noun, n in _ID_RE.findall(text)}


def known_action_ids(history: list[StoredMessage]) -> set[tuple[str, int]]:
    """Pares (tipo, id) citados nos resumos das tools que rodaram de fato em turnos anteriores."""
    ids: set[tuple[str, int]] = set()
    for item in history:
        if item.role != "assistant":
            continue
        for attachment in item.attachments:
            if attachment.get("type") != "tools":
                continue
            for action in attachment.get("items") or []:
                default = _TOOL_NOUN.get(str(action.get("name") or "").split("_", 1)[0])
                cited = _cited_ids(str(action.get("summary") or ""), default)
                ids.update((noun, n) for noun, n in cited if noun)
    return ids


def _all_known(cited: set[tuple[str | None, int]], known: set[tuple[str, int]] | frozenset) -> bool:
    known_numbers = {n for _, n in known}
    return all((noun, n) in known if noun else n in known_numbers for noun, n in cited)


def claims_unexecuted_action(
    text: str, known_ids: set[tuple[str, int]] | frozenset[tuple[str, int]] = frozenset()
) -> bool:
    """Verdadeiro quando alguma oração afirma uma ação concluída (usado só quando nenhuma tool rodou)."""
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        sentence = sentence.strip()
        if not sentence or sentence.endswith("?"):
            continue
        for clause in _CLAUSE_SPLIT.split(sentence):
            if not _CLAIM_RE.search(clause) or _NOT_DONE_RE.search(_IDIOMS_RE.sub(" ", clause)):
                continue
            cited = _cited_ids(clause)
            if cited and _all_known(cited, known_ids):
                continue
            return True
    return False


def strip_fake_action_marker(text: str) -> str:
    """Remove blocos `[ações executadas: …]`/`[ação executada: …]` (mesmo em várias linhas) do texto."""
    if not _FAKE_ACTION_MARKER.search(text):
        return text
    return _FAKE_ACTION_MARKER.sub("", text).strip()


def classify_confirmation(text: str) -> str | None:
    """Devolve 'yes', 'no' ou None (mensagem não é uma confirmação)."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    tokens = re.findall(r"[a-z]+", normalized)
    if not tokens or len(tokens) > 5:
        return None
    token_set = set(tokens)
    if token_set & _NO and token_set <= (_NO | _FILLER):
        return "no"
    if token_set <= _YES | _FILLER and token_set & _YES:
        return "yes"
    return None


@dataclass
class Turn:
    channel: str
    text: str
    llm_text: str | None = None
    images: list[str] = field(default_factory=list)  # base64, só do turno atual
    attachments: list[dict[str, Any]] = field(default_factory=list)
    last_audio_path: Path | None = None
    think: bool | None = None  # sobrescreve `think` nas opções do LLM quando definido


def stable_window(recent: list[Any], total: int, limit: int) -> list[Any]:
    """Corta o histórico em degraus em vez de deslizar 1 mensagem por turno.

    Com janela deslizante, o início do histórico muda a cada turno e o llama-server relê
    tudo depois do system prompt. Com degraus de `limit // 2` (par, para começar no usuário),
    o prefixo fica igual por vários turnos e o cache de prompt é reaproveitado.
    O tamanho fica entre `limit - step` e `limit`.
    """
    if total <= limit or limit < 4:
        return recent
    step = max(2, (limit // 2) // 2 * 2)
    start = -(-(total - limit) // step) * step  # arredonda para cima
    first = total - len(recent)
    return recent[max(0, start - first):]


def history_transcript(past: list[dict[str, Any]], current_text: str) -> str:
    """Histórico em texto corrido + mensagem atual; ações passadas viram linhas com o resultado real."""
    lines: list[str] = []
    for message in past:
        role = message.get("role")
        if role == "tool":
            lines.append(f"[resultado de {message.get('tool_name', 'ferramenta')}: {message.get('content', '')}]")
        elif role == "assistant" and message.get("tool_calls"):
            for call in message["tool_calls"]:
                fn = call.get("function", {})
                args = json.dumps(fn.get("arguments") or {}, ensure_ascii=False)
                lines.append(f"[NICKEL executou {fn.get('name', '')} {args} (id {call.get('id', '')})]")
        elif message.get("content"):
            speaker = "Usuário" if role == "user" else "NICKEL"
            lines.append(f"{speaker}: {message['content']}")
    return "Conversa anterior (só contexto):\n" + "\n".join(lines) + "\n\nMensagem atual:\n" + current_text


@dataclass
class AgentReply:
    text: str
    pending_action_id: str | None = None
    links: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _TurnStats:
    """Contadores de um turno, preenchidos pelo laço e lidos ao fechar o turno."""

    steps: int = 0
    error: str | None = None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class Agent:
    def __init__(self, services: "Services", registry: ToolRegistry) -> None:
        self.services = services
        self.registry = registry
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- entrada
    async def handle(self, turn: Turn) -> AgentReply:
        async with self._lock:
            return await self._traced(turn.channel, len(turn.text), lambda stats: self._handle(turn, stats))

    async def confirm(self, action_id: str, channel: str = "ui") -> AgentReply:
        async with self._lock:
            return await self._traced(channel, 0, lambda stats: self._confirm(action_id, channel))

    async def cancel(self, action_id: str, channel: str = "ui") -> AgentReply:
        async with self._lock:
            return await self._traced(channel, 0, lambda stats: self._cancel(action_id, channel))

    async def _handle(self, turn: Turn, stats: _TurnStats) -> AgentReply:
        route = self.services.workspaces.resolve(turn.text)
        workspace = route.workspace
        self.services.audit.record(
            "route",
            workspace.id,
            "resolved",
            {"command": route.command, "workspace": workspace.id, "switched": route.switched, "auto": route.auto},
        )
        if route.command_only:
            if route.switched:
                self._drop_pending(channel=turn.channel)
            return AgentReply(text=self._command_text(route))
        if route.command == "switch":
            llm_text = route.text if turn.llm_text in (None, turn.text) else turn.llm_text
            turn = replace(turn, text=route.text, llm_text=None if turn.llm_text is None else llm_text)
        if route.switched:
            self._drop_pending(channel=turn.channel)

        store = self.services.conversations
        conversation = workspace.conversation
        limit = workspace.history or self.services.settings.agent_history_messages
        history = stable_window(store.recent(limit, conversation), store.count(conversation), limit)
        store.add(
            "user",
            turn.llm_text or turn.text,
            channel=turn.channel,
            attachments=turn.attachments,
            conversation=conversation,
        )

        pending = self.services.pending.current()
        if pending:
            decision = classify_confirmation(turn.text)
            if decision == "yes":
                reply = await self._execute_pending(pending, turn.channel, workspace)
                return self._finish(reply, turn.channel, workspace)
            if decision == "no":
                self.services.pending.resolve(pending.id, "cancelled")
                self.services.audit.record("confirmation", pending.tool, "cancelled", {"id": pending.id})
                return self._finish(AgentReply(text="Cancelado."), turn.channel, workspace)
            # Mensagem nova não é consentimento: a ação pendente cai.
            self.services.pending.resolve(pending.id, "dropped")
            self.services.audit.record("confirmation", pending.tool, "dropped", {"id": pending.id})

        reply = await self._run_llm(turn, history, workspace, stats)
        if route.auto:
            reply.text = f"↪ {workspace.name}\n{reply.text}"
        return self._finish(reply, turn.channel, workspace)

    async def _confirm(self, action_id: str, channel: str) -> AgentReply:
        pending = self.services.pending.get(action_id)
        if not pending or pending.status != "pending":
            return AgentReply(text="Essa ação não está mais pendente.")
        workspace = self.services.workspaces.active()
        reply = await self._execute_pending(pending, channel, workspace)
        return self._finish(reply, channel, workspace)

    async def _cancel(self, action_id: str, channel: str) -> AgentReply:
        pending = self.services.pending.get(action_id)
        if not pending or pending.status != "pending":
            return AgentReply(text="Essa ação não está mais pendente.")
        self.services.pending.resolve(action_id, "cancelled")
        self.services.audit.record("confirmation", pending.tool, "cancelled", {"id": action_id})
        return self._finish(
            AgentReply(text=f"Cancelado: {pending.summary}."), channel, self.services.workspaces.active()
        )

    # ---------------------------------------------------------------- internos
    async def _traced(
        self, channel: str, chars: int, body: Callable[[_TurnStats], Awaitable[AgentReply]]
    ) -> AgentReply:
        """Roda um turno num `run_scope` (reaproveita o do chamador, se houver), entre `turn/start` e `turn/done` (ou `turn/error`)."""
        audit = self.services.audit
        stats = _TurnStats()
        with run_scope(current_run_id.get() or new_run_id()):
            started = time.monotonic()
            audit.record(
                "turn",
                channel,
                "start",
                {"channel": channel, "workspace": self.services.workspaces.active().id, "chars": chars},
            )
            try:
                reply = await body(stats)
            except asyncio.CancelledError:  # turno cancelado: fecha a fase na UI e propaga
                audit.record("turn", channel, "error", {"detail": "cancelado"}, duration_ms=_elapsed_ms(started))
                raise
            except Exception as exc:
                audit.record("turn", channel, "error", {"detail": str(exc)}, duration_ms=_elapsed_ms(started))
                raise
            elapsed = _elapsed_ms(started)
            if stats.error is not None:
                audit.record("turn", channel, "error", {"detail": stats.error}, duration_ms=elapsed)
            else:
                audit.record(
                    "turn",
                    channel,
                    "done",
                    {"duration_ms": elapsed, "steps": stats.steps, "reply_chars": len(reply.text)},
                    duration_ms=elapsed,
                )
            return reply

    def _command_text(self, route: Resolution) -> str:
        manager = self.services.workspaces
        if route.command == "list":
            return manager.describe()
        if route.command == "unknown":
            return f"Não existe o workspace '{route.target}'.\n{manager.describe()}"
        description = f" {route.workspace.description}" if route.workspace.description else ""
        return f"Workspace ativo: {route.workspace.name}.{description}"

    def _drop_pending(self, *, channel: str) -> None:
        pending = self.services.pending.current()
        if pending:
            self.services.pending.resolve(pending.id, "dropped")
            self.services.audit.record("confirmation", pending.tool, "dropped", {"id": pending.id, "channel": channel})

    def _finish(self, reply: AgentReply, channel: str, workspace: Workspace) -> AgentReply:
        attachments: list[dict[str, Any]] = []
        if reply.tools:
            attachments.append({"type": "tools", "items": reply.tools})
        if reply.pending_action_id:
            attachments.append({"type": "pending", "id": reply.pending_action_id})
        self.services.conversations.add(
            "assistant", reply.text, channel=channel, attachments=attachments, conversation=workspace.conversation
        )
        return reply

    def _context(
        self, channel: str, user_text: str, audio: Path | None = None, workspace: Workspace | None = None
    ) -> ToolContext:
        return ToolContext(
            channel=channel,
            user_text=user_text,
            services=self.services,
            last_audio_path=audio,
            workspace=workspace,
        )

    async def _run_tool(self, name: str, ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult.fail(f"Tool desconhecida: {name}")
        self.services.audit.record("tool", name, "start", {"arguments": arguments})
        started = time.monotonic()
        try:
            result = await tool.handler(ctx, arguments)
        except Exception as exc:  # a falha da tool vira resultado, não derruba o turno
            log.exception("Tool %s falhou", name)
            result = ToolResult.fail(f"{name} falhou: {exc}")
        self.services.audit.record(
            "tool",
            name,
            "ok" if result.ok else "error",
            {"arguments": arguments, "summary": result.summary},
            duration_ms=_elapsed_ms(started),
        )
        return result

    async def _execute_pending(self, pending: PendingAction, channel: str, workspace: Workspace) -> AgentReply:
        ctx = self._context(channel, "", workspace=workspace)
        result = await self._run_tool(pending.tool, ctx, pending.arguments)
        self.services.pending.resolve(pending.id, "confirmed" if result.ok else "failed", result.data)
        self.services.audit.record("confirmation", pending.tool, "confirmed", {"id": pending.id})
        return AgentReply(
            text=result.summary,
            links=ctx.links,
            tools=[
                {
                    "name": pending.tool,
                    "ok": result.ok,
                    "summary": result.summary,
                    "arguments": pending.arguments,
                    "id": f"pending-{pending.id}",
                }
            ],
        )

    def _history_messages(self, history: list[StoredMessage]) -> list[dict[str, Any]]:
        """Histórico para o LLM; ações passadas voltam como tool calls reais, nunca como texto."""
        messages: list[dict[str, Any]] = []
        for item in history:
            if item.role not in {"user", "assistant"}:
                continue
            content = item.content
            actions: list[dict[str, Any]] = []
            for attachment in item.attachments:
                if attachment.get("type") == "image":
                    content = f"[imagem enviada] {content}".strip()
                elif attachment.get("type") == "tools":
                    actions.extend(attachment.get("items") or [])
            if item.role == "assistant":
                content = strip_fake_action_marker(content)
                if actions:
                    messages.extend(self._replayed_actions(item.id, actions))
            messages.append({"role": item.role, "content": content})
        return messages

    @staticmethod
    def _replayed_actions(message_id: int, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mesma forma que `_run_llm` monta dentro do turno: assistant com `tool_calls` e um `tool` por ação."""
        calls: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for index, action in enumerate(actions):
            name = action.get("name", "")
            arguments = action.get("arguments")
            call_id = action.get("id") or f"hist-{message_id}-{index}"
            calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments if isinstance(arguments, dict) else {}},
                }
            )
            prefix = "ok: " if action.get("ok") else "erro: "
            results.append(
                {"role": "tool", "tool_call_id": call_id, "tool_name": name, "content": prefix + action.get("summary", "")}
            )
        return [{"role": "assistant", "content": "", "tool_calls": calls}, *results]

    async def _run_llm(
        self, turn: Turn, history: list[StoredMessage], workspace: Workspace, stats: _TurnStats
    ) -> AgentReply:
        settings = self.services.settings
        system = build_system_prompt(
            channel=turn.channel,
            timezone=settings.timezone,
            memory=self.services.memory.all(),
            workspace=workspace,
        )
        user_text = turn.llm_text or turn.text
        current: dict[str, Any] = {"role": "user", "content": f"{now_stamp(settings.timezone)}\n{user_text}"}
        if turn.images:
            current["images"] = turn.images
        past = self._history_messages(history)
        options = workspace.llm_options()
        if turn.think is not None:
            options["think"] = turn.think
        # O mesmo valor que os clientes mandam ao servidor (`options.get("think", settings.llm_think)`).
        think = options.get("think", settings.llm_think)
        if think and past:
            # Com o histórico em turnos, o Gemma 4 imita as respostas antigas (que chegam sem
            # pensamento) e deixa de pensar; como transcrição na mensagem atual, ele pensa.
            current = {**current, "content": history_transcript(past, current["content"])}
            past = []
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *past, current]
        tools = self.registry.schemas(self.services, workspace)
        tool_names = [t.get("function", {}).get("name", "") for t in tools or []]
        chars = sum(len(m.get("content") or "") for m in messages)
        self.services.audit.record(
            "prompt",
            workspace.id,
            "built",
            {
                "messages": len(messages),
                "history": len(past),
                "tools": len(tool_names),
                "system_chars": len(system),
                "est_tokens": math.ceil(chars / 4),
            },
        )
        ctx = self._context(turn.channel, turn.text, turn.last_audio_path, workspace)
        executed: list[dict[str, Any]] = []
        llm = self.services.llm_for(workspace)
        cloud = self.services.llm_cloud is not None and llm is self.services.llm_cloud
        model = (settings.llm_cloud_model or settings.llm_model) if cloud else settings.llm_model
        backend = "cloud" if cloud else "local"
        stream = bool(getattr(llm, "supports_stream", False) and settings.llm_stream)
        extra: dict[str, Any] = {"options": options} if options else {}
        known_ids = known_action_ids(history)
        retried = False

        for step in range(settings.agent_max_steps):
            stats.steps = step + 1
            self.services.audit.record(
                "llm",
                model,
                "start",
                {
                    "step": step,
                    "model": model,
                    "backend": backend,
                    "requested_backend": workspace.backend,
                    "think": think,
                },
            )
            tracker = ReasoningTracker(self.services.audit, step=step, tool_names=tool_names) if stream else None
            call_extra = {**extra, "on_delta": tracker.feed} if tracker is not None else extra
            started = time.monotonic()
            try:
                try:
                    reply = await llm.chat(messages, tools, **call_extra)
                finally:  # o raciocínio parcial fecha também quando a chamada falha
                    if tracker is not None:
                        tracker.finish()
            except LLMError as exc:
                self.services.audit.record(
                    "llm", model, "error", {"step": step, "detail": str(exc)}, duration_ms=_elapsed_ms(started)
                )
                stats.error = str(exc)
                return AgentReply(text=f"O modelo local não respondeu ({exc}).", tools=executed, links=ctx.links)
            except Exception as exc:  # erro inesperado: fecha o llm/start antes de propagar
                self.services.audit.record(
                    "llm", model, "error", {"step": step, "detail": str(exc)}, duration_ms=_elapsed_ms(started)
                )
                raise
            elapsed = _elapsed_ms(started)
            done: dict[str, Any] = {"step": step, "duration_ms": elapsed}
            done.update({key: reply.usage[key] for key in _USAGE_KEYS if key in reply.usage})
            done["tool_calls"] = [c.name for c in reply.tool_calls]
            self.services.audit.record("llm", model, "done", done, duration_ms=elapsed)

            if not reply.tool_calls:
                fallback = "Feito." if executed else "Sem resposta do modelo."
                text = reply.content or fallback
                cleaned = strip_fake_action_marker(text)
                faked = not executed and (cleaned != text or claims_unexecuted_action(cleaned, known_ids))
                if faked and not retried and step + 1 < settings.agent_max_steps:
                    # Uma nova tentativa por turno; o pedido não vai para o histórico gravado.
                    retried = True
                    self.services.audit.record(
                        "tool",
                        "<fake>",
                        "error",
                        {"detail": "modelo afirmou ação sem chamar a ferramenta; pedindo nova tentativa"},
                    )
                    messages.append({"role": "assistant", "content": cleaned})
                    messages.append({"role": "user", "content": _FAKE_ACTION_RETRY})
                    continue
                if faked:  # afirmou ação sem chamar a tool, e persistiu
                    self.services.audit.record(
                        "tool", "<fake>", "error", {"detail": "modelo afirmou ação sem chamar a ferramenta"}
                    )
                    cleaned = f"{cleaned}\n{_FAKE_ACTION_WARNING}" if cleaned else _FAKE_ACTION_WARNING
                return AgentReply(text=cleaned or fallback, tools=executed, links=ctx.links)

            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [
                        {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                        for call in reply.tool_calls
                    ],
                }
            )
            for call in reply.tool_calls:
                tool = self.registry.get(call.name)
                if tool is None or not workspace.allows(call.name):
                    result = ToolResult.fail(f"Tool desconhecida: {call.name}. Use só as tools listadas.")
                else:
                    arguments, errors = validate_arguments(tool.parameters, call.arguments)
                    if errors:
                        result = ToolResult.fail("Argumentos inválidos: " + "; ".join(errors))
                    elif tool.confirm:
                        summary = tool.confirmation_text(arguments)
                        pending = self.services.pending.create(tool.name, arguments, summary, channel=turn.channel)
                        self.services.audit.record("confirmation", tool.name, "requested", {"id": pending.id})
                        return AgentReply(
                            text=f"Confirma: {summary}? Responda sim ou não.",
                            pending_action_id=pending.id,
                            tools=executed,
                            links=ctx.links,
                        )
                    else:
                        result = await self._run_tool(tool.name, ctx, arguments)
                        executed.append(
                            {
                                "name": tool.name,
                                "ok": result.ok,
                                "summary": result.summary,
                                "arguments": arguments,
                                "id": call.id,
                            }
                        )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "tool_name": call.name, "content": result.to_llm()}
                )

        last = executed[-1]["summary"] if executed else "nenhuma ação concluída"
        return AgentReply(
            text=f"Parei após {settings.agent_max_steps} passos. Último resultado: {last}",
            tools=executed,
            links=ctx.links,
        )
