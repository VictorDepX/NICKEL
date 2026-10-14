"""Mensagens iniciadas pelo NICKEL (lembretes): WhatsApp e, como reserva, notificação no desktop."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from nickel.services import Services

log = logging.getLogger(__name__)


async def desktop_notify(title: str, body: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    try:
        process = await asyncio.create_subprocess_exec("notify-send", "-a", "NICKEL", title, body)
        return await process.wait() == 0
    except OSError:
        return False


class Outbound:
    def __init__(self, services: "Services") -> None:
        self.services = services

    async def notify(self, text: str, *, channel: str = "lembrete") -> bool:
        delivered = False
        if self.services.whatsapp is not None:
            delivered = await self.services.whatsapp.send_text(text)
        if self.services.settings.voice_notify:
            delivered = await desktop_notify("NICKEL", text) or delivered
        if delivered:
            self.services.conversations.add("assistant", text, channel=channel)
        self.services.audit.record("outbound", channel, "ok" if delivered else "undelivered", {"text": text})
        return delivered
