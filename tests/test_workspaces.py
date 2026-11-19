from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from nickel.core.agent import Agent, Turn
from nickel.core.llm import OpenAICompatClient, make_cloud_llm, make_llm
from nickel.core.skills import ToolContext, ToolRegistry, ToolResult
from nickel.core.stores import StateStore
from nickel.core.workspaces import (
    WorkspaceManager,
    load_workspaces,
    parse_frontmatter,
    slugify,
    workspace_from_text,
)
from nickel.integrations.obsidian import ObsidianVault
from nickel.skills import build_registry

from conftest import FakeLLM, call, run, say

RPG = """---
name: RPG CoC
description: Guardião de Chamado de Cthulhu
aliases: [rpg, "Chamado de Cthulhu"]
keywords: [investigador, sanidade, guardião]
tools: [notes_*, echo]
think: false
temperature: 0.8
max_tokens: 900
history: 4
notes_dir: 06 Pensamentos/RPG
---
Você é o Guardião.
Narre com sobriedade.
"""


def write(directory: Path, name: str, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")


@pytest.fixture
def wsdir(settings) -> Path:
    write(settings.workspaces_dir, "rpg-coc.md", RPG)
    write(settings.workspaces_dir, "codigo.md", "---\nname: Código\nkeywords: [typescript, bug]\ntools: []\n---\nSó conversa.\n")
    write(settings.workspaces_dir, "README.md", "# ignorado\n")
    write(settings.workspaces_dir, "_rascunho.md", "---\nname: Rascunho\n---\n")
    return settings.workspaces_dir


# ------------------------------------------------------------------ arquivos
def test_parse_frontmatter_lists_and_quotes():
    meta, body = parse_frontmatter("---\nname: X\naliases: [a, \"b c\"]\ntools:\n  - notes_*\n- echo\n---\ncorpo\n")
    assert meta["name"] == "X"
    assert meta["aliases"] == ["a", "b c"]
    assert meta["tools"] == ["notes_*", "echo"]
    assert body == "corpo"
    assert parse_frontmatter("sem frontmatter") == ({}, "sem frontmatter")


def test_workspace_fields_and_defaults():
    ws = workspace_from_text("rpg-coc", RPG)
    assert (ws.name, ws.backend, ws.think, ws.temperature, ws.max_tokens, ws.history) == ("RPG CoC", "local", False, 0.8, 900, 4)
    assert ws.notes_dir == "06 Pensamentos/RPG" and ws.instructions.startswith("Você é o Guardião")
    assert ws.llm_options() == {"think": False, "temperature": 0.8, "max_tokens": 900}
    bare = workspace_from_text("x", "só instruções")
    assert bare.tools is None and bare.llm_options() == {} and bare.backend == "local"
    assert workspace_from_text("x", "---\nbackend: nuvem\n---\n").backend == "local"


def test_tool_allowlist_patterns():
    ws = workspace_from_text("x", "---\ntools: [notes_*, memory_list]\n---\n")
    assert ws.allows("notes_capture") and ws.allows("memory_list")
    assert not ws.allows("email_send") and not ws.allows("memory_forget")
    assert workspace_from_text("x", "---\ntools: []\n---\n").allows("notes_capture") is False
    assert workspace_from_text("x", "sem tools").allows("qualquer") is True


def test_load_skips_readme_and_underscore_and_adds_default(wsdir):
    spaces = load_workspaces(wsdir, "geral")
    assert set(spaces) == {"geral", "rpg-coc", "codigo"}
    assert spaces["geral"].is_default and spaces["geral"].conversation == "main"
    assert spaces["rpg-coc"].conversation == "rpg-coc"
    assert set(load_workspaces(None, "geral")) == {"geral"}


def test_default_file_overrides_builtin(settings):
    write(settings.workspaces_dir, "geral.md", "---\nname: Geral\ndescription: tudo\n---\nBase.\n")
    default = load_workspaces(settings.workspaces_dir, "geral")["geral"]
    assert default.is_default and default.instructions == "Base." and default.description == "tudo"


# ------------------------------------------------------------------ roteamento
def make_manager(wsdir, **kw) -> WorkspaceManager:
    return WorkspaceManager(load_workspaces(wsdir, "geral"), None, default_id="geral", **kw)


def test_resolve_list_switch_and_passthrough(wsdir):
    manager = make_manager(wsdir)
    assert manager.active().id == "geral"

    listing = manager.resolve("/ws")
    assert listing.command == "list" and listing.command_only

    switched = manager.resolve("/rpg o investigador entra no porão")
    assert switched.workspace.id == "rpg-coc" and switched.switched and switched.text == "o investigador entra no porão"
    assert not switched.command_only and manager.active().id == "rpg-coc"

    only = manager.resolve("/Chamado-de-Cthulhu")
    assert only.command_only and not only.switched  # já estava ativo

    assert manager.resolve("/ws codigo corrige isso").workspace.id == "codigo"
    assert manager.resolve("/ws nada").command == "unknown"

    plain = manager.resolve("/qualquer-coisa não é workspace")
    assert plain.command is None and plain.text == "/qualquer-coisa não é workspace" and plain.workspace.id == "codigo"


def test_slug_handles_accents():
    assert slugify("Prospecção Fria!") == "prospeccao-fria"


def test_active_workspace_persists_in_state(wsdir, services):
    state = StateStore(services.db)
    first = WorkspaceManager(load_workspaces(wsdir, "geral"), state, default_id="geral")
    first.activate("codigo")
    second = WorkspaceManager(load_workspaces(wsdir, "geral"), state, default_id="geral")
    assert second.active().id == "codigo"
    state.set("workspace.active", "apagado")
    assert second.active().id == "geral"  # workspace que sumiu volta ao padrão


def test_auto_route_needs_threshold_and_no_tie(wsdir):
    manager = make_manager(wsdir, auto_route=True, auto_threshold=2)
    assert manager.resolve("o investigador perdeu sanidade").workspace.id == "rpg-coc"
    manager.activate("geral")
    assert manager.resolve("só uma palavra: sanidade").workspace.id == "geral"
    assert manager.resolve("investigador sanidade bug typescript").workspace.id == "geral"  # empate 2 x 2
    off = make_manager(wsdir, auto_route=False)
    assert off.resolve("investigador sanidade guardião").workspace.id == "geral"


def test_edits_are_picked_up_without_restart(settings):
    manager = WorkspaceManager.from_settings(settings)
    assert [w.id for w in manager.all()] == ["geral"]
    write(settings.workspaces_dir, "novo.md", "---\nname: Novo\n---\nOi\n")
    assert manager.resolve("/novo").workspace.id == "novo"
    write(settings.workspaces_dir, "novo.md", "---\nname: Novo\naliases: [nn]\n---\nOi 2\n")
    manager.refresh()
    assert manager.get("nn").instructions == "Oi 2"


# ------------------------------------------------------------------ agente
@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.executed = []  # type: ignore[attr-defined]

    @registry.add("echo", "Repete", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
    async def echo(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        registry.executed.append(args["text"])  # type: ignore[attr-defined]
        return ToolResult(True, f"eco: {args['text']}")

    @registry.add("email_send", "Envia", {"type": "object", "properties": {}})
    async def email_send(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        registry.executed.append("EMAIL")  # type: ignore[attr-defined]
        return ToolResult(True, "enviado")

    return registry


def make_agent(services, registry, wsdir) -> Agent:
    services.workspaces = WorkspaceManager.from_settings(services.settings, StateStore(services.db))
    return Agent(services, registry)


def test_command_only_does_not_call_model(services, llm, registry, wsdir):
    agent = make_agent(services, registry, wsdir)
    reply = run(agent.handle(Turn(channel="whatsapp", text="/rpg")))
    assert "RPG CoC" in reply.text and not llm.calls
    assert services.conversations.recent(10) == []
    assert "Workspaces:" in run(agent.handle(Turn(channel="whatsapp", text="/ws"))).text
    assert "Não existe" in run(agent.handle(Turn(channel="whatsapp", text="/ws xyz"))).text


def test_instructions_options_and_history_are_per_workspace(services, llm, registry, wsdir):
    agent = make_agent(services, registry, wsdir)
    llm.queue(say("Geral 1."), say("Porão escuro."), say("Voltei."))

    run(agent.handle(Turn(channel="ui", text="oi geral")))
    first = llm.calls[0]
    assert "Você é o Guardião" not in first["messages"][0]["content"] and first["options"] is None

    run(agent.handle(Turn(channel="ui", text="/rpg descreva o porão")))
    second = llm.calls[1]
    assert "Workspace ativo: RPG CoC" in second["messages"][0]["content"]
    assert "Você é o Guardião" in second["messages"][0]["content"]
    assert second["options"] == {"think": False, "temperature": 0.8, "max_tokens": 900}
    assert [m["content"] for m in second["messages"][1:]] == ["descreva o porão"]  # sem o histórico do geral

    run(agent.handle(Turn(channel="ui", text="/geral voltei")))
    third = llm.calls[2]
    assert [m["content"] for m in third["messages"][1:]] == ["oi geral", "Geral 1.", "voltei"]

    assert [m.content for m in services.conversations.recent(10, "rpg-coc")] == ["descreva o porão", "Porão escuro."]


def test_history_limit_comes_from_workspace(services, llm, registry, wsdir):
    agent = make_agent(services, registry, wsdir)
    for index in range(5):
        services.conversations.add("user", f"u{index}", channel="ui", conversation="rpg-coc")
        services.conversations.add("assistant", f"a{index}", channel="ui", conversation="rpg-coc")
    llm.queue(say("ok"))
    run(agent.handle(Turn(channel="ui", text="/rpg mais uma")))
    sent = [m["content"] for m in llm.calls[0]["messages"][1:]]
    assert sent == ["u3", "a3", "u4", "a4", "mais uma"]  # history: 4


def test_tools_are_filtered_and_guarded(services, llm, registry, wsdir):
    agent = make_agent(services, registry, wsdir)
    llm.queue(say("ok"))
    run(agent.handle(Turn(channel="ui", text="/codigo olá")))
    assert llm.calls[0]["tools"] == []  # tools: [] = só conversa

    llm.queue(say("ok"))
    run(agent.handle(Turn(channel="ui", text="/rpg olá")))
    assert [t["function"]["name"] for t in llm.calls[1]["tools"]] == ["echo"]  # email_send fora

    llm.queue(call("email_send"), say("não consegui"))
    reply = run(agent.handle(Turn(channel="ui", text="manda um e-mail")))
    assert "EMAIL" not in registry.executed and reply.text == "não consegui"
    assert "Tool desconhecida: email_send" in llm.calls[-1]["messages"][-1]["content"]


def test_switch_drops_pending_confirmation(services, llm, wsdir):
    registry = build_registry()
    agent = make_agent(services, registry, wsdir)
    services.pending.create("memory_save", {"key": "a", "value": "b"}, "guardar a", channel="ui")
    run(agent.handle(Turn(channel="ui", text="/rpg")))
    assert services.pending.current() is None


def test_auto_route_prefixes_reply(services, llm, registry, wsdir):
    services.settings = services.settings.with_overrides(workspace_auto_route=True)
    agent = make_agent(services, registry, wsdir)
    llm.queue(say("Claro."))
    reply = run(agent.handle(Turn(channel="whatsapp", text="o investigador perdeu sanidade")))
    assert reply.text == "↪ RPG CoC\nClaro."


class NamedLLM(FakeLLM):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


def test_cloud_backend_and_fallback(services, llm, registry, settings):
    write(settings.workspaces_dir, "pesado.md", "---\nname: Pesado\nbackend: cloud\n---\nRaciocínio longo.\n")
    agent = make_agent(services, registry, settings.workspaces_dir)

    local_only = NamedLLM("local")
    services.llm = local_only
    local_only.queue(say("local respondeu"))
    assert run(agent.handle(Turn(channel="ui", text="/pesado oi"))).text == "local respondeu"  # sem cloud: cai no local

    cloud = NamedLLM("cloud")
    cloud.queue(say("nuvem respondeu"))
    services.llm_cloud = cloud
    assert run(agent.handle(Turn(channel="ui", text="de novo"))).text == "nuvem respondeu"
    assert len(local_only.calls) == 1 and len(cloud.calls) == 1


# ------------------------------------------------------------------ notas por workspace
def test_notes_go_to_workspace_folder(services, llm, vault, wsdir):
    registry = build_registry()
    agent = make_agent(services, registry, wsdir)
    llm.queue(call("notes_capture", title="Porão da casa Corbitt", content="Cena do porão."), say("Anotei."))
    run(agent.handle(Turn(channel="whatsapp", text="/rpg anota: cena do porão")))
    assert (vault / "06 Pensamentos" / "RPG" / "Porão da casa Corbitt.md").exists()

    found = services.obsidian.search("porão", notes_dir="06 Pensamentos/RPG")
    assert [item["title"] for item in found] == ["Porão da casa Corbitt"]


def test_notes_dir_cannot_escape_vault(vault):
    obsidian = ObsidianVault(vault, "06 Pensamentos")
    with pytest.raises(ValueError, match="fora do vault"):
        obsidian.folder("../fora")
    assert obsidian.folder("06 Pensamentos/X") == (vault / "06 Pensamentos" / "X").resolve()


# ------------------------------------------------------------------ provider local (llama-server)
def llama_settings(settings, **extra):
    return settings.with_overrides(
        llm_provider="llamacpp", llm_base_url="http://127.0.0.1:8080/v1", llm_model="qwen3.6-35b-a3b", **extra
    )


def test_llamacpp_needs_no_key_and_applies_options(settings):
    client = make_llm(llama_settings(settings))
    assert isinstance(client, OpenAICompatClient) and client.local
    assert "Authorization" not in client._client.headers
    payload = client.build_payload([{"role": "user", "content": "oi"}], None, {"think": True, "temperature": 0.9, "max_tokens": 77})
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert payload["temperature"] == 0.9 and payload["max_tokens"] == 77
    default = client.build_payload([{"role": "user", "content": "oi"}], None)
    assert default["chat_template_kwargs"] == {"enable_thinking": False}


def test_llamacpp_health_states(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(503, json={"error": {"message": "Loading model"}})
        return httpx.Response(404)

    loading = OpenAICompatClient(llama_settings(settings), transport=httpx.MockTransport(handler))
    result = run(loading.health())
    assert result["ok"] is False and "carregando" in result["detail"]

    def ready(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3.6-35b-a3b"}]})
        return httpx.Response(404)

    ok = run(OpenAICompatClient(llama_settings(settings), transport=httpx.MockTransport(ready)).health())
    assert ok["ok"] is True and ok["provider"] == "llamacpp" and "qwen3.6-35b-a3b" in ok["detail"]

    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusado")

    gone = run(OpenAICompatClient(llama_settings(settings), transport=httpx.MockTransport(down)).health())
    assert gone["ok"] is False and "inacessível" in gone["detail"]


def test_llamacpp_chat_parses_tool_calls(settings):
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"id": "c1", "type": "function", "function": {"name": "echo", "arguments": '{"text": "x"}'}}
                            ],
                        }
                    }
                ]
            },
        )

    client = OpenAICompatClient(llama_settings(settings), transport=httpx.MockTransport(handler))
    reply = run(client.chat([{"role": "user", "content": "oi"}], [{"type": "function", "function": {"name": "echo"}}]))
    assert reply.tool_calls[0].name == "echo" and reply.tool_calls[0].arguments == {"text": "x"}
    assert seen["tool_choice"] == "auto"


def test_make_cloud_llm(settings):
    assert make_cloud_llm(settings) is None
    cloud = make_cloud_llm(
        settings.with_overrides(
            llm_cloud_base_url="https://api.runpod.ai/v2/abc/openai/v1", llm_cloud_api_key="k", llm_cloud_model="qwen3.6-27b"
        )
    )
    assert isinstance(cloud, OpenAICompatClient) and not cloud.local
    assert cloud.settings.llm_model == "qwen3.6-27b" and cloud.runpod_endpoint_id == "abc"


# ------------------------------------------------------------------ API
def test_workspace_api(services, llm, wsdir):
    from fastapi.testclient import TestClient

    from nickel.app import create_app

    services.workspaces = WorkspaceManager.from_settings(services.settings, StateStore(services.db))
    app = create_app(services=services, registry=build_registry(), background=False)
    with TestClient(app) as client:
        data = client.get("/api/workspaces").json()
        assert data["active"] == "geral"
        assert {item["id"] for item in data["items"]} == {"geral", "rpg-coc", "codigo"}

        assert client.post("/api/workspaces/rpg-coc/activate").json()["active"] == "rpg-coc"
        assert client.post("/api/workspaces/nada/activate").status_code == 404
        assert client.get("/api/state").json()["workspace"] == "rpg-coc"

        llm.queue(say("Boa noite."))
        client.post("/api/chat", json={"text": "oi"})
        assert [m["content"] for m in client.get("/api/messages").json()] == ["oi", "Boa noite."]
        assert client.get("/api/messages", params={"workspace": "geral"}).json() == []
        assert client.get("/api/messages", params={"workspace": "xx"}).status_code == 404
