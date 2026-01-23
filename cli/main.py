from __future__ import annotations

import os
import sys
from typing import Callable

import requests

from cli.api_client import NickelAPIClient
from cli.session_store import SessionState, load_session, save_session
from cli.ui import (
    clear_screen,
    print_error,
    print_info,
    print_nickel,
    print_pending,
    print_user,
)


COMMANDS = {
    "/help": "List commands",
    "/exit": "Exit",
    "/clear": "Clear screen",
    "/confirm": "Confirm pending action",
    "/cancel": "Cancel pending action",
    "/status": "Show session status",
}


def main() -> int:
    base_url = os.getenv("NICKEL_API_BASE_URL", "http://localhost:8000")
    client = NickelAPIClient(base_url=base_url)
    state = load_session()

    print_info("Nickel CLI. Type /help for commands.")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print_info("Exiting.")
            return 0

        if not user_input:
            continue

        if user_input.startswith("/"):
            handled = handle_command(user_input, state, client)
            if handled is False:
                return 0
            continue

        print_user(user_input)
        try:
            response = client.send_message(user_input, state.session_id)
        except requests.RequestException:
            print_error("Backend offline or unreachable.")
            continue
        except ValueError:
            print_error("Invalid response format from backend.")
            continue

        if not response.session_id:
            print_error("Missing session_id in response. Restart the session.")
            state = SessionState(session_id=None, pending_action=None)
            save_session(state)
            continue

        state.session_id = response.session_id
        if response.pending_action:
            state.pending_action = response.pending_action
            print_nickel(response.reply)
            print_pending(response.pending_action.summary)
        else:
            state.pending_action = None
            print_nickel(response.reply)
        save_session(state)

    return 0


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
    }
    handler = handlers.get(command)
    if not handler:
        print_error("Unknown command. Use /help.")
        return True
    return handler()


def show_help() -> bool:
    print_info("Commands:")
    for cmd, desc in COMMANDS.items():
        print_info(f"  {cmd} - {desc}")
    return True


def clear_command() -> bool:
    clear_screen()
    return True


def status_command(state: SessionState, client: NickelAPIClient) -> bool:
    pending = "yes" if state.pending_action else "no"
    print_info(f"base_url: {client.base_url}")
    print_info(f"session_id: {state.session_id or 'none'}")
    print_info(f"pending_action: {pending}")
    if state.pending_action:
        print_pending(state.pending_action.summary)
    return True


def confirm_command(state: SessionState, client: NickelAPIClient) -> bool:
    if not state.pending_action:
        print_info("No pending action.")
        return True
    action_id = state.pending_action.id
    try:
        response = client.confirm_action(action_id)
    except requests.RequestException:
        print_error("Backend offline or unreachable.")
        return True
    except ValueError:
        print_error("Invalid response format from backend.")
        return True

    print_nickel(response.result_text)
    state.pending_action = response.pending_action
    save_session(state)
    if state.pending_action:
        print_pending(state.pending_action.summary)
    return True


def cancel_command(state: SessionState, client: NickelAPIClient) -> bool:
    if not state.pending_action:
        print_info("No pending action.")
        return True
    action_id = state.pending_action.id
    try:
        response = client.cancel_action(action_id)
    except requests.RequestException:
        print_error("Backend offline or unreachable.")
        return True
    except ValueError:
        print_error("Invalid response format from backend.")
        return True

    print_nickel(response.result_text)
    state.pending_action = response.pending_action
    save_session(state)
    if state.pending_action:
        print_pending(state.pending_action.summary)
    return True


if __name__ == "__main__":
    sys.exit(main())
