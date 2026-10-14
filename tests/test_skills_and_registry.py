from __future__ import annotations

import pytest

from nickel.core.skills import ToolRegistry, ToolResult, validate_arguments
from nickel.integrations.google import GoogleAuth
from nickel.integrations.spotify import SpotifyClient
from nickel.skills import build_registry


def test_validate_arguments_coerces_and_reports():
    schema = {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "flag": {"type": "boolean"},
            "kind": {"type": "string", "enum": ["a", "b"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "text": {"type": "string"},
        },
        "required": ["text"],
    }
    clean, errors = validate_arguments(
        schema, {"n": "10", "flag": "sim", "kind": "a", "tags": "x, y", "text": "oi", "extra": 1}
    )
    assert errors == []
    assert clean == {"n": 10, "flag": True, "kind": "a", "tags": ["x", "y"], "text": "oi"}

    _, errors = validate_arguments(schema, {"n": "dez", "kind": "z"})
    assert "'n' deveria ser integer" in errors
    assert any("'kind' deve ser um de" in e for e in errors)
    assert "'text' é obrigatório" in errors


def test_booleans_are_not_integers():
    _, errors = validate_arguments({"properties": {"n": {"type": "integer"}}}, {"n": True})
    assert errors == ["'n' deveria ser integer"]


def test_duplicate_tool_is_rejected():
    registry = ToolRegistry()

    @registry.add("x", "x")
    async def x(ctx, args):
        return ToolResult(True, "x")

    with pytest.raises(ValueError):
        registry.add("x", "outra")(x)


def test_schema_format_and_names_are_ollama_safe():
    registry = build_registry()
    for name in registry.names():
        assert name.replace("_", "").isalnum(), name
    schema = registry.get("reminder_create").schema()
    assert schema["type"] == "function"
    assert schema["function"]["parameters"]["required"] == ["text", "when"]


def test_tools_hidden_when_integration_not_configured(services, settings):
    registry = build_registry()
    services.google = GoogleAuth(settings.with_overrides(google_client_id=None), services.tokens)
    services.spotify = SpotifyClient(settings.with_overrides(spotify_client_id=None), services.tokens)
    names = {tool.name for tool in registry.available(services)}
    assert "notes_capture" in names and "reminder_create" in names
    assert not any(n.startswith(("email_", "calendar_", "spotify_")) for n in names)
    assert "music_recognize" not in names  # sem shazamio/MusicFinder

    services.google = GoogleAuth(
        settings.with_overrides(google_client_id="id", google_client_secret="s"), services.tokens
    )
    names = {tool.name for tool in registry.available(services)}
    assert "email_send" in names


def test_confirmation_flags():
    registry = build_registry()
    confirm = {name for name in registry.names() if registry.get(name).confirm}
    assert confirm == {"email_send", "calendar_create", "calendar_update", "memory_save"}
