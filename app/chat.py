from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException

from app.audit import record_event
from app.calendar import CALENDAR_READ_SCOPES, CALENDAR_WRITE_SCOPES, list_events as calendar_list
from app.config import Settings
from app.gmail import GMAIL_COMPOSE_SCOPES, GMAIL_READ_SCOPES, draft as email_draft
from app.gmail import read as email_read
from app.gmail import read_latest as email_read_latest
from app.gmail import search as email_search
from app.llm import generate_response
from app.orchestrator import decide_tool, is_high_confidence
from app.oauth import ensure_google_ready
from app.pending_actions import require_confirmation
from app.spotify import (
    check_spotify_playback_target,
    pause as spotify_pause,
    play as spotify_play,
    skip as spotify_skip,
)
from app.spotify_oauth import SPOTIFY_TOKEN_STORE_KEY, start_spotify_oauth
from app.tasks import list_tasks

ReadinessStatus = Literal[
    "ready",
    "needs_configuration",
    "needs_connection",
    "token_expired",
    "insufficient_scopes",
    "needs_device",
    "needs_external_activation",
    "blocked",
    "requires_clarification",
]

_MINIMUM_TOOL_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "email.search": ("query",),
    "email.read": ("message_id",),
    "email.draft": ("raw_base64",),
    "email.send": ("raw_base64",),
    "calendar.create_event": ("calendar_id", "event"),
    "calendar.modify_event": ("calendar_id", "event_id", "event"),
    "notes.create": ("title", "body"),
    "tasks.create": ("title",),
}

_SEMANTIC_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "spotify.play": ("context_uri", "uris"),
}



GOOGLE_TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "email.search": GMAIL_READ_SCOPES,
    "email.read": GMAIL_READ_SCOPES,
    "email.read_latest": GMAIL_READ_SCOPES,
    "email.draft": GMAIL_COMPOSE_SCOPES,
    "email.send": GMAIL_COMPOSE_SCOPES,
    "calendar.list_events": CALENDAR_READ_SCOPES,
    "calendar.create_event": CALENDAR_WRITE_SCOPES,
    "calendar.modify_event": CALENDAR_WRITE_SCOPES,
}


_CONFIRMATION_REQUIRED_TOOLS = {

    "email.send",
    "calendar.create_event",
    "calendar.modify_event",
    "notes.create",
    "tasks.create",
}

TOOL_HANDLERS: dict[str, dict[str, Any]] = {
    "email.search": {"handler": email_search, "requires_confirmation": False},
    "email.read": {"handler": email_read, "requires_confirmation": False},
    "email.read_latest": {"handler": email_read_latest, "requires_confirmation": False},
    "email.draft": {"handler": email_draft, "requires_confirmation": False},
    "email.send": {"handler": None, "requires_confirmation": True},
    "calendar.list_events": {
        "handler": calendar_list,
        "requires_confirmation": False,
    },
    "calendar.create_event": {"handler": None, "requires_confirmation": True},
    "calendar.modify_event": {"handler": None, "requires_confirmation": True},
    "notes.create": {"handler": None, "requires_confirmation": True},
    "tasks.create": {"handler": None, "requires_confirmation": True},
    "tasks.list": {"handler": list_tasks, "requires_confirmation": False},
    "spotify.play": {"handler": spotify_play, "requires_confirmation": False},
    "spotify.pause": {"handler": spotify_pause, "requires_confirmation": False},
    "spotify.skip": {"handler": spotify_skip, "requires_confirmation": False},
}

_GOOGLE_TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "email.search": ("https://www.googleapis.com/auth/gmail.readonly",),
    "email.read": ("https://www.googleapis.com/auth/gmail.readonly",),
    "email.read_latest": ("https://www.googleapis.com/auth/gmail.readonly",),
    "email.draft": ("https://www.googleapis.com/auth/gmail.compose",),
    "email.send": ("https://www.googleapis.com/auth/gmail.send",),
    "calendar.list_events": ("https://www.googleapis.com/auth/calendar.readonly",),
    "calendar.create_event": ("https://www.googleapis.com/auth/calendar.events",),
    "calendar.modify_event": ("https://www.googleapis.com/auth/calendar.events",),
}

_SPOTIFY_TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "spotify.play": ("user-modify-playback-state",),
    "spotify.pause": ("user-modify-playback-state",),
    "spotify.skip": ("user-modify-playback-state",),
}


# existing helper funcs preserved below ...
def _parse_history(payload: dict[str, Any]) -> list[dict[str, str]]:
    history = payload.get("history")
    if not isinstance(history, list):
        return []

    parsed: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        parsed.append({"role": role, "content": content.strip()})
    return parsed


def _require_message(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if not message or not isinstance(message, str):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "missing_message",
                    "message": "message is required.",
                }
            },
        )
    return message


def _compute_confidence(requested_tool: str | None, action_tool: str | None) -> float:
    if requested_tool and action_tool == requested_tool:
        return 0.95
    if requested_tool and action_tool is None:
        return 0.35
    if not requested_tool and action_tool:
        return 0.65
    return 0.8


def _clarification_result(
    *,
    decision: Any,
    llm_tool: str | None,
    response_text: str,
    fallback: str,
) -> dict[str, Any]:
    clarification_response = response_text.strip() or (
        "Não tenho confiança suficiente para executar essa ação ainda. "
        "Pode esclarecer o que você quer fazer?"
    )
    return {
        "status": "requires_clarification",
        "response": clarification_response,
        "fallback": fallback,
        "orchestration": {
            "decision": {
                "tool": decision.tool,
                "reason": decision.reason,
                "confidence": decision.confidence,
            },
            "llm_tool": llm_tool,
        },
    }


def _readiness_result(
    *,
    status: ReadinessStatus,
    tool: str,
    explanation: str,
    technical_details: str,
    missing_factor: str,
    authorization_url: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    readiness: dict[str, Any] = {
        "status": status,
        "tool": tool,
        "explanation": explanation,
        "technical_details": technical_details,
        "missing_factor": missing_factor,
    }
    if authorization_url:
        readiness["authorization_url"] = authorization_url
    if state:
        readiness["state"] = state
    return readiness


def _tool_not_ready_response(
    *,
    response_text: str,
    action: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    natural_response = response_text.strip() or str(readiness.get("message") or "A ferramenta precisa de conexão ou configuração antes de continuar.")
    return {
        "status": "tool_not_ready",
    natural_response = response_text.strip() or readiness["explanation"]
    result = {
        "status": readiness["status"],
        "response": natural_response,
        "action": action,
        "tool_readiness": readiness,
        "requires_confirmation": False,
    }
    if "authorization_url" in readiness:
        result["authorization_url"] = readiness["authorization_url"]
    return result


def _resolve_google_readiness(
    settings: Settings,
    tool: str,
    _payload: dict[str, Any],
) -> dict[str, Any]:
    required_scopes = _GOOGLE_TOOL_SCOPES.get(tool, ())
    return ensure_google_ready(settings, required_scopes).to_response()


def _resolve_spotify_readiness(
    settings: Settings,
    tool: str,
    _payload: dict[str, Any],
) -> dict[str, Any]:
    required_scopes = _SPOTIFY_TOOL_SCOPES.get(tool, ())
    connection = check_spotify_connection(settings)
    if connection.status == "needs_configuration":
        return _readiness_result(
            status="needs_user_setup",
            tool=tool,
            explanation="A integração do Spotify ainda não foi configurada neste ambiente.",
            technical_details=connection.message or "Spotify OAuth não configurado.",
            missing_factor="spotify_configuration",
            authorization_url=connection.authorization_url,
            state=connection.state,
        )
    if connection.status in {"needs_connection", "needs_reauth"}:
        return _readiness_result(
            status="needs_connection",
            tool=tool,
            explanation="Preciso conectar ou reconectar sua conta Spotify antes de controlar a reprodução.",
            technical_details=connection.message or "Spotify OAuth indisponível.",
            missing_factor="spotify_account_connection",
            authorization_url=connection.authorization_url,
            state=connection.state,
        )

    access_token = connection.access_token
    if not access_token:
        return _readiness_result(
            status="blocked",
            tool=tool,
            explanation="A conexão com Spotify está inconsistente e não pode ser usada agora.",
            technical_details="Spotify marcado como pronto sem access_token.",
            missing_factor="spotify_access_token",
        )

    if not settings.spotify_access_token:
        token_store = get_token_store(settings)
        token = token_store.get(SPOTIFY_TOKEN_STORE_KEY) or {}
        granted_scopes = set(token.get("scopes") or [])
        missing_scopes = [scope for scope in required_scopes if scope not in granted_scopes]
        if missing_scopes:
            session = start_spotify_oauth(settings)
            return _readiness_result(
                status="needs_external_activation",
                tool=tool,
                explanation="Sua conexão Spotify existe, mas faltam permissões para controlar a reprodução.",
                technical_details=f"Scopes ausentes: {', '.join(missing_scopes)}.",
                missing_factor="spotify_oauth_scopes",
                authorization_url=session.authorization_url,
                state=session.state,
            )

    if (
        tool in {"spotify.play", "spotify.pause", "spotify.skip"}
        and not settings.spotify_device_id
    ):
        target = check_spotify_playback_target(settings)
        if not target.device_id:
            return _readiness_result(
                status="needs_external_activation",
                tool=tool,
                explanation="Preciso que exista um device Spotify ativo ou disponível antes de executar essa ação.",
                technical_details="Nenhum device reproduzível foi encontrado em /me/player/devices.",
                missing_factor="spotify_playback_device",
            )

    return _readiness_result(
        status="ready",
        tool=tool,
        explanation="Tool pronta para execução.",
        technical_details="Pré-requisitos do Spotify atendidos.",
        missing_factor="none",
    )


def resolve_tool_readiness(
    settings: Settings,
    tool: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if tool.startswith("email.") or tool.startswith("calendar."):
        return _resolve_google_readiness(settings, tool, payload)
    if tool.startswith("spotify."):
        return _resolve_spotify_readiness(settings, tool, payload)
    return {"status": "ready", "tool": tool}


def _missing_required_fields(tool: str, payload: dict[str, Any]) -> list[str]:
    required_fields = _MINIMUM_TOOL_REQUIREMENTS.get(tool, ())
    missing: list[str] = []
    for field in required_fields:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def _is_semantically_incomplete(tool: str, payload: dict[str, Any]) -> bool:
    if tool != "spotify.play":
        return False
    return not any(payload.get(field) for field in _SEMANTIC_REQUIREMENTS[tool])


def resolve_action_readiness(
    settings: Settings,
    tool: str,
    payload: dict[str, Any],
    user_message: str,
    *,
    confidence: float | None = None,
) -> dict[str, Any]:
    base_readiness = resolve_tool_readiness(settings, tool, payload)
    if base_readiness["status"] != "ready":
        return base_readiness

    missing_fields = _missing_required_fields(tool, payload)
    if missing_fields:
        missing_list = ", ".join(missing_fields)
        return _readiness_result(
            status="requires_clarification",
            tool=tool,
            explanation=(
                f"Antes de executar {tool}, preciso confirmar alguns dados: {missing_list}."
            ),
            technical_details=(
                f"Payload sem parâmetros mínimos obrigatórios: {missing_list}."
            ),
            missing_factor="missing_required_parameters",
        )

    if _is_semantically_incomplete(tool, payload):
        return _readiness_result(
            status="requires_clarification",
            tool=tool,
            explanation=(
                "Consigo controlar o Spotify, mas ainda preciso saber exatamente o que tocar."
            ),
            technical_details=(
                "Payload semanticamente incompleto: spotify.play sem context_uri nem uris."
            ),
            missing_factor="semantic_payload_gap",
        )

    if confidence is not None and confidence < 0.75:
        return _readiness_result(
            status="requires_clarification",
            tool=tool,
            explanation=(
                "Ainda não tenho confiança suficiente para executar essa ação automaticamente. "
                "Pode confirmar ou detalhar melhor o pedido?"
            ),
            technical_details=(
                f"Heurística/orquestração com baixa confiança ({confidence:.2f}) para a mensagem: {user_message!r}."
            ),
            missing_factor="low_confidence_action",
        )

    return _readiness_result(
        status="ready",
        tool=tool,
        explanation="Tool pronta para execução.",
        technical_details="Conexão, parâmetros mínimos e contexto suficientes.",
        missing_factor="none",
    )


def plan_chat(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    message = _require_message(payload)
    history = _parse_history(payload)

    decision = decide_tool(message)
    forced_tool = decision.tool if is_high_confidence(decision) else None

    llm_response = generate_response(
        settings,
        message,
        forced_tool=forced_tool,
        history=history,
    )

    action = llm_response.get("action")
    action_tool = action.get("tool") if isinstance(action, dict) else None
    response_text = llm_response.get("response", "")

    if action:
        tool = action.get("tool")
        if forced_tool and tool != forced_tool:
            record_event(
                tool="orchestrator.mismatch",
                status="fallback",
                payload={
                    "message": message,
                    "decision_tool": decision.tool,
                    "decision_reason": decision.reason,
                    "decision_confidence": decision.confidence,
                    "forced_tool": forced_tool,
                    "llm_tool": tool,
                },
            )
            return {
                "status": "requires_clarification",
                "response": "Encontrei um conflito na interpretação do pedido. Pode confirmar a ação desejada?",
                "fallback": "tool_mismatch",
                "orchestration": {
                    "decision": {
                        "tool": decision.tool,
                        "reason": decision.reason,
                        "confidence": decision.confidence,
                    },
                    "llm_tool": tool,
                },
            }

        if tool and (decision.tool is None or not is_high_confidence(decision)):
            record_event(
                tool="orchestrator.low_confidence_action",
                status="observed",
                payload={
                    "message": message,
                    "decision_reason": decision.reason,
                    "decision_confidence": decision.confidence,
                    "llm_tool": tool,
                },
            )
            return _clarification_result(
                decision=decision,
                llm_tool=tool,
                response_text=response_text,
                fallback="low_confidence_action",
            )

        if tool not in TOOL_HANDLERS:
            return _clarification_result(
                decision=decision,
                llm_tool=tool,
                response_text=response_text,
                fallback="unsupported_llm_tool",
            )

        readiness = resolve_action_readiness(
            settings,
            tool,
            action.get("payload", {}),
            message,
            confidence=decision.confidence,
        )
        if readiness["status"] != "ready":
            return _tool_not_ready_response(
                response_text=response_text,
                action=action,
                readiness=readiness,
            )

    return {
        "response": llm_response.get("response", ""),
        "action": action if isinstance(action, dict) else None,
        "confidence": _compute_confidence(decision.tool, action_tool),
        "requires_confirmation": action_tool in _CONFIRMATION_REQUIRED_TOOLS,
    }


def execute_chat_plan(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    response_text = payload.get("response", "")

    if action is None:
        return {
            "status": "ok",
            "response": response_text,
        }

    if not isinstance(action, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "invalid_action",
                    "message": "action must be an object or null.",
                }
            },
        )

    tool = action.get("tool")
    action_payload = action.get("payload", {})
    readiness = resolve_action_readiness(
        settings,
        str(tool),
        action_payload if isinstance(action_payload, dict) else {},
        str(response_text),
        confidence=payload.get("confidence"),
    )
    if readiness["status"] != "ready":
        return _tool_not_ready_response(
            response_text=response_text,
            action=action,
            readiness=readiness,
        )

    if tool == "email.search":
        tool_result = email_search(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "email.read":
        tool_result = email_read(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "email.read_latest":
        tool_result = email_read_latest(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "email.draft":
        tool_result = email_draft(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "email.send":
        pending = require_confirmation("email.send", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "calendar.list_events":
        tool_result = calendar_list(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "calendar.create_event":
        pending = require_confirmation("calendar.create_event", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "calendar.modify_event":
        pending = require_confirmation("calendar.modify_event", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "notes.create":
        pending = require_confirmation("notes.create", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "tasks.create":
        pending = require_confirmation("tasks.create", action_payload)
        return {
            "status": "pending_confirmation",
            "response": response_text,
            "pending_action": pending,
        }
    if tool == "tasks.list":
        tool_result = list_tasks(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "spotify.play":
        tool_result = spotify_play(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "spotify.pause":
        tool_result = spotify_pause(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    if tool == "spotify.skip":
        tool_result = spotify_skip(settings, action_payload)
        return {"status": "ok", "response": response_text, "tool_result": tool_result}
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "unsupported_tool",
                "message": f"Tool {tool} is not supported.",
            }
        },
    )


def handle_chat(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    plan_result = plan_chat(settings, payload)
    if "status" in plan_result:
        return plan_result
    return execute_chat_plan(settings, plan_result)
