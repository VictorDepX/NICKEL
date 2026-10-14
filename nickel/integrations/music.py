"""Reconhecimento musical (ShazamIO) e busca de links (Spotify → YouTube)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

Recognizer = Callable[[Path], Awaitable[dict[str, Any] | None]]
YouTubeSearch = Callable[[str], Awaitable[dict[str, Any] | None]]


@dataclass
class MusicMatch:
    title: str
    artist: str
    shazam_url: str | None = None
    spotify_url: str | None = None
    spotify_uri: str | None = None
    youtube_url: str | None = None

    @property
    def best_link(self) -> str | None:
        return self.spotify_url or self.youtube_url or self.shazam_url

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "spotify_url": self.spotify_url,
            "spotify_uri": self.spotify_uri,
            "youtube_url": self.youtube_url,
            "shazam_url": self.shazam_url,
        }

    def annotation(self) -> str:
        where = (
            f"Spotify: {self.spotify_url}" if self.spotify_url
            else f"YouTube: {self.youtube_url}" if self.youtube_url
            else "sem link no Spotify nem no YouTube"
        )
        return f"[Reconhecimento musical: '{self.title}' — {self.artist}. {where}]"


async def shazam_recognize(path: Path) -> dict[str, Any] | None:
    from shazamio import Shazam

    shazam = Shazam()
    method = getattr(shazam, "recognize", None) or getattr(shazam, "recognize_song")
    out = await method(str(path))
    track = (out or {}).get("track")
    if not track:
        return None
    return {"title": track.get("title", ""), "artist": track.get("subtitle", ""), "url": track.get("url")}


async def youtube_search(query: str) -> dict[str, Any] | None:
    def run() -> dict[str, Any] | None:
        import yt_dlp

        options = {"quiet": True, "skip_download": True, "extract_flat": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = (info or {}).get("entries") or []
        if not entries:
            return None
        entry = entries[0]
        url = entry.get("url") or entry.get("webpage_url")
        if not url or not str(url).startswith("http"):
            url = f"https://www.youtube.com/watch?v={entry.get('id')}"
        return {"title": entry.get("title"), "url": url}

    return await asyncio.to_thread(run)


class MusicFinder:
    def __init__(
        self,
        spotify: Any | None,
        recognizer: Recognizer = shazam_recognize,
        youtube: YouTubeSearch = youtube_search,
    ) -> None:
        self.spotify = spotify
        self.recognizer = recognizer
        self.youtube = youtube

    async def recognize(self, path: Path) -> MusicMatch | None:
        try:
            raw = await self.recognizer(path)
        except Exception:  # API não oficial: falha vira "não reconhecido"
            log.exception("Reconhecimento musical falhou")
            return None
        if not raw or not raw.get("title"):
            return None
        match = MusicMatch(title=raw["title"], artist=raw.get("artist", ""), shazam_url=raw.get("url"))
        await self.attach_links(match)
        return match

    async def attach_links(self, match: MusicMatch) -> MusicMatch:
        if self.spotify is not None and self.spotify.status().get("status") == "ready":
            try:
                query = f"track:{match.title} artist:{match.artist}" if match.artist else match.title
                results = await self.spotify.search(query, "track", 3)
                if not results and match.artist:
                    results = await self.spotify.search(f"{match.title} {match.artist}", "track", 3)
                if results:
                    match.spotify_url, match.spotify_uri = results[0]["url"], results[0]["uri"]
            except Exception:
                log.exception("Busca no Spotify falhou")
        if not match.spotify_url:
            try:
                found = await self.youtube(f"{match.title} {match.artist}".strip())
                if found:
                    match.youtube_url = found.get("url")
            except Exception:
                log.exception("Busca no YouTube falhou")
        return match
