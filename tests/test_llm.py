from __future__ import annotations

from app.llm import _build_messages
from app.llm import _decode_llm_json
from app.llm import _parse_llm_choice


def test_decode_llm_json_parses_plain_json() -> None:
    decoded = _decode_llm_json('{"response":"ok","action":null}')
    assert decoded == {"response": "ok", "action": None}


def test_decode_llm_json_parses_markdown_fence() -> None:
    decoded = _decode_llm_json('```json\n{"response":"ok","action":null}\n```')
    assert decoded["response"] == "ok"


def test_decode_llm_json_parses_prefixed_text() -> None:
    decoded = _decode_llm_json('Aqui está: {"response":"ok","action":null}')
    assert decoded["action"] is None


def test_decode_llm_json_parses_content_array() -> None:
    decoded = _decode_llm_json([{"type": "text", "text": '{"response":"ok","action":null}'}])
    assert decoded["response"] == "ok"


def test_parse_llm_choice_reads_message_content_json() -> None:
    decoded = _parse_llm_choice({"content": '{"response":"beleza","action":null}'})
    assert decoded == {"response": "beleza", "action": None}


def test_parse_llm_choice_reads_structured_tool_call() -> None:
    decoded = _parse_llm_choice(
        {
            "content": None,
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "tasks.create",
                        "arguments": '{"title":"Comprar leite","notes":"integral"}',
                    },
                }
            ],
        }
    )

    assert decoded == {
        "response": "",
        "action": {
            "tool": "tasks.create",
            "payload": {"title": "Comprar leite", "notes": "integral"},
        },
    }


def test_build_messages_includes_history_for_conversation() -> None:
    messages = _build_messages(
        "E para amanhã?",
        forced_tool=None,
        history=[
            {"role": "assistant", "content": "Oi, em que posso ajudar?"},
            {"role": "user", "content": "Quais compromissos tenho hoje?"},
        ],
    )

    assert messages[1] == {"role": "assistant", "content": "Oi, em que posso ajudar?"}
    assert messages[2] == {"role": "user", "content": "Quais compromissos tenho hoje?"}
    assert messages[3] == {"role": "user", "content": "E para amanhã?"}
