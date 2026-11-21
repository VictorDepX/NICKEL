"""Rastreador do raciocínio do modelo e resumo determinístico.

O resumo nunca chama um modelo: cabeçalho e conclusão vêm das frases do
próprio texto. O rastreador recebe os deltas do LLM (``on_delta``) e grava
eventos ``reasoning/progress`` (limitados por tempo) e ``reasoning/final``.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

HEADLINE_MAX = 140
FINAL_TEXT_LIMIT = 4000
_SPLIT = re.compile(r"(?<=[.!?])(?:\s+|$)|\n+")


@dataclass(frozen=True)
class ReasoningSummary:
    headline: str
    conclusion: str
    chars: int
    tokens_est: int
    tools_mentioned: tuple[str, ...]


def _cap(sentence: str) -> str:
    if len(sentence) <= HEADLINE_MAX:
        return sentence
    return sentence[: HEADLINE_MAX - 1].rstrip() + "…"


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in _SPLIT.split(text) if p and p.strip()]


def summarize_reasoning(text: str, tool_names: Iterable[str] = ()) -> ReasoningSummary:
    sentences = _sentences(text)
    headline = _cap(sentences[0]) if sentences else ""
    conclusion = _cap(sentences[-1]) if sentences else ""
    tools = tuple(n for n in tool_names if n and n in text)
    return ReasoningSummary(headline, conclusion, len(text), math.ceil(len(text) / 4), tools)


class ReasoningTracker:
    """Acumula deltas de raciocínio e emite eventos de auditoria."""

    def __init__(
        self,
        audit: Any,
        *,
        step: int,
        tool_names: Iterable[str] = (),
        interval_s: float = 0.4,
        tail_chars: int = 600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.audit = audit
        self.step = step
        self.tool_names = tuple(tool_names)
        self.interval_s = interval_s
        self.tail_chars = min(tail_chars, FINAL_TEXT_LIMIT)
        self.clock = clock
        self._parts: list[str] = []
        self._chars = 0
        self._content_chars = 0
        self._last_emit: float | None = None
        self._summary: ReasoningSummary | None = None

    def _record(self, status: str, detail: dict[str, Any], limit: int) -> None:
        try:
            self.audit.record("reasoning", "model", status, detail, text_limit=limit)
        except Exception:
            logger.debug("falha ao gravar evento de raciocínio", exc_info=True)

    def feed(self, channel: str, text: str) -> None:
        if channel != "reasoning":
            if channel == "content":
                self._content_chars += len(text)
            return
        if not text:
            return
        self._parts.append(text)
        self._chars += len(text)
        now = self.clock()
        if self._last_emit is not None and now - self._last_emit < self.interval_s:
            return
        self._last_emit = now
        full = "".join(self._parts)
        self._parts = [full]
        summary = summarize_reasoning(full)
        self._record(
            "progress",
            {
                "step": self.step,
                "chars": summary.chars,
                "tokens_est": summary.tokens_est,
                "headline": summary.headline,
                "tail": full[-self.tail_chars :],
                "content_chars": self._content_chars,
            },
            self.tail_chars,
        )

    def finish(self) -> ReasoningSummary:
        if self._summary is not None:
            return self._summary
        full = "".join(self._parts)
        summary = summarize_reasoning(full, self.tool_names)
        self._summary = summary
        if full:
            self._record(
                "final",
                {
                    "step": self.step,
                    "text": full[:FINAL_TEXT_LIMIT],
                    "headline": summary.headline,
                    "conclusion": summary.conclusion,
                    "chars": summary.chars,
                    "tokens_est": summary.tokens_est,
                    "tools_mentioned": list(summary.tools_mentioned),
                },
                FINAL_TEXT_LIMIT,
            )
        return summary
