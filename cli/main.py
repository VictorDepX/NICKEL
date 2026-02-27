from __future__ import annotations

import os
import sys
from typing import Callable

import requests

from cli.api_client import NickelAPIClient
from cli.session_store import SessionState, load_session, save_session
from cli.ui import (
    clear_screen,
    print_banner,
    print_error,
    print_info,
    print_nickel,
    print_pending,
    print_user,
)


COMMANDS = {
    "/help": "Lista comandos",
    "/exit": "Sai",
    "/clear": "Limpa a tela",
    "/confirm": "Confirma ação pendente",
    "/cancel": "Cancela ação pendente",
    "/status": "Mostra estado da sessão",
    "/reset": "Limpa histórico da conversa",
}


def main() -> int:
    base_url = os.getenv("NICKEL_API_BASE_URL", "http://localhost:8000")
    client = NickelAPIClient(base_url=base_url)
    state = load_session()

    print_banner()

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print_info("Saindo.")
            return 0

        if not user_input:
            continue

        if user_input.startswith("/"):
            handled = handle_command(user_input, state, client)
            if handled is False:
                return 0
            continue

        print_user(user_input)
        state.history.append({"role": "user", "content": user_input})
        try:
            response = client.send_message(user_input, state.history[:-1])
        except requests.RequestException:
            print_error("Backend offline ou indisponível.")
            state.history.pop()
            continue
        except ValueError:
            print_error("Formato de resposta inválido do backend.")
            state.history.pop()
            continue

        print_nickel(response.reply)
        state.history.append({"role": "assistant", "content": response.reply})
        state.history = state.history[-30:]

        if response.pending_action:
            state.pending_action = response.pending_action
            print_pending(response.pending_action.tool, response.pending_action.action_id)
        else:
            state.pending_action = None

        save_session(state)


def handle_command(
    command: str,
    state: SessionState,
    client: NickelAPIClient,
) -> bool:
    handlers: dict[str, Callable[[], bool]] = {
        "/help": lambda: show_help(),
        "/exit": lambda: False,
        "/clear": lambda: clear_command(),
        "/confirm": lambda: confirm_command(state, client),
        "/cancel": lambda: cancel_command(state, client),
        "/status": lambda: status_command(state, client),
        "/reset": lambda: reset_command(state),
    }
    handler = handlers.get(command)
    if not handler:
        print_error("Comando desconhecido. Use /help.")
        return True
    return handler()


def show_help() -> bool:
    print_info("Comandos:")
    for cmd, desc in COMMANDS.items():
        print_info(f"  {cmd} - {desc}")
    return True


def clear_command() -> bool:
    clear_screen()
    print_banner()
    return True


def status_command(state: SessionState, client: NickelAPIClient) -> bool:
    pending = "sim" if state.pending_action else "não"
    print_info(f"base_url: {client.base_url}")
    print_info(f"turnos em memória: {len(state.history)}")
    print_info(f"ação pendente: {pending}")
    if state.pending_action:
        print_pending(state.pending_action.tool, state.pending_action.action_id)
    return True


def reset_command(state: SessionState) -> bool:
    state.history = []
    state.pending_action = None
    save_session(state)
    print_info("Histórico e ação pendente removidos.")
    return True


def confirm_command(state: SessionState, client: NickelAPIClient) -> bool:
    if not state.pending_action:
        print_info("Sem ação pendente.")
        return True

    action_id = state.pending_action.action_id
    try:
        response = client.confirm_action(action_id)
    except requests.RequestException:
        print_error("Backend offline ou indisponível.")
        return True
    except ValueError:
        print_error("Formato de resposta inválido do backend.")
        return True

    print_nickel(response.result_text)
    state.history.append({"role": "assistant", "content": response.result_text})
    state.history = state.history[-30:]
    state.pending_action = None
    save_session(state)
    return True


def cancel_command(state: SessionState, client: NickelAPIClient) -> bool:
    if not state.pending_action:
        print_info("Sem ação pendente.")
        return True
    action_id = state.pending_action.action_id
    try:
        response = client.cancel_action(action_id)
    except requests.RequestException:
        print_error("Backend offline ou indisponível.")
        return True
    except ValueError:
        print_error("Formato de resposta inválido do backend.")
        return True

    print_nickel(response.result_text)
    state.history.append({"role": "assistant", "content": response.result_text})
    state.history = state.history[-30:]
    state.pending_action = None
    save_session(state)
    return True


if __name__ == "__main__":
    sys.exit(main())
