"""Registro de skills: cada tool é declarada uma única vez."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:  # pragma: no cover
    from nickel.services import Services

_MAX_RESULT_CHARS = 4000


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_llm(self) -> str:
        text = json.dumps({"ok": self.ok, "summary": self.summary, "data": self.data}, ensure_ascii=False, default=str)
        if len(text) > _MAX_RESULT_CHARS:
            text = text[:_MAX_RESULT_CHARS] + "…(truncado)"
        return text

    @classmethod
    def fail(cls, summary: str, **data: Any) -> "ToolResult":
        return cls(ok=False, summary=summary, data=data)


@dataclass
class ToolContext:
    channel: str
    user_text: str
    services: "Services"
    last_audio_path: Path | None = None
    # Links que o canal pode abrir/mostrar depois da resposta (ex.: música encontrada).
    links: list[str] = field(default_factory=list)

    @property
    def settings(self):
        return self.services.settings


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    confirm: bool = False
    describe: Callable[[dict[str, Any]], str] | None = None
    available: Callable[["Services"], bool] | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def confirmation_text(self, arguments: dict[str, Any]) -> str:
        if self.describe:
            return self.describe(arguments)
        args = ", ".join(f"{key}={value!r}" for key, value in arguments.items())
        return f"executar {self.name}({args})"

    def is_available(self, services: "Services") -> bool:
        return self.available(services) if self.available else True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Tool duplicada: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def add(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        *,
        confirm: bool = False,
        describe: Callable[[dict[str, Any]], str] | None = None,
        available: Callable[["Services"], bool] | None = None,
    ) -> Callable[[Handler], Handler]:
        """Decorator: `@registry.add("nome", "descrição", {...})`."""

        def decorator(handler: Handler) -> Handler:
            self.register(
                Tool(
                    name=name,
                    description=description,
                    parameters=parameters or {"type": "object", "properties": {}},
                    handler=handler,
                    confirm=confirm,
                    describe=describe,
                    available=available,
                )
            )
            return handler

        return decorator

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def available(self, services: "Services") -> list[Tool]:
        return [tool for tool in self._tools.values() if tool.is_available(services)]

    def schemas(self, services: "Services") -> list[dict[str, Any]]:
        return [tool.schema() for tool in self.available(services)]


_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validação leve de JSON Schema (o suficiente para argumentos gerados por LLM).

    Converte casos comuns ("10" → 10, "true" → True), descarta chaves desconhecidas
    e devolve a lista de erros em português.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    clean: dict[str, Any] = {}
    errors: list[str] = []

    for key, value in arguments.items():
        spec = properties.get(key)
        if spec is None:
            continue  # o modelo inventou um campo; ignora
        if value is None:
            continue
        expected = spec.get("type")
        value = _coerce(value, expected)
        if expected and not _matches(value, expected):
            errors.append(f"'{key}' deveria ser {expected}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"'{key}' deve ser um de {spec['enum']}")
            continue
        if expected == "array" and "items" in spec and spec["items"].get("type"):
            item_type = spec["items"]["type"]
            value = [_coerce(item, item_type) for item in value]
            if not all(_matches(item, item_type) for item in value):
                errors.append(f"itens de '{key}' deveriam ser {item_type}")
                continue
        clean[key] = value

    for key in required:
        value = clean.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"'{key}' é obrigatório")
    return clean, errors


def _matches(value: Any, expected: str) -> bool:
    types = _TYPES.get(expected)
    if types is None:
        return True
    if expected in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, types)


def _coerce(value: Any, expected: str | None) -> Any:
    if expected == "integer" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    if expected == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    if expected == "number" and isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return value
    if expected == "boolean" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "sim", "yes", "1"}:
            return True
        if lowered in {"false", "não", "nao", "no", "0"}:
            return False
    if expected == "array" and isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value
