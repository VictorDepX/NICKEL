from __future__ import annotations

import os
import shutil
import textwrap

_RESET = "\033[0m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_MAGENTA = "\033[95m"
_DIM = "\033[2m"


def _width() -> int:
    return max(60, min(shutil.get_terminal_size((88, 24)).columns, 120))


def _line(char: str = "═") -> str:
    return char * (_width() - 2)


def _print_box(title: str, message: str, color: str) -> None:
    inner_width = _width() - 4
    print(f"{color}╔{_line()}╗{_RESET}")
    print(f"{color}║ {title.ljust(inner_width)} ║{_RESET}")
    print(f"{color}╠{_line('─')}╣{_RESET}")
    for paragraph in message.splitlines() or [""]:
        wrapped = textwrap.wrap(paragraph, width=inner_width) or [""]
        for chunk in wrapped:
            print(f"{color}║ {chunk.ljust(inner_width)} ║{_RESET}")
    print(f"{color}╚{_line()}╝{_RESET}")


def print_banner() -> None:
    clear_screen()
    title = " NICKEL // RETRO TERMINAL "
    bar = "=" * max(10, (_width() - len(title)) // 2)
    print(f"{_MAGENTA}{bar}{title}{bar}{_RESET}")
    print(f"{_DIM}Conversa contínua ativa. Use /help para comandos.{_RESET}")


def print_user(message: str) -> None:
    _print_box("VOCÊ", message, _CYAN)


def print_nickel(message: str) -> None:
    _print_box("NICKEL", message or "(sem resposta)", _GREEN)


def print_info(message: str) -> None:
    print(f"{_YELLOW}{message}{_RESET}")


def print_error(message: str) -> None:
    print(f"{_RED}ERRO: {message}{_RESET}")


def print_pending(tool: str, action_id: str) -> None:
    info = (
        f"Ação pendente: {tool}\n"
        f"id: {action_id}\n"
        "Use /confirm para executar ou /cancel para descartar."
    )
    _print_box("CONFIRMAÇÃO", info, _YELLOW)


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")
