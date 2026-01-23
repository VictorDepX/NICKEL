from __future__ import annotations

import os


def print_user(message: str) -> None:
    print(f"USER > {message}")


def print_nickel(message: str) -> None:
    print(f"NICKEL > {message}")


def print_info(message: str) -> None:
    print(message)


def print_error(message: str) -> None:
    print(f"ERROR: {message}")


def print_pending(summary: str) -> None:
    print("PENDING:")
    print(summary)
    print("[/confirm] to execute | [/cancel] to discard")


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")
