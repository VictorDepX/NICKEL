"""Cliente do VoiceStudio (API compatível com OpenAI `/v1/audio/speech`)."""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
import wave
from pathlib import Path

import httpx

from nickel.config import Settings
from nickel.speech import playback
from nickel.speech.tts import TTSError, split_for_tts

__all__ = ["TTSError", "VoiceStudioSpeaker", "split_for_tts"]

log = logging.getLogger(__name__)

_DEFAULT_URL = "http://127.0.0.1:3900"
_MAX_INPUT = 4096
_CHUNK_LIMIT = 4000


def _error_message(response: httpx.Response) -> str:
    """Lê `error.message` no padrão OpenAI; senão usa o texto cru (até 200 caracteres)."""
    try:
        message = response.json()["error"]["message"]
        if isinstance(message, str) and message:
            return message
    except (ValueError, KeyError, TypeError):
        pass
    return response.text[:200] or response.reason_phrase


class VoiceStudioSpeaker:
    def __init__(
        self,
        settings: Settings,
        work_dir: Path,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.work_dir = work_dir
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._cancel = asyncio.Event()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self.settings.voicestudio_api_key:
                headers["Authorization"] = f"Bearer {self.settings.voicestudio_api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.settings.voicestudio_url or _DEFAULT_URL,
                headers=headers,
                transport=self._transport,
                timeout=httpx.Timeout(
                    self.settings.voicestudio_timeout_seconds, connect=5.0
                ),
            )
        return self._client

    async def _request_chunk(self, text: str) -> bytes:
        body = {
            "model": self.settings.voicestudio_model,
            "input": text[:_MAX_INPUT],
            "voice": self.settings.voicestudio_voice,
            "response_format": "wav",
            "speed": 1.0,
        }
        try:
            response = await self._get_client().post("/v1/audio/speech", json=body)
        except httpx.TimeoutException as exc:
            raise TTSError("VoiceStudio demorou demais para responder.") from exc
        except httpx.HTTPError as exc:
            raise TTSError(f"Não foi possível falar com o VoiceStudio: {type(exc).__name__}.") from exc
        if response.status_code >= 400:
            raise TTSError(f"VoiceStudio ({response.status_code}): {_error_message(response)}")
        return response.content

    @staticmethod
    def _concat_wavs(chunks: list[bytes], target: Path) -> None:
        params = None
        frames: list[bytes] = []
        for data in chunks:
            try:
                with wave.open(io.BytesIO(data), "rb") as reader:
                    current = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate())
                    if params is None:
                        params = current
                    elif current != params:
                        raise TTSError("formatos de áudio diferentes entre blocos")
                    frames.append(reader.readframes(reader.getnframes()))
            except wave.Error as exc:
                raise TTSError("VoiceStudio devolveu um áudio WAV inválido.") from exc
        assert params is not None
        with wave.open(str(target), "wb") as writer:
            writer.setnchannels(params[0])
            writer.setsampwidth(params[1])
            writer.setframerate(params[2])
            for frame in frames:
                writer.writeframes(frame)

    async def synthesize(self, text: str) -> Path:
        pieces = split_for_tts(text, _CHUNK_LIMIT)
        if not pieces:
            raise TTSError("Nada para falar depois da limpeza do texto.")
        audio = [await self._request_chunk(piece) for piece in pieces]
        self.work_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(suffix=".wav", dir=self.work_dir, delete=False)
        handle.close()
        target = Path(handle.name)
        try:
            if len(audio) == 1:
                target.write_bytes(audio[0])
            else:
                self._concat_wavs(audio, target)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target

    async def speak(self, text: str) -> None:
        pieces = split_for_tts(text, _CHUNK_LIMIT)
        if not pieces:
            return
        self._cancel.clear()
        for piece in pieces:
            if self._cancel.is_set():
                return
            wav = await self.synthesize(piece)
            try:
                if self._cancel.is_set():
                    return
                await playback.play_wav(wav)
            finally:
                wav.unlink(missing_ok=True)

    def stop(self) -> None:
        self._cancel.set()
        playback.stop_playback()

    async def health(self) -> dict:
        try:
            response = await self._get_client().get("/v1/models")
            if response.status_code >= 400:
                return {"ok": False, "detail": f"HTTP {response.status_code}"}
            data = response.json().get("data", [])
            return {"ok": True, "detail": f"{len(data)} modelos"}
        except httpx.TimeoutException:
            return {"ok": False, "detail": "tempo esgotado"}
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": f"sem conexão ({type(exc).__name__})"}
        except Exception as exc:  # health nunca levanta
            return {"ok": False, "detail": f"resposta inválida ({type(exc).__name__})"}

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
