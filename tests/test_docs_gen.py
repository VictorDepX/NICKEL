from __future__ import annotations

import json
from pathlib import Path

import pytest

from nickel.cli import main
from nickel.core import trace
from nickel.core.db import Database
from nickel.core.docs_gen import CATALOG_FILE, TURN_FLOW_FILE, render_catalog_md, render_turn_flow_md
from nickel.core.events import CATALOG, PHASES, TURN_FLOW
from nickel.core.stores import AuditLog

DOCS = Path(__file__).resolve().parent.parent / "docs" / "processos"


def test_committed_docs_match_generator():
    assert (DOCS / CATALOG_FILE).read_text(encoding="utf-8") == render_catalog_md()
    assert (DOCS / TURN_FLOW_FILE).read_text(encoding="utf-8") == render_turn_flow_md()


def test_generated_docs_are_deterministic_and_marked():
    for text in (render_catalog_md(), render_turn_flow_md()):
        assert text.startswith("<!-- Gerado por `nickel audit docs`")
        assert text.endswith("\n") and not text.endswith("\n\n")
    assert render_catalog_md() == render_catalog_md()


def test_catalog_md_lists_every_kind_and_status():
    md = render_catalog_md()
    for kind, spec in CATALOG.items():
        assert f"`{kind}`" in md
        for status in spec.statuses:
            assert f"`{status}`" in md
        for field in spec.fields:
            assert f"`{field}`" in md
    for (kind, status) in PHASES:
        assert f"| `{kind}` | `{status}` |" in md


def test_turn_flow_mermaid_has_one_arrow_per_step():
    md = render_turn_flow_md()
    assert "sequenceDiagram" in md
    arrows = [ln for ln in md.splitlines() if "->>" in ln]
    assert len(arrows) == len(TURN_FLOW)
    for (kind, status), line in zip(TURN_FLOW, arrows):
        assert line.endswith(f"{kind}/{status}")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NICKEL_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # sem .env
    audit = AuditLog(Database(tmp_path / "nickel.db"))
    with trace.run_scope("run-abc"):
        audit.record("turn", "chat", "start")
        audit.record("turn", "chat", "done", {"reply_chars": 5}, duration_ms=1200)
    with trace.run_scope("run-def"):
        audit.record("tool", "notes", "ok", {"summary": "çã"}, duration_ms=5)
    return tmp_path


def test_cli_audit_report_prints_markdown_for_existing_run(data_dir, capsys):
    assert main(["audit", "report", "run-abc"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Execução run-abc")


def test_cli_audit_report_unknown_run_exits_nonzero(data_dir, capsys):
    assert main(["audit", "report", "nope"]) == 1
    captured = capsys.readouterr()
    assert "não encontrada" in captured.err
    assert captured.out == ""


def test_cli_audit_export_jsonl_one_event_per_line(data_dir, capsys):
    assert main(["audit", "export"]) == 0
    lines = capsys.readouterr().out.splitlines()
    events = [json.loads(ln) for ln in lines]
    assert len(events) == 3
    assert events[2]["detail"] == {"summary": "çã"}
    assert "çã" in lines[2]


def test_cli_audit_export_since_and_md(data_dir, capsys):
    assert main(["audit", "export", "--since", "2999-01-01T00:00:00"]) == 0
    assert capsys.readouterr().out == ""
    assert main(["audit", "export", "--format", "md"]) == 0
    out = capsys.readouterr().out
    assert out.index("# Execução run-def") < out.index("# Execução run-abc")


def test_cli_audit_docs_writes_files(tmp_path, capsys):
    assert main(["audit", "docs", "--out", str(tmp_path / "x")]) == 0
    assert (tmp_path / "x" / CATALOG_FILE).read_text(encoding="utf-8") == render_catalog_md()
