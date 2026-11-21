"""Relatório em Markdown de uma execução (run) a partir dos eventos de auditoria."""
from __future__ import annotations

from typing import Any


def fmt_ms(ms: int | float | None) -> str:
    if ms is None:
        return "-"
    ms = int(ms)
    if ms < 1000:
        return f"{ms} ms"
    return f"{ms / 1000:.1f}".replace(".", ",") + " s"


def _cell(value: Any) -> str:
    return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")


def _hour(at: str) -> str:
    return at[11:19] if len(at) >= 19 else at


def render_run_report(events: list[dict[str, Any]]) -> str:
    if not events:
        return "# Execução sem eventos\n"
    events = sorted(events, key=lambda e: e["id"])
    run_id = events[0].get("run_id") or "-"
    total = sum(e.get("duration_ms") or 0 for e in events if e["kind"] in ("turn",)) or sum(
        e.get("duration_ms") or 0 for e in events
    )
    lines = [
        f"# Execução {run_id}",
        "",
        f"- Data: {events[0]['at']}",
        f"- Duração: {fmt_ms(total)}",
        f"- Eventos: {len(events)}",
        "",
        "## Etapas",
        "",
        "| hora | tipo | nome | status | ms |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in events:
        ms = e.get("duration_ms")
        lines.append(
            f"| {_hour(e['at'])} | {_cell(e['kind'])} | {_cell(e['name'])} | {_cell(e['status'])} | "
            f"{'' if ms is None else ms} |"
        )

    lines += ["", "## Ferramentas", ""]
    tools = [e for e in events if e["kind"] == "tool" and e["status"] in ("ok", "error")]
    if tools:
        for e in tools:
            summary = (e.get("detail") or {}).get("summary") or ""
            extra = f": {summary}" if summary else ""
            lines.append(f"- {e['name']} ({e['status']}, {fmt_ms(e.get('duration_ms'))}){extra}")
    else:
        lines.append("Nenhuma ferramenta executada.")

    lines += ["", "## Raciocínio", ""]
    reasoning = [e for e in events if e["kind"] == "reasoning"]
    final = next((e for e in reversed(reasoning) if e["status"] == "final"), None)
    if final:
        detail = final.get("detail") or {}
        headline = detail.get("headline")
        conclusion = detail.get("conclusion") or detail.get("text")
        if headline:
            lines.append(f"**{headline}**")
            lines.append("")
        lines.append(str(conclusion) if conclusion else "sem raciocínio expandido")
    else:
        lines.append("sem raciocínio expandido")

    lines += ["", "## Erros", ""]
    errors = [e for e in events if e["status"] == "error"]
    if errors:
        for e in errors:
            detail = (e.get("detail") or {}).get("detail") or (e.get("detail") or {}).get("summary") or ""
            lines.append(f"- {e['kind']}/{e['name']}: {detail}".rstrip(": "))
    else:
        lines.append("Nenhum erro.")
    return "\n".join(lines) + "\n"
