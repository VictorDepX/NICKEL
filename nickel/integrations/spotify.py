"""Spotify Web API: OAuth (authorization code) + playback + busca.

Desde fev/2026 o Development Mode exige Premium do dono do app e limita a busca a 10 itens.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any
from urllib.parse import urlencode

import httpx

from nickel.config import Settings
from nickel.core.stores import TokenStore

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
TOKEN_NAME = "spotify"
SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
)


class SpotifyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SpotifyClient:
    def __init__(
        self,
        settings: Settings,
        tokens: TokenStore,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.tokens = tokens
        self._states: set[str] = set()
        self._http = httpx.AsyncClient(timeout=15, transport=transport)

    # ------------------------------------------------------------ status / OAuth
    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.spotify_client_id:
            missing.append("SPOTIFY_CLIENT_ID")
        if not self.settings.spotify_client_secret:
            missing.append("SPOTIFY_CLIENT_SECRET")
        if not self.tokens.available:
            missing.append("OAUTH_TOKEN_KEY")
        return missing

    def status(self) -> dict[str, Any]:
        missing = self.missing_config()
        if missing:
            return {"status": "needs_configuration", "missing": missing,
                    "message": f"Configure {', '.join(missing)} no .env."}
        if not self.tokens.get(TOKEN_NAME):
            return {"status": "needs_connection", "connect_url": "/auth/spotify/start",
                    "message": "Conecte o Spotify pela UI local (Conexões)."}
        return {"status": "ready"}

    def start(self) -> str:
        if self.missing_config():
            raise SpotifyError("not_configured", self.status()["message"])
        state = token_urlsafe(24)
        self._states.add(state)
        params = {
            "response_type": "code",
            "client_id": self.settings.spotify_client_id,
            "scope": " ".join(SCOPES),
            "redirect_uri": self.settings.spotify_redirect_uri,
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def finish(self, code: str, state: str) -> None:
        if state not in self._states:
            raise ValueError("Estado OAuth inválido ou expirado. Recomece a conexão.")
        self._states.discard(state)
        payload = await self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": self.settings.spotify_redirect_uri}
        )
        self._store(payload)

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        response = await self._http.post(
            TOKEN_URL, data=data, auth=(self.settings.spotify_client_id or "", self.settings.spotify_client_secret or "")
        )
        if response.status_code >= 400:
            raise SpotifyError("oauth_failed", f"Spotify recusou o token ({response.status_code}).")
        return response.json()

    def _store(self, payload: dict[str, Any]) -> None:
        existing = self.tokens.get(TOKEN_NAME) or {}
        expires_in = int(payload.get("expires_in", 3600))
        self.tokens.put(
            TOKEN_NAME,
            {
                "access_token": payload.get("access_token"),
                "refresh_token": payload.get("refresh_token") or existing.get("refresh_token"),
                "expiry": (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat(),
            },
        )

    async def _access_token(self) -> str:
        token = self.tokens.get(TOKEN_NAME)
        if not token:
            raise SpotifyError("not_connected", self.status()["message"])
        expiry = datetime.fromisoformat(token["expiry"]) if token.get("expiry") else None
        if expiry is None or expiry <= datetime.now(timezone.utc) + timedelta(seconds=60):
            if not token.get("refresh_token"):
                raise SpotifyError("not_connected", "Token do Spotify expirou. Reconecte pela UI.")
            refreshed = await self._token_request(
                {"grant_type": "refresh_token", "refresh_token": token["refresh_token"]}
            )
            self._store(refreshed)
            token = self.tokens.get(TOKEN_NAME) or {}
        return token["access_token"]

    # ------------------------------------------------------------ API
    async def _api(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        headers = {"Authorization": f"Bearer {await self._access_token()}"}
        response = await self._http.request(method, f"{API_URL}{path}", headers=headers, **kwargs)
        if response.status_code == 204 or not response.content:
            if response.status_code >= 400:
                raise self._error(response)
            return None
        if response.status_code >= 400:
            raise self._error(response)
        return response.json()

    @staticmethod
    def _error(response: httpx.Response) -> SpotifyError:
        reason = message = ""
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict):
                reason, message = error.get("reason", ""), error.get("message", "")
        except ValueError:
            pass
        if response.status_code == 404 or reason == "NO_ACTIVE_DEVICE":
            return SpotifyError("no_device", "Nenhum dispositivo Spotify ativo. Abra o Spotify em algum aparelho.")
        if response.status_code == 403:
            return SpotifyError("forbidden", message or "Spotify recusou a ação (Premium necessário?).")
        if response.status_code == 401:
            return SpotifyError("not_connected", "Spotify recusou o token. Reconecte pela UI.")
        if response.status_code == 429:
            return SpotifyError("rate_limited", "Limite de requisições do Spotify atingido. Tente em instantes.")
        return SpotifyError("api_error", f"Spotify respondeu {response.status_code}: {message or response.text[:120]}")

    async def devices(self) -> list[dict[str, Any]]:
        data = await self._api("GET", "/me/player/devices") or {}
        return data.get("devices", [])

    async def pick_device(self) -> str:
        devices = await self.devices()
        if not devices:
            raise SpotifyError("no_device", "Nenhum dispositivo Spotify disponível. Abra o Spotify em algum aparelho.")
        preferred = (self.settings.spotify_device_name or "").lower()
        for rule in (
            lambda d: preferred and d.get("name", "").lower() == preferred,
            lambda d: d.get("is_active"),
            lambda d: str(d.get("type", "")).lower() == "computer",
            lambda d: True,
        ):
            for device in devices:
                if rule(device) and not device.get("is_restricted"):
                    return device["id"]
        raise SpotifyError("no_device", "Os dispositivos Spotify encontrados não aceitam controle remoto.")

    async def search(self, query: str, kind: str = "track", limit: int = 5) -> list[dict[str, Any]]:
        params = {"q": query, "type": kind, "limit": max(1, min(limit, 10)), "market": self.settings.spotify_market}
        data = await self._api("GET", "/search", params=params) or {}
        items = (data.get(f"{kind}s") or {}).get("items") or []
        results = []
        for item in items:
            if not item:
                continue
            artists = ", ".join(a.get("name", "") for a in item.get("artists", []) or [])
            if not artists and kind == "playlist":
                artists = (item.get("owner") or {}).get("display_name", "")
            results.append(
                {
                    "name": item.get("name"),
                    "artists": artists,
                    "uri": item.get("uri"),
                    "url": (item.get("external_urls") or {}).get("spotify"),
                }
            )
        return results

    async def play(self, *, uris: list[str] | None = None, context_uri: str | None = None) -> None:
        device_id = await self.pick_device()
        body: dict[str, Any] = {}
        if uris:
            body["uris"] = uris
        if context_uri:
            body["context_uri"] = context_uri
        await self._api("PUT", "/me/player/play", params={"device_id": device_id}, json=body or None)

    async def pause(self) -> None:
        await self._api("PUT", "/me/player/pause")

    async def next(self) -> None:
        await self._api("POST", "/me/player/next")

    async def previous(self) -> None:
        await self._api("POST", "/me/player/previous")

    async def now_playing(self) -> dict[str, Any] | None:
        data = await self._api("GET", "/me/player/currently-playing")
        if not data or not data.get("item"):
            return None
        item = data["item"]
        return {
            "name": item.get("name"),
            "artists": ", ".join(a.get("name", "") for a in item.get("artists", [])),
            "url": (item.get("external_urls") or {}).get("spotify"),
            "is_playing": data.get("is_playing", False),
        }

    async def aclose(self) -> None:
        await self._http.aclose()
