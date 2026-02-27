from __future__ import annotations

from app.orchestrator import decide_tool, is_high_confidence


def test_decide_tool_marks_ambiguous_intent_low_confidence() -> None:
    decision = decide_tool("quero ver agenda e mandar email")

    assert decision.tool is None
    assert decision.reason.startswith("ambiguous_tool_match:")
    assert decision.confidence < 0.75
    assert not is_high_confidence(decision)


def test_decide_tool_for_non_tool_phrase_returns_no_tool() -> None:
    decision = decide_tool("como você está hoje?")

    assert decision.tool is None
    assert decision.reason == "no_tool_match"
    assert decision.confidence == 0.0
    assert not is_high_confidence(decision)
