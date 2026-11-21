from __future__ import annotations

from nickel.core.reasoning import ReasoningTracker, summarize_reasoning


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def record(self, kind, name, status, detail=None, **kw):
        self.events.append((kind, name, status, detail, kw))
        return {}


def test_summary_headline_conclusion_and_tools():
    text = "Preciso entender o pedido. Vou chamar reminder_create para agendar! Depois confirmo ao usuário."
    s = summarize_reasoning(text, ["note_add", "reminder_create"])
    assert s.headline == "Preciso entender o pedido."
    assert s.conclusion == "Depois confirmo ao usuário."
    assert s.chars == len(text)
    assert s.tokens_est == -(-len(text) // 4)
    assert s.tools_mentioned == ("reminder_create",)


def test_summary_truncates_headline_at_140_chars():
    s = summarize_reasoning("a" * 300 + ".")
    assert len(s.headline) == 140
    assert s.headline.endswith("…")
    assert s.conclusion == s.headline


def test_progress_is_throttled():
    audit, clock = FakeAudit(), FakeClock()
    t = ReasoningTracker(audit, step=1, clock=clock)
    for _ in range(50):
        t.feed("reasoning", "pensando ")
        clock.now += 0.002
    progress = [e for e in audit.events if e[2] == "progress"]
    assert len(progress) == 1
    clock.now += 0.5
    t.feed("reasoning", "mais")
    assert len([e for e in audit.events if e[2] == "progress"]) == 2
    detail = audit.events[-1][3]
    assert {"step", "chars", "tokens_est", "headline", "tail", "content_chars"} <= set(detail)


def test_content_channel_does_not_emit_reasoning_events():
    audit = FakeAudit()
    t = ReasoningTracker(audit, step=1, clock=FakeClock())
    t.feed("content", "olá")
    assert t.finish().chars == 0
    assert [e[2] for e in audit.events] == ["answering"]  # só o início da resposta, nada de raciocínio


def test_final_event_keeps_up_to_4000_chars_and_emitted_once():
    audit = FakeAudit()
    t = ReasoningTracker(audit, step=2, clock=FakeClock())
    t.feed("reasoning", "x" * 5000)
    s1 = t.finish()
    s2 = t.finish()
    assert s1 == s2
    finals = [e for e in audit.events if e[2] == "final"]
    assert len(finals) == 1
    assert finals[0][4]["text_limit"] == 4000
    assert len(finals[0][3]["text"]) <= 4000
    assert finals[0][3]["chars"] == 5000


def test_finish_without_reasoning_emits_nothing():
    audit = FakeAudit()
    ReasoningTracker(audit, step=1, clock=FakeClock()).finish()
    assert audit.events == []


def test_audit_failure_never_raises():
    class Boom:
        def record(self, *a, **k):
            raise RuntimeError("x")

    t = ReasoningTracker(Boom(), step=1, clock=FakeClock())
    t.feed("reasoning", "oi")
    t.finish()


def test_whitespace_only_reasoning_emits_no_progress_or_final():
    audit = FakeAudit()
    tracker = ReasoningTracker(audit, step=1, clock=FakeClock())
    tracker.feed("reasoning", "\n")
    tracker.feed("reasoning", "  \n\t")
    tracker.feed("content", "Feito.")
    tracker.finish()
    assert [e[2] for e in audit.events] == ["answering"]


def test_progress_starts_once_reasoning_has_text():
    audit = FakeAudit()
    tracker = ReasoningTracker(audit, step=0, clock=FakeClock())
    tracker.feed("reasoning", "\n")
    tracker.feed("reasoning", "Penso.")
    tracker.finish()
    statuses = [e[2] for e in audit.events]
    assert statuses == ["progress", "final"]
    assert audit.events[0][3]["chars"] == len("\nPenso.")


def test_answering_is_recorded_once_on_first_real_content_delta():
    audit = FakeAudit()
    tracker = ReasoningTracker(audit, step=3, clock=FakeClock())
    tracker.feed("reasoning", "Penso.")
    tracker.feed("content", "")
    tracker.feed("content", "\n  ")
    assert [e[2] for e in audit.events] == ["progress"]
    tracker.feed("content", "Olá")
    tracker.feed("content", " mundo")
    tracker.feed("reasoning", " mais")
    tracker.finish()
    answering = [e for e in audit.events if e[2] == "answering"]
    assert len(answering) == 1
    assert answering[0][:4] == ("reasoning", "model", "answering", {"step": 3})
    assert [e[2] for e in audit.events] == ["progress", "answering", "final"]


def test_reasoning_only_step_never_records_answering():
    audit = FakeAudit()
    tracker = ReasoningTracker(audit, step=0, clock=FakeClock())
    tracker.feed("reasoning", "Vou chamar a ferramenta.")
    tracker.finish()
    assert "answering" not in [e[2] for e in audit.events]
