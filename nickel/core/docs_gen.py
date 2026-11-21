"""Gera a documentação de processos a partir do catálogo de eventos."""
from __future__ import annotations

from pathlib import Path

from nickel.core.events import CATALOG, PHASE_LABELS, PHASES, TURN_FLOW

HEADER = "<!-- Gerado por `nickel audit docs` a partir de nickel/core/events.py. Não edite à mão. -->"

CATALOG_FILE = "catalogo-de-eventos.md"
TURN_FLOW_FILE = "fluxo-de-um-turno.md"

# Participantes do diagrama: (nome exibido no Mermaid, alias).
_PARTICIPANTS = (("Usuário/Canal", "Canal"), ("Agente", "Agente"), ("Modelo", "Modelo"), ("Ferramenta", "Ferramenta"))
_ALIAS = {"Canal": "Usuário/Canal"}

# (kind, status) -> (origem, destino, seta, rótulo opcional). O que não estiver aqui vira nota do agente.
_ARROWS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("turn", "start"): ("Canal", "Agente", "->>"),
    ("turn", "done"): ("Agente", "Canal", "-->>"),
    ("turn", "error"): ("Agente", "Canal", "-->>"),
    ("llm", "start"): ("Agente", "Modelo", "->>"),
    ("llm", "done"): ("Modelo", "Agente", "-->>"),
    ("llm", "error"): ("Modelo", "Agente", "-->>"),
    ("reasoning", "progress"): ("Modelo", "Agente", "-->>"),
    ("reasoning", "final"): ("Modelo", "Agente", "-->>"),
    ("tool", "start"): ("Agente", "Ferramenta", "->>"),
    ("tool", "ok"): ("Ferramenta", "Agente", "-->>"),
    ("tool", "error"): ("Ferramenta", "Agente", "-->>"),
}


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_catalog_md() -> str:
    lines = [
        HEADER,
        "",
        "# Catálogo de eventos de auditoria",
        "",
        "Cada ação relevante do NICKEL grava um evento em `AuditLog` (`kind`, `name`, `status`, `detail`).",
        "Esta página lista os tipos (`kind`), seus estados, os campos de `detail` e o módulo que os emite.",
        "",
        "## Tipos de evento",
        "",
        "| kind | descrição | estados | campos | fonte |",
        "| --- | --- | --- | --- | --- |",
    ]
    for kind in sorted(CATALOG):
        spec = CATALOG[kind]
        statuses = ", ".join(f"`{s}`" for s in spec.statuses)
        fields = ", ".join(f"`{f}`" for f in spec.fields) or "-"
        lines.append(
            f"| `{kind}` | {_cell(spec.description)} | {statuses} | {fields} | `{_cell(spec.source)}` |"
        )
    lines += [
        "",
        "## Fases da interface",
        "",
        "O monitor deduz a fase atual a partir do último evento que muda de fase.",
        "",
        "| kind | status | fase |",
        "| --- | --- | --- |",
    ]
    for (kind, status) in sorted(PHASES):
        phase = PHASES[(kind, status)]
        lines.append(f"| `{kind}` | `{status}` | {PHASE_LABELS.get(phase, phase)} (`{phase}`) |")
    return "\n".join(lines) + "\n"


def render_turn_flow_md() -> str:
    lines = [
        HEADER,
        "",
        "# Fluxo de um turno",
        "",
        "Sequência esperada de eventos num turno normal com uma chamada de ferramenta.",
        "Cada seta corresponde a um evento `kind/status` de `TURN_FLOW`.",
        "",
        "```mermaid",
        "sequenceDiagram",
    ]
    for label, alias in _PARTICIPANTS:
        lines.append(f"    participant {alias} as {label}")
    for kind, status in TURN_FLOW:
        src, dst, arrow = _ARROWS.get((kind, status), ("Agente", "Agente", "->>"))
        lines.append(f"    {src}{arrow}{dst}: {kind}/{status}")
    lines += ["```", "", "## Etapas", ""]
    for i, (kind, status) in enumerate(TURN_FLOW, 1):
        spec = CATALOG.get(kind)
        lines.append(f"{i}. `{kind}/{status}`: {spec.description if spec else '-'}")
    return "\n".join(lines) + "\n"


def write_docs(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {CATALOG_FILE: render_catalog_md(), TURN_FLOW_FILE: render_turn_flow_md()}
    paths = []
    for name, content in files.items():
        path = out / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths
