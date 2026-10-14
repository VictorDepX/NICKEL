from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from nickel.core.llm import LLMError, OllamaClient, parse_reply
from nickel.integrations.music import MusicFinder, MusicMatch
from nickel.integrations.spotify import TOKEN_NAME, SpotifyClient, SpotifyError

from conftest import run


# ---------------------------------------------------------------- Ollama
def test_ollama_payload_and_tool_call_parsing(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "message": {
                "role": "assistant",
                "content": "<think>pensando</think>",
                "tool_calls": [{"function": {"name": "spotify_play", "arguments": '{"query": "Djavan"}'}}],
            },
            "done": True,
        })

    client = OllamaClient(settings, transport=httpx.MockTransport(handler))
    tools = [{"type": "function", "function": {"name": "spotify_play", "parameters": {}}}]
    reply = run(client.chat([{"role": "user", "content": "toca djavan", "images": ["AAA"]}], tools))
    assert seen["path"] == "/api/chat"
    body = seen["body"]
    assert body["model"] == "qwen3.6:27b" and body["stream"] is False and body["think"] is False
    assert body["options"]["num_ctx"] == 16384 and body["tools"] == tools
    assert body["messages"][0]["images"] == ["AAA"]
    assert reply.content == ""
    assert reply.tool_calls[0].name == "spotify_play" and reply.tool_calls[0].arguments == {"query": "Djavan"}


def test_ollama_errors(settings):
    client = OllamaClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    with pytest.raises(LLMError, match="500"):
        run(client.chat([{"role": "user", "content": "x"}]))


def test_parse_reply_ignores_malformed_calls():
    reply = parse_reply({"message": {"content": "ok", "tool_calls": [{"function": {"arguments": {}}}]}})
    assert reply.content == "ok" and reply.tool_calls == []


# ---------------------------------------------------------------- Spotify
def _spotify(settings, services, handler) -> SpotifyClient:
    configured = settings.with_overrides(spotify_client_id="cid", spotify_client_secret="sec")
    client = SpotifyClient(configured, services.tokens, transport=httpx.MockTransport(handler))
    services.tokens.put(TOKEN_NAME, {"access_token": "tok", "refresh_token": "ref", "expiry": "2099-01-01T00:00:00+00:00"})
    return client


def test_spotify_search_and_play(settings, services):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/v1/search":
            return httpx.Response(200, json={"tracks": {"items": [
                {"name": "Oceano", "uri": "spotify:track:1", "artists": [{"name": "Djavan"}],
                 "external_urls": {"spotify": "https://open.spotify.com/track/1"}}
            ]}})
        if request.url.path == "/v1/me/player/devices":
            return httpx.Response(200, json={"devices": [
                {"id": "phone", "type": "Smartphone", "is_active": False, "name": "Celular"},
                {"id": "pc", "type": "Computer", "is_active": False, "name": "Linux"},
            ]})
        if request.url.path == "/v1/me/player/play":
            assert json.loads(request.content) == {"uris": ["spotify:track:1"]}
            return httpx.Response(204)
        return httpx.Response(404)

    client = _spotify(settings, services, handler)
    results = run(client.search("oceano", "track", 50))
    assert results[0]["uri"] == "spotify:track:1"
    assert calls[0][2]["limit"] == "10"  # limite do Development Mode
    run(client.play(uris=["spotify:track:1"]))
    assert calls[-1][2] == {"device_id": "pc"}  # sem dispositivo ativo, prefere o computador


def test_spotify_no_device(settings, services):
    client = _spotify(settings, services, lambda r: httpx.Response(200, json={"devices": []}))
    with pytest.raises(SpotifyError) as exc:
        run(client.play())
    assert exc.value.code == "no_device"


def test_spotify_refreshes_expired_token(settings, services):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.spotify.com":
            assert b"grant_type=refresh_token" in request.content
            return httpx.Response(200, json={"access_token": "novo", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer novo"
        return httpx.Response(204)

    client = _spotify(settings, services, handler)
    services.tokens.put(TOKEN_NAME, {"access_token": "velho", "refresh_token": "ref", "expiry": "2000-01-01T00:00:00+00:00"})
    run(client.pause())
    assert services.tokens.get(TOKEN_NAME)["refresh_token"] == "ref"


# ---------------------------------------------------------------- Música
class FakeSpotify:
    def __init__(self, ready=True, results=None):
        self.ready = ready
        self.results = results or []
        self.queries = []

    def status(self):
        return {"status": "ready" if self.ready else "needs_connection"}

    async def search(self, query, kind, limit):
        self.queries.append(query)
        return self.results


def test_music_prefers_spotify(tmp_path: Path):
    async def recognizer(path):
        return {"title": "Trem das Onze", "artist": "Adoniran Barbosa", "url": "https://shazam/x"}

    async def youtube(query):
        raise AssertionError("não deveria buscar no YouTube")

    spotify = FakeSpotify(results=[{"url": "https://open.spotify.com/track/9", "uri": "spotify:track:9"}])
    match = run(MusicFinder(spotify, recognizer, youtube).recognize(tmp_path / "a.ogg"))
    assert match.spotify_uri == "spotify:track:9"
    assert spotify.queries == ["track:Trem das Onze artist:Adoniran Barbosa"]
    assert "Spotify: https://open.spotify.com/track/9" in match.annotation()


def test_music_falls_back_to_youtube(tmp_path: Path):
    async def recognizer(path):
        return {"title": "Música rara", "artist": "Banda local"}

    async def youtube(query):
        return {"url": "https://www.youtube.com/watch?v=abc", "title": query}

    match = run(MusicFinder(FakeSpotify(results=[]), recognizer, youtube).recognize(tmp_path / "a.ogg"))
    assert match.spotify_url is None and match.youtube_url == "https://www.youtube.com/watch?v=abc"
    match = run(MusicFinder(None, recognizer, youtube).recognize(tmp_path / "a.ogg"))
    assert match.best_link == "https://www.youtube.com/watch?v=abc"


def test_music_recognizer_failure_is_none(tmp_path: Path):
    async def broken(path):
        raise RuntimeError("API mudou")

    assert run(MusicFinder(None, broken).recognize(tmp_path / "a.ogg")) is None


def test_match_annotation_without_links():
    assert "sem link" in MusicMatch("X", "Y").annotation()
