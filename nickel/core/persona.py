"""Monta o system prompt: persona canônica (docs/Nickel) + regras de canal + contexto do momento."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # pragma: no cover
    from nickel.core.workspaces import Workspace

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "docs" / "Nickel"
_FALLBACK = "You are Nickel, an adult, pragmatic personal assistant. Be brief and precise."

_WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def now_stamp(timezone: str, now: datetime | None = None) -> str:
    """Data e hora atuais para ir junto da mensagem do usuário.

    Modelos menores (visto com o Gemma 4) copiam datas do histórico; repetir "agora" na
    última mensagem, onde a atenção é maior, evita lembretes no dia errado.
    """
    tz = ZoneInfo(timezone)
    current = (now or datetime.now(tz)).astimezone(tz)
    return f"[agora: {_WEEKDAYS[current.weekday()]}, {current.strftime('%d/%m/%Y %H:%M')}]"

CHANNEL_RULES = {
    "whatsapp": (
        "Canal: WhatsApp. Responda em texto curto. Formatação do WhatsApp apenas: *negrito*, _itálico_, "
        "listas com hífen. Sem títulos markdown, sem tabelas. Links por extenso."
    ),
    "voice": (
        "Canal: voz. A resposta será falada em voz alta. Máximo de duas ou três frases. "
        "Sem markdown, sem listas, sem links, sem emojis. Números e horários por extenso quando ajudar a fala."
    ),
    "ui": "Canal: interface local. Markdown simples permitido.",
}

TOOL_RULES = """\
Regras operacionais:
- Responda sempre em português do Brasil.
- Use tools só para ações reais ou dados verificáveis. Nunca diga que fez algo sem o resultado da tool com ok=true.
- Para guardar algo na memória, chame memory_save direto; o NICKEL já pede a confirmação ao usuário. Não pergunte antes em texto.
- Depois de uma tool, relate o que mudou em uma frase. Se falhou, diga o motivo e a próxima opção.
- Datas relativas ("amanhã às 9", "sexta à noite") viram ISO 8601 com o fuso do usuário, a partir do [agora: …] no início da mensagem do usuário. \
"À noite" sem hora = 20:00; "de manhã" = 09:00; "à tarde" = 15:00. \
"Daqui a N minutos/horas" soma N à data e hora de [agora: …], nunca a datas ou horários do histórico.
- Pensamento avulso, ideia, desabafo para registrar ou pedido de "anota": use notes_capture. \
Dê um título curto, organize o conteúdo em markdown limpo, corrija só a transcrição, sem inventar nada. \
Em links, só cite notas que o usuário mencionou.
- "Me lembra de…": use reminder_create.
- Mensagens com "[Reconhecimento musical: …]" já trazem a música identificada e os links: informe título, artista e o link. \
Para identificar uma música tocando perto do PC, use music_recognize.
- Algumas tools exigem confirmação do usuário; o sistema cuida disso. Não peça confirmação por conta própria para as demais.
- Se faltar um dado indispensável, pergunte uma coisa só.
"""


@lru_cache(maxsize=4)
def _load(name: str, directory: str) -> str:
    path = Path(directory) / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def prompts_dir() -> Path:
    override = os.environ.get("NICKEL_PROMPTS_DIR")
    return Path(override) if override else _DEFAULT_DIR


def build_system_prompt(
    *,
    channel: str,
    timezone: str,
    now: datetime | None = None,
    memory: list[dict[str, str]] | None = None,
    workspace: "Workspace | None" = None,
) -> str:
    directory = str(prompts_dir())
    base = _load("system_prompt_text.md", directory) or _FALLBACK
    parts = [base]
    if workspace is not None and workspace.instructions:
        parts.append(f"Workspace ativo: {workspace.name}.\n{workspace.instructions}")
    if channel == "voice":
        voice = _load("system_prompt_voice.md", directory)
        if voice:
            parts.append(voice)
    parts.append(TOOL_RULES)
    parts.append(CHANNEL_RULES.get(channel, CHANNEL_RULES["ui"]))

    tz = ZoneInfo(timezone)
    current = (now or datetime.now(tz)).astimezone(tz)
    # Sem hora aqui: o system prompt precisa ficar idêntico entre turnos para o llama-server
    # reaproveitar o cache do prompt. A data/hora vai em `now_stamp` na mensagem do usuário.
    parts.append(
        f"Fuso do usuário: {timezone} (UTC{current.strftime('%z')[:3]}:{current.strftime('%z')[3:]}). "
        "A data e a hora atuais vêm em [agora: …] no início da mensagem do usuário."
    )
    if memory:
        lines = "\n".join(f"- {item['key']}: {item['value']}" for item in memory)
        parts.append(f"Preferências salvas pelo usuário:\n{lines}")
    return "\n\n".join(parts)
