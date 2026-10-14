"""Canal WhatsApp: recebe da bridge (open-wa), monta o turno e devolve a resposta."""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from nickel.config import Settings
from nickel.core.agent import Agent, Turn

if TYPE_CHECKING:  # pragma: no cover
    from nickel.services import Services

log = logging.getLogger(__name__)

AUDIO_TYPES = {"ptt", "audio"}
IMAGE_TYPES = {"image"}
TEXT_TYPES = {"chat"}


class WhatsAppClient:
    """Fala com a bridge Node (whatsapp-bridge/) por HTTP local."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.wa_bridge_url.rstrip("/"),
            timeout=30,
            transport=transport,
            headers={"X-Nickel-Token": settings.bridge_token or ""},
        )

    async def send_text(self, text: str) -> bool:
        try:
            response = await self._http.post("/send", json={"text": text})
            return response.status_code < 300
        except httpx.HTTPError:
            log.warning("Bridge do WhatsApp indisponível para envio de texto.")
            return False

    async def send_voice(self, ogg: bytes) -> bool:
        try:
            response = await self._http.post(
                "/send-voice", json={"audio_b64": base64.b64encode(ogg).decode(), "mime": "audio/ogg; codecs=opus"}
            )
            return response.status_code < 300
        except httpx.HTTPError:
            return False

    async def health(self) -> dict[str, Any]:
        try:
            response = await self._http.get("/health", timeout=3)
            return response.json() if response.status_code < 300 else {"ready": False}
        except (httpx.HTTPError, ValueError):
            return {"ready": False, "detail": "bridge offline"}

    async def aclose(self) -> None:
        await self._http.aclose()


def prune_media(media_dir: Path, days: int = 30) -> int:
    """Apaga mídias recebidas há mais de `days` dias. Devolve quantas apagou."""
    if not media_dir.exists():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for path in media_dir.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _extension(mime: str | None, fallback: str) -> str:
    if not mime:
        return fallback
    guessed = mimetypes.guess_extension(mime.split(";")[0].strip())
    return guessed or fallback


class WhatsAppChannel:
    def __init__(self, services: "Services", agent: Agent) -> None:
        self.services = services
        self.agent = agent

    def _save_media(self, message_id: str, media_b64: str, mime: str | None, fallback_ext: str) -> Path:
        media_dir = self.services.settings.media_dir
        media_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(ch for ch in message_id if ch.isalnum())[-40:] or "media"
        path = media_dir / f"wa-{safe_id}{_extension(mime, fallback_ext)}"
        path.write_bytes(base64.b64decode(media_b64))
        return path

    async def build_turn(self, payload: dict[str, Any]) -> Turn | str:
        """Converte a mensagem da bridge num Turn. Devolve str quando a resposta é direta (sem LLM)."""
        kind = payload.get("type", "chat")
        message_id = str(payload.get("id", ""))
        text = (payload.get("body") if kind in TEXT_TYPES else payload.get("caption")) or ""
        media = payload.get("media_b64")
        mime = payload.get("mimetype")

        if kind in TEXT_TYPES:
            return Turn(channel="whatsapp", text=text.strip())

        if kind in IMAGE_TYPES:
            if not media:
                return "Não consegui baixar a imagem. Envie de novo."
            path = self._save_media(message_id, media, mime, ".jpg")
            return Turn(
                channel="whatsapp",
                text=text.strip() or "(imagem sem legenda)",
                images=[media],
                attachments=[{"type": "image", "path": str(path), "mime": mime}],
            )

        if kind in AUDIO_TYPES:
            if not media:
                return "Não consegui baixar o áudio. Envie de novo."
            path = self._save_media(message_id, media, mime, ".ogg")
            transcript, match = await asyncio.gather(self._transcribe(path), self._recognize(path))
            spoken = transcript or ""
            llm_parts = [f"[Áudio] {spoken}" if spoken else "[Áudio sem fala reconhecível]"]
            if match:
                llm_parts.append(match.annotation())
            return Turn(
                channel="whatsapp",
                text=spoken or "(áudio)",
                llm_text="\n".join(llm_parts),
                attachments=[{"type": "audio", "path": str(path), "mime": mime}],
                last_audio_path=path,
            )

        return "Ainda não processo esse tipo de mensagem. Mande texto, áudio ou foto."

    async def _transcribe(self, path: Path) -> str | None:
        stt = self.services.stt
        if stt is None:
            return None
        try:
            return await stt.transcribe(path)
        except Exception:
            log.exception("Transcrição falhou")
            return None

    async def _recognize(self, path: Path):
        music = self.services.music
        if music is None or not self.services.settings.music_auto_detect:
            return None
        return await music.recognize(path)

    async def handle_inbound(self, payload: dict[str, Any]) -> str | None:
        message_id = str(payload.get("id") or "")
        if message_id and self.services.dedup.seen(message_id):
            return None
        self.services.audit.record("whatsapp", "inbound", "received", {"type": payload.get("type"), "id": message_id})
        client = self.services.whatsapp
        try:
            turn = await self.build_turn(payload)
            if isinstance(turn, str):
                reply_text = turn
            else:
                reply = await self.agent.handle(turn)
                reply_text = reply.text
                if (
                    self.services.settings.wa_voice_replies
                    and turn.last_audio_path is not None
                    and self.services.tts is not None
                ):
                    await self._send_voice(reply_text)
        except Exception as exc:
            log.exception("Falha ao processar mensagem do WhatsApp")
            reply_text = f"Erro interno ao processar a mensagem: {exc}"
        if client is not None:
            await client.send_text(reply_text)
        return reply_text

    async def _send_voice(self, text: str) -> None:
        from nickel.speech.tts import wav_to_ogg_opus

        try:
            wav = await self.services.tts.synthesize(text)
            try:
                ogg = await wav_to_ogg_opus(wav)
            finally:
                wav.unlink(missing_ok=True)
            await self.services.whatsapp.send_voice(ogg)
        except Exception:
            log.exception("Resposta em áudio falhou; segue só o texto")
