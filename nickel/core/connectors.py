"""Conectores e pipelines para a GUI: só o que está configurado aparece, cada um com um nível.

Níveis: `ok` (funcionando), `warn` (configurado, falta um passo do usuário) e `bad`
(configurado, mas fora do ar). Integração sem configuração não entra na lista.
O NICKEL não tem servidores MCP; por isso não há seção de MCP.
"""

from __future__ import annotations

from typing import Any

UNCONFIGURED = {"disabled", "needs_configuration"}


def _item(id_: str, name: str, level: str, detail: str = "", action: str | None = None) -> dict[str, Any]:
    item = {"id": id_, "name": name, "level": level, "detail": detail}
    if action:
        item["action"] = action
    return item


def _oauth(id_: str, name: str, info: dict[str, Any], path: str) -> dict[str, Any] | None:
    status = info.get("status")
    if status in UNCONFIGURED or status is None:
        return None
    if status == "ready":
        return _item(id_, name, "ok", "conectado")
    if status == "needs_connection":
        return _item(id_, name, "warn", "falta autorizar", path)
    return _item(id_, name, "bad", str(info.get("message") or status))


def build_connectors(snapshot: dict[str, Any], *, whatsapp: bool, music: bool, reminders: bool, obsidian_path: str) -> dict[str, Any]:
    llm = snapshot.get("llm") or {}
    voice = snapshot.get("voice") or {}
    tts = voice.get("tts") or {}
    wa = snapshot.get("whatsapp") or {}

    connectors: list[dict[str, Any]] = []
    llm_ok = bool(llm.get("ok")) and llm.get("model_present", True) is not False
    connectors.append(_item("llm", f"Modelo {llm.get('model') or ''}".strip(), "ok" if llm_ok else "bad", str(llm.get("detail") or "")))
    if tts.get("provider"):
        connectors.append(_item("tts", f"Voz ({tts['provider']})", "ok" if tts.get("ok") else "bad", str(tts.get("detail") or "")))
    if voice.get("stt"):
        connectors.append(_item("stt", "Transcrição de voz", "ok", "faster-whisper"))
    if whatsapp:
        connectors.append(_item("whatsapp", "WhatsApp", "ok" if wa.get("ready") else "bad", str(wa.get("detail") or "")))
    for item in (
        _oauth("google", "Google (Gmail + Agenda)", snapshot.get("google") or {}, "/auth/google/start"),
        _oauth("spotify", "Spotify", snapshot.get("spotify") or {}, "/auth/spotify/start"),
    ):
        if item:
            connectors.append(item)
    if obsidian_path:
        available = bool((snapshot.get("obsidian") or {}).get("available"))
        connectors.append(_item("obsidian", "Obsidian", "ok" if available else "bad", "vault encontrado" if available else f"vault não encontrado: {obsidian_path}"))
    if music:
        connectors.append(_item("music", "Reconhecimento musical", "ok", "shazamio"))

    pipelines: list[dict[str, Any]] = []
    if reminders:
        pipelines.append(_item("reminders", "Lembretes", "ok", "agendador ativo"))
    if whatsapp:
        pipelines.append(_item("whatsapp-in", "WhatsApp → NICKEL → resposta", "ok" if wa.get("ready") else "bad", "ponte no ar" if wa.get("ready") else "ponte fora do ar"))
    if voice.get("stt") or voice.get("microphone"):
        ready = bool(voice.get("available"))
        pipelines.append(_item("voice", "Microfone → transcrição → NICKEL → fala", "ok" if ready else "warn", str(voice.get("state") or "") if ready else "falta microfone ou transcrição"))
    if tts.get("provider"):
        pipelines.append(_item("speech", "Resposta → voz", "ok" if tts.get("ok") else "bad", "Falar respostas e botão Ouvir"))
    return {"connectors": connectors, "pipelines": pipelines}
