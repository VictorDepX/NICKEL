from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from nickel.core.agent import Agent, Turn
from nickel.integrations.obsidian import ObsidianVault, normalize_tag, safe_filename
from nickel.skills import build_registry

from conftest import call, run, say

NOW = datetime(2026, 10, 14, 15, 40, tzinfo=ZoneInfo("America/Sao_Paulo"))


def test_safe_filename_is_windows_safe():
    assert safe_filename('Ideia: app "X"/Y? <z>|#tag.') == "Ideia app X Y z tag"
    assert safe_filename("   ") == "Nota sem título"
    assert len(safe_filename("palavra " * 30)) <= 80


def test_normalize_tag():
    assert normalize_tag("#Escrita Criativa") == "escrita-criativa"
    assert normalize_tag("Ação") == "acao"


def test_create_note_with_frontmatter_links_and_original(vault):
    obsidian = ObsidianVault(vault, "06 Pensamentos")
    path, links = obsidian.create_note(
        title="Cena do corredor",
        content="- Espelho reflete com atraso\n- Usar no capítulo 3",
        kind="ideia",
        tags=["Escrita", "terror"],
        links=["Fluxo de criação", "Nota que não existe"],
        source="whatsapp",
        original="tive uma ideia o espelho do corredor reflete com atraso usar no capitulo tres",
        now=NOW,
    )
    assert path == vault / "06 Pensamentos" / "Cena do corredor.md"
    assert links == ["Fluxo de criação"]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: \"Cena do corredor\"\ntags: [pensamento, ideia, escrita, terror]\n")
    assert "type: pensamento\ncategoria: ideia\nfonte: whatsapp\nstatus: inbox\ncreated: 2026-10-14" in text
    assert "## Conexões\n- [[Fluxo de criação]]" in text
    assert "[[Nota que não existe]]" not in text
    assert "> [!quote]- Original\n> tive uma ideia" in text


def test_collision_never_overwrites(vault):
    obsidian = ObsidianVault(vault, "06 Pensamentos")
    first, _ = obsidian.create_note(title="Mesma", content="a", kind="x", tags=[], links=[], source="ui", original="", now=NOW)
    second, _ = obsidian.create_note(title="Mesma", content="b", kind="x", tags=[], links=[], source="ui", original="", now=NOW)
    assert first.name == "Mesma.md" and second.name == "Mesma (2).md"
    assert "categoria: pensamento" in second.read_text(encoding="utf-8")  # kind inválido cai no padrão
    assert "Original" not in first.read_text(encoding="utf-8")


def test_search(vault):
    obsidian = ObsidianVault(vault, "06 Pensamentos")
    obsidian.create_note(title="Treino", content="ideia de planilha de cargas", kind="ideia", tags=[], links=[],
                         source="voz", original="", now=NOW)
    assert obsidian.search("planilha")[0]["title"] == "Treino"
    assert obsidian.search("Fluxo") == []
    assert obsidian.search("Fluxo", whole_vault=True)[0]["title"] == "Fluxo de criação"


def test_capture_tool_end_to_end(services, llm, vault):
    llm.queue(
        call("notes_capture", title="Ideia de conto", content="Um inquilino que só existe à noite.",
             kind="ideia", tags=["conto"]),
        say("Anotado."),
    )
    reply = run(Agent(services, build_registry()).handle(
        Turn(channel="voice", text="anota aí um inquilino que só existe de noite")))
    assert reply.text == "Anotado."
    note = vault / "06 Pensamentos" / "Ideia de conto.md"
    text = note.read_text(encoding="utf-8")
    assert "fonte: voz" in text
    assert "> anota aí um inquilino que só existe de noite" in text
