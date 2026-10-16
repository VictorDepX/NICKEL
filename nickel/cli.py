"""CLI: `nickel serve | listen | chat | keys | doctor`."""

from __future__ import annotations

import argparse
import asyncio
import secrets
import shutil
import sys

import httpx

from nickel.config import load_settings


def _base_url(settings) -> str:
    return f"http://{settings.host}:{settings.port}"


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "nickel.app:main_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_level="info",
    )
    return 0


def cmd_listen(_args: argparse.Namespace) -> int:
    """Atalho de teclado: alterna gravar/parar no serviço em execução."""
    settings = load_settings()
    try:
        response = httpx.post(f"{_base_url(settings)}/voice/toggle", timeout=5)
        print(response.json().get("state"))
        return 0
    except httpx.HTTPError as exc:
        print(f"NICKEL não está rodando em {_base_url(settings)}: {exc}", file=sys.stderr)
        return 1


def cmd_chat(_args: argparse.Namespace) -> int:
    settings = load_settings()
    url = f"{_base_url(settings)}/api/chat"
    print("Conversa com o NICKEL (Ctrl+D para sair).")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            print()
            return 0
        if not text:
            continue
        try:
            response = httpx.post(url, json={"text": text}, timeout=settings.llm_timeout_seconds + 10)
            print(response.json().get("text"))
        except httpx.HTTPError as exc:
            print(f"Erro: {exc}", file=sys.stderr)


def cmd_keys(_args: argparse.Namespace) -> int:
    from cryptography.fernet import Fernet

    print(f"OAUTH_TOKEN_KEY={Fernet.generate_key().decode()}")
    print(f"BRIDGE_TOKEN={secrets.token_urlsafe(32)}")
    return 0


async def _doctor() -> int:
    from nickel.core.host import is_oracle_cloud, memory_used_percent
    from nickel.core.llm import LLMError, make_llm
    from nickel.services import module_available

    settings = load_settings()
    problems = 0

    def line(ok: bool, label: str, hint: str = "") -> None:
        nonlocal problems
        problems += 0 if ok else 1
        print(f"[{'ok' if ok else '!!'}] {label}" + (f" — {hint}" if hint and not ok else ""))

    provider = settings.llm_provider.lower()
    health: dict = {}
    try:
        client = make_llm(settings)
    except LLMError as exc:
        line(False, f"LLM ({provider})", str(exc))
    else:
        health = await client.health()
        await client.aclose()
    if provider == "ollama":
        line(health.get("ok", False), f"Ollama em {settings.llm_base_url}", "rode `ollama serve`")
        line(bool(health.get("model_present")), f"Modelo {settings.llm_model}", f"rode `ollama pull {settings.llm_model}`")
    elif health:
        label = "Endpoint RunPod" if health.get("provider") == "runpod" else f"Provedor em {settings.llm_base_url}"
        line(health.get("ok", False), f"{label} ({settings.llm_model})", health.get("detail") or "confira LLM_BASE_URL e LLM_API_KEY")
        if health.get("ok") and health.get("detail"):
            print(f"     {health['detail']}")
        if health.get("provider") == "openai":
            line(bool(health.get("model_present")), f"Modelo {settings.llm_model} no provedor", "confira LLM_MODEL")

    line(bool(settings.oauth_token_key), "OAUTH_TOKEN_KEY", "gere com `nickel keys`")
    line(bool(settings.bridge_token), "BRIDGE_TOKEN", "gere com `nickel keys`")
    vault_ok = bool(settings.obsidian_vault_path and settings.obsidian_vault_path.is_dir())
    line(vault_ok, f"Vault Obsidian ({settings.obsidian_vault_path})", "ajuste OBSIDIAN_VAULT_PATH / Syncthing")
    line(module_available("faster_whisper"), f"faster-whisper (STT {settings.stt_model}, {settings.stt_device})", "pip install -e '.[server]'")
    if settings.voice_enabled or settings.wa_voice_replies:
        line(module_available("piper"), "piper-tts (TTS)", "pip install -e '.[voice]'")
        voice_ok = bool(settings.tts_voice_path and settings.tts_voice_path.exists())
        line(voice_ok, f"Voz do Piper ({settings.tts_voice_path})", "baixe a voz (veja o README)")
    if settings.voice_enabled:
        line(module_available("sounddevice"), "sounddevice (microfone)", "pip install -e '.[voice]'")
    if settings.voice_notify:
        line(bool(shutil.which("notify-send")), "notify-send", "sudo apt install libnotify-bin")
    line(module_available("shazamio"), "shazamio (música)", "pip install -e '.[music]'")
    line(module_available("yt_dlp"), "yt-dlp (YouTube)", "pip install -e '.[music]'")
    line(bool(shutil.which("ffmpeg")), "ffmpeg", "sudo apt install ffmpeg")
    try:
        response = httpx.get(f"{settings.wa_bridge_url}/health", timeout=3)
        ready = response.json().get("ready", False)
    except (httpx.HTTPError, ValueError):
        ready = False
    line(ready, f"Bridge WhatsApp ({settings.wa_bridge_url})", "veja `journalctl --user -u nickel-whatsapp`")

    if is_oracle_cloud():
        used = memory_used_percent()
        if used is not None:
            line(
                used >= 25,
                f"Memória em uso na VM Oracle: {used:.0f}%",
                "abaixo de 20% por 7 dias (com CPU e rede baixas) a Oracle pode recuperar a VM; "
                "reduza a RAM da instância ou veja docs/deploy/oracle-runpod.md",
            )

    print("\nTudo certo." if problems == 0 else f"\n{problems} item(ns) pendente(s).")
    return 0 if problems == 0 else 1


def cmd_doctor(_args: argparse.Namespace) -> int:
    return asyncio.run(_doctor())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nickel", description="Assistente pessoal local.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Sobe a API, a UI e os serviços de fundo")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=cmd_serve)
    sub.add_parser("listen", help="Alterna gravar/parar (use num atalho de teclado)").set_defaults(func=cmd_listen)
    sub.add_parser("chat", help="Conversa por texto no terminal").set_defaults(func=cmd_chat)
    sub.add_parser("keys", help="Gera OAUTH_TOKEN_KEY e BRIDGE_TOKEN").set_defaults(func=cmd_keys)
    sub.add_parser("doctor", help="Verifica dependências e configuração").set_defaults(func=cmd_doctor)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
