"""Workspaces: perfis de trabalho (o equivalente local dos Projetos do Claude).

Um workspace NÃO é outro modelo: é um perfil sobre o mesmo modelo, com instruções,
ferramentas permitidas, pasta de notas, parâmetros de geração, histórico próprio e backend.

Cada workspace é um arquivo Markdown em `WORKSPACES_DIR`, com frontmatter simples:

    ---
    name: RPG CoC
    description: Guardião de Chamado de Cthulhu 7e
    aliases: [rpg, coc]
    keywords: [investigador, sanidade, guardião]
    tools: [notes_*]          # padrões fnmatch; omitido = todas; [] = nenhuma
    backend: local            # local | cloud
    think: false
    temperature: 0.8
    max_tokens: 1500
    history: 24
    notes_dir: 07 RPG/Sessões
    ---
    Instruções do workspace (corpo do arquivo).
"""

from __future__ import annotations

import fnmatch
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nickel.core.stores import MAIN_CONVERSATION

if TYPE_CHECKING:  # pragma: no cover
    from nickel.config import Settings
    from nickel.core.stores import StateStore

log = logging.getLogger(__name__)

ACTIVE_KEY = "workspace.active"
LIST_COMMANDS = {"ws", "workspace", "workspaces", "projeto", "projetos"}
_FRONT_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")


def normalize(text: str) -> str:
    """Minúsculas, sem acentos."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(text)).strip("-")


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    description: str = ""
    instructions: str = ""
    aliases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    tools: tuple[str, ...] | None = None  # None = todas; padrões fnmatch
    backend: str = "local"
    think: bool | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    history: int | None = None
    notes_dir: str | None = None
    is_default: bool = False

    @property
    def conversation(self) -> str:
        """O workspace padrão mantém a conversa `main` (compatível com a v2 original)."""
        return MAIN_CONVERSATION if self.is_default else self.id

    @property
    def handles(self) -> set[str]:
        return {self.id, *(slugify(alias) for alias in self.aliases)}

    def allows(self, tool_name: str) -> bool:
        if self.tools is None:
            return True
        return any(fnmatch.fnmatchcase(tool_name, pattern) for pattern in self.tools)

    def llm_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if self.think is not None:
            options["think"] = self.think
        if self.temperature is not None:
            options["temperature"] = self.temperature
        if self.max_tokens is not None:
            options["max_tokens"] = self.max_tokens
        return options


# ------------------------------------------------------------------ leitura dos arquivos
def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text.strip()
    meta: dict[str, str | list[str]] = {}
    key: str | None = None
    for raw in lines[1:end]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _FRONT_KEY.match(raw)
        if match and not raw[:1].isspace():
            key, value = match.group(1).lower(), match.group(2).strip()
            if value == "":
                meta[key] = []
            elif value.startswith("[") and value.endswith("]"):
                meta[key] = [_unquote(part) for part in value[1:-1].split(",") if part.strip()]
            else:
                meta[key] = _unquote(value)
        elif stripped.startswith("- ") and key and isinstance(meta.get(key), list):
            meta[key].append(_unquote(stripped[2:]))  # type: ignore[union-attr]
    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _scalar(value: Any) -> str | None:
    if isinstance(value, list):
        return None
    return value.strip() or None if isinstance(value, str) else None


def _bool(value: Any) -> bool | None:
    raw = _scalar(value)
    if raw is None:
        return None
    return raw.lower() in {"1", "true", "yes", "on", "sim"}


def _number(value: Any, cast):
    raw = _scalar(value)
    if raw is None:
        return None
    try:
        return cast(raw.replace(",", "."))
    except ValueError:
        return None


def _list(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(item for item in value if item)
    raw = _scalar(value)
    return tuple(part.strip() for part in raw.split(",") if part.strip()) if raw else ()


def workspace_from_text(identifier: str, text: str, *, is_default: bool = False) -> Workspace:
    meta, body = parse_frontmatter(text)
    tools: tuple[str, ...] | None = None
    if "tools" in meta:
        tools = _list(meta["tools"])
    backend = (_scalar(meta.get("backend")) or "local").lower()
    return Workspace(
        id=identifier,
        name=_scalar(meta.get("name")) or identifier,
        description=_scalar(meta.get("description")) or "",
        instructions=body,
        aliases=_list(meta.get("aliases")),
        keywords=_list(meta.get("keywords")),
        tools=tools,
        backend=backend if backend in {"local", "cloud"} else "local",
        think=_bool(meta.get("think")),
        temperature=_number(meta.get("temperature"), float),
        max_tokens=_number(meta.get("max_tokens"), int),
        history=_number(meta.get("history"), int),
        notes_dir=_scalar(meta.get("notes_dir")),
        is_default=is_default,
    )


def load_workspaces(directory: Path | None, default_id: str) -> dict[str, Workspace]:
    """Lê `*.md` do diretório. Sempre devolve um workspace padrão."""
    default_id = slugify(default_id) or "geral"
    found: dict[str, Workspace] = {}
    if directory and directory.is_dir():
        for path in sorted(directory.glob("*.md")):
            if path.name.startswith(("_", ".")) or path.stem.lower() == "readme":
                continue
            identifier = slugify(path.stem)
            if not identifier or identifier in found:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                log.warning("Workspace %s ignorado: %s", path.name, exc)
                continue
            found[identifier] = workspace_from_text(identifier, text, is_default=identifier == default_id)
    if default_id not in found:
        found = {default_id: Workspace(id=default_id, name="Geral", is_default=True), **found}
    return found


# ------------------------------------------------------------------ roteamento
@dataclass
class Resolution:
    workspace: Workspace
    text: str
    command: str | None = None  # "list" | "switch" | "unknown"
    switched: bool = False
    auto: bool = False
    target: str | None = None  # nome digitado, quando "unknown"

    @property
    def command_only(self) -> bool:
        return self.command in {"list", "unknown"} or (self.command == "switch" and not self.text)


class WorkspaceManager:
    def __init__(
        self,
        workspaces: dict[str, Workspace],
        state: "StateStore | None" = None,
        *,
        default_id: str = "geral",
        auto_route: bool = False,
        auto_threshold: int = 2,
        directory: Path | None = None,
    ) -> None:
        self.default_id = slugify(default_id) or "geral"
        self.state = state
        self.auto_route = auto_route
        self.auto_threshold = max(1, auto_threshold)
        self.directory = directory
        self._memory_active: str | None = None
        self._signature: tuple[tuple[str, float, int], ...] | None = None
        self._workspaces: dict[str, Workspace] = {}
        self._index: dict[str, str] = {}
        self._set(workspaces)

    @classmethod
    def from_settings(cls, settings: "Settings", state: "StateStore | None" = None) -> "WorkspaceManager":
        manager = cls(
            load_workspaces(settings.workspaces_dir, settings.workspace_default),
            state,
            default_id=settings.workspace_default,
            auto_route=settings.workspace_auto_route,
            auto_threshold=settings.workspace_auto_threshold,
            directory=settings.workspaces_dir,
        )
        manager._signature = manager._scan()
        return manager

    # -- catálogo
    def _set(self, workspaces: dict[str, Workspace]) -> None:
        self._workspaces = dict(workspaces)
        self._index = {}
        for workspace in self._workspaces.values():
            for handle in workspace.handles:
                if handle in self._index and self._index[handle] != workspace.id:
                    log.warning("Apelido '%s' repetido; mantido em '%s'", handle, self._index[handle])
                    continue
                self._index[handle] = workspace.id

    def _scan(self) -> tuple[tuple[str, float, int], ...]:
        if not self.directory or not self.directory.is_dir():
            return ()
        entries = []
        for path in sorted(self.directory.glob("*.md")):
            try:
                info = path.stat()
            except OSError:
                continue
            entries.append((path.name, info.st_mtime, info.st_size))
        return tuple(entries)

    def refresh(self) -> None:
        """Recarrega os arquivos se algo mudou (edições feitas no Obsidian valem na próxima mensagem)."""
        if not self.directory:
            return
        signature = self._scan()
        if signature != self._signature:
            self._signature = signature
            self._set(load_workspaces(self.directory, self.default_id))

    def all(self) -> list[Workspace]:
        return list(self._workspaces.values())

    def get(self, identifier: str) -> Workspace | None:
        return self._workspaces.get(self._index.get(slugify(identifier), ""))

    @property
    def default(self) -> Workspace:
        return self._workspaces[self.default_id]

    # -- ativo
    def active(self) -> Workspace:
        stored = self.state.get(ACTIVE_KEY) if self.state else self._memory_active
        return self._workspaces.get(stored or "", self.default)

    def activate(self, identifier: str) -> Workspace:
        workspace = self.get(identifier)
        if workspace is None:
            raise KeyError(identifier)
        if self.state:
            self.state.set(ACTIVE_KEY, workspace.id)
        else:
            self._memory_active = workspace.id
        return workspace

    # -- roteamento
    def resolve(self, text: str) -> Resolution:
        self.refresh()
        active = self.active()
        stripped = text.strip()
        match = re.match(r"^/(\S+)(?:\s+(.*))?$", stripped, re.DOTALL)
        if match:
            command, rest = slugify(match.group(1)), (match.group(2) or "").strip()
            if command in LIST_COMMANDS:
                if not rest:
                    return Resolution(active, "", command="list")
                name, _, remainder = rest.partition(" ")
                target = self.get(name)
                if target is None:
                    return Resolution(active, "", command="unknown", target=name)
                return self._switch(active, target, remainder.strip())
            target = self.get(command)
            if target is not None:
                return self._switch(active, target, rest)
            # "/qualquer-coisa" que não é workspace segue como mensagem normal
        if self.auto_route:
            guess = self._guess(stripped)
            if guess is not None and guess.id != active.id:
                self.activate(guess.id)
                return Resolution(guess, stripped, switched=True, auto=True)
        return Resolution(active, stripped)

    def _switch(self, previous: Workspace, target: Workspace, text: str) -> Resolution:
        self.activate(target.id)
        return Resolution(target, text, command="switch", switched=target.id != previous.id)

    def _guess(self, text: str) -> Workspace | None:
        haystack = normalize(text)
        scores: list[tuple[int, Workspace]] = []
        for workspace in self._workspaces.values():
            hits = 0
            for keyword in workspace.keywords:
                needle = normalize(keyword).strip()
                if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
                    hits += 1
            if hits:
                scores.append((hits, workspace))
        if not scores:
            return None
        scores.sort(key=lambda item: item[0], reverse=True)
        best, workspace = scores[0]
        if best < self.auto_threshold or (len(scores) > 1 and scores[1][0] == best):
            return None
        return workspace

    # -- texto para os canais
    def describe(self) -> str:
        active = self.active()
        lines = ["Workspaces:"]
        for workspace in self._workspaces.values():
            marker = " (ativo)" if workspace.id == active.id else ""
            names = sorted({workspace.id, *(slugify(a) for a in workspace.aliases)})
            commands = ", ".join(f"/{name}" for name in names)
            summary = f" — {workspace.description}" if workspace.description else ""
            lines.append(f"- {workspace.name}{marker}: {commands}{summary}")
        lines.append("Use /<nome> para trocar ou /<nome> mensagem para falar direto com um deles.")
        return "\n".join(lines)
