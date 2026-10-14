from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

from nickel.config import Settings
from nickel.core.db import Database
from nickel.core.llm import LLMReply, ToolCall
from nickel.core.outbound import Outbound
from nickel.integrations.obsidian import ObsidianVault
from nickel.services import Services
from nickel.skills.reminders import ReminderService


def run(coro):
    return asyncio.run(coro)


class FakeLLM:
    """Devolve respostas roteirizadas e guarda as mensagens recebidas."""

    def __init__(self, replies: list[LLMReply] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []

    def queue(self, *replies: LLMReply) -> None:
        self.replies.extend(replies)

    async def chat(self, messages, tools=None) -> LLMReply:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.replies:
            return LLMReply(content="(sem roteiro)")
        return self.replies.pop(0)

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "model": "fake", "model_present": True}


def say(text: str) -> LLMReply:
    return LLMReply(content=text)


def call(name: str, **arguments: Any) -> LLMReply:
    return LLMReply(content="", tool_calls=[ToolCall(name=name, arguments=arguments)])


class FakeWhatsApp:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[str] = []
        self.voice: list[bytes] = []

    async def send_text(self, text: str) -> bool:
        self.sent.append(text)
        return self.ok

    async def send_voice(self, ogg: bytes) -> bool:
        self.voice.append(ogg)
        return self.ok

    async def health(self) -> dict[str, Any]:
        return {"ready": True, "host": "5563999999999"}


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "Editora"
    (root / ".obsidian").mkdir(parents=True)
    (root / "00 Processos").mkdir()
    (root / "00 Processos" / "Fluxo de criação.md").write_text("# Fluxo de criação\n", encoding="utf-8")
    (root / "Home.md").write_text("# Editora\n", encoding="utf-8")
    return root


@pytest.fixture
def settings(tmp_path: Path, vault: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        timezone="America/Sao_Paulo",
        oauth_token_key=Fernet.generate_key().decode(),
        bridge_token="segredo",
        obsidian_vault_path=vault,
        voice_notify=False,
        music_auto_detect=True,
    )


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def services(settings: Settings, llm: FakeLLM) -> Services:
    services = Services.core(settings, llm, Database(":memory:"))
    services.obsidian = ObsidianVault(settings.obsidian_vault_path, settings.obsidian_notes_dir)
    services.whatsapp = FakeWhatsApp()
    services.outbound = Outbound(services)
    services.reminders = ReminderService(services)
    return services
