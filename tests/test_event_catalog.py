"""Testes de completude do catálogo de eventos de auditoria."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nickel.core.events import CATALOG, PHASE_LABELS, PHASES, TURN_FLOW, phase_for

ROOT = Path(__file__).resolve().parent.parent / "nickel"


def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _receiver_ends_in_audit(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "audit"
    if isinstance(node, ast.Name):
        return node.id == "audit"
    return False


def _calls(method: str, audit_only: bool):
    """Gera (arquivo, linha, kind, status) de cada chamada `X.method(...)`."""
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != method:
                continue
            if audit_only and not _receiver_ends_in_audit(node.func.value):
                continue
            args = node.args
            kind = _literal(args[0]) if len(args) > 0 else None
            status = _literal(args[2]) if len(args) > 2 else None
            yield path.relative_to(ROOT.parent), node.lineno, kind, status


def test_phase_for_known_and_unknown():
    assert phase_for("llm", "start") == "thinking"
    assert phase_for("oauth", "connected") is None


def test_every_phase_value_has_a_label():
    assert set(PHASES.values()) <= set(PHASE_LABELS)
    assert set(PHASE_LABELS) == {
        "idle", "routing", "prompting", "thinking", "answering",
        "tool", "confirming", "listening", "speaking", "error",
    }
    for kind, status in list(PHASES) + list(TURN_FLOW):
        assert kind in CATALOG and status in CATALOG[kind].statuses


def test_all_record_calls_use_cataloged_kind_and_status():
    errors = []
    for path, line, kind, status in _calls("record", audit_only=True):
        if kind is None:
            continue
        if kind not in CATALOG:
            errors.append(f"{path}:{line} kind desconhecido: {kind!r}")
        elif status is not None and status not in CATALOG[kind].statuses:
            errors.append(f"{path}:{line} status {status!r} fora do catálogo de {kind!r}")
    assert not errors, "\n".join(errors)


@pytest.mark.xfail(strict=True, reason="fecha na Task 6")
def test_every_cataloged_kind_is_emitted_somewhere():
    emitted = {k for _, _, k, _ in _calls("record", True) if k}
    emitted |= {k for _, _, k, _ in _calls("emit", False) if k}
    missing = sorted(set(CATALOG) - emitted)
    assert not missing, f"kinds nunca emitidos: {missing}"
