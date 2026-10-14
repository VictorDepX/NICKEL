"""Escrita de notas no vault do Obsidian.

Regra de sincronização (Syncthing): o NICKEL só cria arquivos novos e nunca edita
notas existentes, para não gerar conflito com edições feitas no outro computador.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

KINDS = ("pensamento", "ideia", "tarefa", "referencia", "diario", "pergunta")
_INVALID = re.compile(r'[\\/:*?"<>|#^\[\]\n\r\t]')
_SKIP_DIRS = {".obsidian", ".trash", ".git", ".stfolder", ".stversions"}


def safe_filename(title: str, max_length: int = 80) -> str:
    """Nome válido no Linux e no Windows (o vault é sincronizado entre os dois)."""
    name = _INVALID.sub(" ", title)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if len(name) > max_length:
        name = name[:max_length].rsplit(" ", 1)[0].rstrip(". ") or name[:max_length]
    return name or "Nota sem título"


def normalize_tag(tag: str) -> str:
    tag = tag.strip().lstrip("#").lower()
    tag = unicodedata.normalize("NFKD", tag)
    tag = "".join(ch for ch in tag if not unicodedata.combining(ch))
    tag = re.sub(r"[^a-z0-9/_-]+", "-", tag).strip("-")
    return tag


class ObsidianVault:
    def __init__(self, vault_path: Path | None, notes_dir: str) -> None:
        self.vault_path = vault_path
        self.notes_dir = notes_dir
        self._titles: set[str] = set()
        self._titles_at = 0.0

    @property
    def available(self) -> bool:
        return bool(self.vault_path and self.vault_path.is_dir())

    @property
    def notes_path(self) -> Path:
        assert self.vault_path is not None
        return self.vault_path / self.notes_dir

    def _iter_notes(self, root: Path):
        for path in root.rglob("*.md"):
            if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            yield path

    def existing_titles(self) -> set[str]:
        if not self.available:
            return set()
        if time.monotonic() - self._titles_at > 60:
            self._titles = {path.stem for path in self._iter_notes(self.vault_path)}
            self._titles_at = time.monotonic()
        return self._titles

    def create_note(
        self,
        *,
        title: str,
        content: str,
        kind: str,
        tags: list[str],
        links: list[str],
        source: str,
        original: str,
        now: datetime,
    ) -> tuple[Path, list[str]]:
        """Cria a nota e devolve (caminho, links aceitos)."""
        if not self.available:
            raise FileNotFoundError("Vault do Obsidian não encontrado (OBSIDIAN_VAULT_PATH).")
        self.notes_path.mkdir(parents=True, exist_ok=True)

        known = self.existing_titles()
        valid_links = [link for link in dict.fromkeys(l.strip() for l in links) if link and link in known]
        kind = kind if kind in KINDS else "pensamento"
        clean_tags = list(dict.fromkeys(t for t in ["pensamento", kind, *map(normalize_tag, tags)] if t))
        date = now.strftime("%Y-%m-%d")

        frontmatter = "\n".join(
            [
                "---",
                f"title: {json.dumps(title.strip(), ensure_ascii=False)}",
                f"tags: [{', '.join(clean_tags)}]",
                "type: pensamento",
                f"categoria: {kind}",
                f"fonte: {source}",
                "status: inbox",
                f"created: {date}",
                f"updated: {date}",
                f"capturado_em: {now.isoformat(timespec='minutes')}",
                "---",
            ]
        )
        body = [frontmatter, "", f"# {title.strip()}", "", content.strip(), ""]
        if valid_links:
            body += ["## Conexões", *[f"- [[{link}]]" for link in valid_links], ""]
        if original.strip() and original.strip() != content.strip():
            quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in original.strip().splitlines())
            body += ["> [!quote]- Original", quoted, ""]
        body += ["---", f"Capturado pelo NICKEL ({source}) em {now.strftime('%d/%m/%Y %H:%M')}.", ""]

        base = safe_filename(title)
        path = self.notes_path / f"{base}.md"
        counter = 2
        while path.exists():
            path = self.notes_path / f"{base} ({counter}).md"
            counter += 1
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(body))
        self._titles.add(path.stem)
        return path, valid_links

    def search(self, query: str, limit: int = 5, whole_vault: bool = False) -> list[dict[str, Any]]:
        if not self.available:
            return []
        root = self.vault_path if whole_vault else self.notes_path
        if not root.exists():
            return []
        needle = query.lower().strip()
        results: list[dict[str, Any]] = []
        candidates = sorted(self._iter_notes(root), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            haystack = text.lower()
            position = haystack.find(needle) if needle else 0
            if needle and position < 0 and needle not in path.stem.lower():
                continue
            start = max(0, position - 80)
            snippet = re.sub(r"\s+", " ", text[start : start + 240]).strip()
            results.append(
                {"title": path.stem, "path": str(path.relative_to(self.vault_path)), "snippet": snippet}
            )
            if len(results) >= limit:
                break
        return results
