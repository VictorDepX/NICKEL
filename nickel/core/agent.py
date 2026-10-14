"""Loop do agente: histórico + tools nativas + confirmações."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nickel.core.llm import LLMError
from nickel.core.persona import build_system_prompt
from nickel.core.skills import ToolContext, ToolRegistry, ToolResult, validate_arguments
from nickel.core.stores import PendingAction, StoredMessage

if TYPE_CHECKING:  # pragma: no cover
    from nickel.services import Services

log = logging.getLogger(__name__)

_YES = {
    "sim", "s", "confirmo", "confirma", "confirmado", "pode", "ok", "okay", "manda", "envia", "faz",
    "isso", "claro", "yes", "y", "positivo", "beleza", "blz", "bora", "certo", "fechado", "vai",
    "mandar", "enviar", "fazer", "ser",
}
_NO = {"nao", "n", "cancela", "cancelar", "cancelado", "deixa", "esquece", "no", "negativo", "para", "nem"}
_FILLER = {"pode", "por", "favor", "pfv", "pf", "e", "isso", "mesmo", "precisa", "agora", "ai", "la"}


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


@dataclass
class AgentReply:
    text: str
    pending_action_id: str | None = None
    links: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)


class Agent:
    def __init__(self, services: "Services", registry: ToolRegistry) -> None:
        self.services = services
        self.registry = registry
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- entrada
    async def handle(self, turn: Turn) -> AgentReply:
        async with self._lock:
            store = self.services.conversations
            history = store.recent(self.services.settings.agent_history_messages)
            store.add("user", turn.llm_text or turn.text, channel=turn.channel, attachments=turn.attachments)

            pending = self.services.pending.current()
            if pending:
                decision = classify_confirmation(turn.text)
                if decision == "yes":
                    reply = await self._execute_pending(pending, turn.channel)
                    return self._finish(reply, turn.channel)
                if decision == "no":
                    self.services.pending.resolve(pending.id, "cancelled")
                    self.services.audit.record("confirmation", pending.tool, "cancelled", {"id": pending.id})
                    return self._finish(AgentReply(text="Cancelado."), turn.channel)
                # Mensagem nova não é consentimento: a ação pendente cai.
                self.services.pending.resolve(pending.id, "dropped")
                self.services.audit.record("confirmation", pending.tool, "dropped", {"id": pending.id})

            reply = await self._run_llm(turn, history)
            return self._finish(reply, turn.channel)

    async def confirm(self, action_id: str, channel: str = "ui") -> AgentReply:
        async with self._lock:
            pending = self.services.pending.get(action_id)
            if not pending or pending.status != "pending":
                return AgentReply(text="Essa ação não está mais pendente.")
            reply = await self._execute_pending(pending, channel)
            return self._finish(reply, channel)

    async def cancel(self, action_id: str, channel: str = "ui") -> AgentReply:
        async with self._lock:
            pending = self.services.pending.get(action_id)
            if not pending or pending.status != "pending":
                return AgentReply(text="Essa ação não está mais pendente.")
            self.services.pending.resolve(action_id, "cancelled")
            self.services.audit.record("confirmation", pending.tool, "cancelled", {"id": action_id})
            return self._finish(AgentReply(text=f"Cancelado: {pending.summary}."), channel)

    # ---------------------------------------------------------------- internos
    def _finish(self, reply: AgentReply, channel: str) -> AgentReply:
        attachments: list[dict[str, Any]] = []
        if reply.tools:
            attachments.append({"type": "tools", "items": reply.tools})
        if reply.pending_action_id:
            attachments.append({"type": "pending", "id": reply.pending_action_id})
        self.services.conversations.add("assistant", reply.text, channel=channel, attachments=attachments)
        return reply

    def _context(self, channel: str, user_text: str, audio: Path | None = None) -> ToolContext:
        return ToolContext(channel=channel, user_text=user_text, services=self.services, last_audio_path=audio)

    async def _run_tool(self, name: str, ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult.fail(f"Tool desconhecida: {name}")
        try:
            result = await tool.handler(ctx, arguments)
        except Exception as exc:  # a falha da tool vira resultado, não derruba o turno
            log.exception("Tool %s falhou", name)
            result = ToolResult.fail(f"{name} falhou: {exc}")
        self.services.audit.record(
            "tool", name, "ok" if result.ok else "error", {"arguments": arguments, "summary": result.summary}
        )
        return result

    async def _execute_pending(self, pending: PendingAction, channel: str) -> AgentReply:
        ctx = self._context(channel, "")
        result = await self._run_tool(pending.tool, ctx, pending.arguments)
        self.services.pending.resolve(pending.id, "confirmed" if result.ok else "failed", result.data)
        self.services.audit.record("confirmation", pending.tool, "confirmed", {"id": pending.id})
        return AgentReply(
            text=result.summary,
            links=ctx.links,
            tools=[{"name": pending.tool, "ok": result.ok, "summary": result.summary}],
        )

    def _history_messages(self, history: list[StoredMessage]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in history:
            if item.role not in {"user", "assistant"}:
                continue
            content = item.content
            for attachment in item.attachments:
                if attachment.get("type") == "image":
                    content = f"[imagem enviada] {content}".strip()
                elif attachment.get("type") == "tools":
                    actions = "; ".join(f"{t['name']}: {t['summary']}" for t in attachment.get("items", []))
                    content = f"{content}\n[ações executadas: {actions}]"
            messages.append({"role": item.role, "content": content})
        return messages

    async def _run_llm(self, turn: Turn, history: list[StoredMessage]) -> AgentReply:
        settings = self.services.settings
        system = build_system_prompt(
            channel=turn.channel,
            timezone=settings.timezone,
            memory=self.services.memory.all(),
        )
        current: dict[str, Any] = {"role": "user", "content": turn.llm_text or turn.text}
        if turn.images:
            current["images"] = turn.images
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *self._history_messages(history),
            current,
        ]
        tools = self.registry.schemas(self.services)
        ctx = self._context(turn.channel, turn.text, turn.last_audio_path)
        executed: list[dict[str, Any]] = []

        for _ in range(settings.agent_max_steps):
            try:
                reply = await self.services.llm.chat(messages, tools)
            except LLMError as exc:
                self.services.audit.record("llm", settings.llm_model, "error", {"detail": str(exc)})
                return AgentReply(text=f"O modelo local não respondeu ({exc}).", tools=executed, links=ctx.links)

            if not reply.tool_calls:
                fallback = "Feito." if executed else "Sem resposta do modelo."
                text = reply.content or fallback
                return AgentReply(text=text, tools=executed, links=ctx.links)

            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [
                        {"type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                        for call in reply.tool_calls
                    ],
                }
            )
            for call in reply.tool_calls:
                tool = self.registry.get(call.name)
                if tool is None:
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
                        executed.append({"name": tool.name, "ok": result.ok, "summary": result.summary})
                messages.append({"role": "tool", "tool_name": call.name, "content": result.to_llm()})

        last = executed[-1]["summary"] if executed else "nenhuma ação concluída"
        return AgentReply(
            text=f"Parei após {settings.agent_max_steps} passos. Último resultado: {last}",
            tools=executed,
            links=ctx.links,
        )
