# Observabilidade e Auditoria Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma aba "Monitor" na GUI que mostra, em tempo real e a partir do código em execução, tudo o que o NICKEL faz e o raciocínio real do modelo, sobre um log de auditoria persistente com documentação de processos gerada do código.

**Architecture:** O `AuditLog` existente vira o barramento de eventos: `record()` grava no SQLite, devolve o evento e o publica para assinantes. Um `run_id` por turno (`ContextVar`) agrupa os eventos. Os clientes LLM ganham streaming opcional (`on_delta`) e um `ReasoningTracker` converte os deltas em eventos limitados por tempo. A API expõe SSE, execuções e relatório em Markdown. A UI é um reducer puro (testado com `node --test`) mais DOM. Um catálogo de eventos é a fonte única da interface, da documentação gerada e do teste que barra eventos fora do catálogo.

**Tech Stack:** Python 3.11, FastAPI (`StreamingResponse`), SQLite, httpx, JS puro (ES modules), `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-19-observabilidade-e-voz-design.md` (seção 1)

## Global Constraints

- Sem dependências novas de runtime; frontend sem build e sem CDN.
- `from __future__ import annotations` e docstring de módulo em PT-BR; textos da UI em PT-BR no imperativo.
- Migração do SQLite só aditiva (`ALTER TABLE ... ADD COLUMN`); os 102 testes atuais continuam passando.
- Chamada ao LLM **sem** `on_delta` continua com `"stream": False` (comportamento atual intacto).
- Nenhum segredo, `audio_b64`, `image_b64` ou token em eventos: tudo passa por `_redact`.
- Texto de evento é limitado: 500 caracteres por padrão; só `reasoning/final` pode chegar a 4000.
- Todo `audit.record(<kind>, ...)` no código usa um `kind` presente em `CATALOG` (teste de varredura por AST).

## Review Focus

- Stream do servidor LLM cai no meio: o turno termina com `llm/error` e `turn/error`, o raciocínio parcial fica salvo e nenhum assinante SSE trava.
- Aba aberta tarde ou reconectada (`after`/`Last-Event-ID`): reprisa sem duplicar e sem perder eventos; assinante desconectado sai do barramento (sem vazamento).
- Detalhe com quebra de linha, 8000 caracteres ou segredo não quebra o enquadramento SSE nem vaza.
- `</think>` partido entre chunks, argumentos de ferramenta chegando em pedaços e modelo com `think` desligado (sem raciocínio): nada inventado na tela.
- Escrita de evento em thread de trabalho (`asyncio.to_thread`) chega aos assinantes sem erro de loop.

---

### Task 1: Barramento de eventos no AuditLog

**Files:**
- Create: `nickel/core/trace.py`
- Modify: `nickel/core/db.py` (migração da tabela `audit`), `nickel/core/stores.py:157-186` (`AuditLog`, `_redact`)
- Test: `tests/test_audit_bus.py`

**Interfaces:**
- Produces:
  - `trace.current_run_id: ContextVar[str | None]`; `trace.new_run_id() -> str` (12 hex); `trace.run_scope(run_id: str | None = None)` (context manager que entrega o `run_id` e restaura o anterior).
  - `AuditLog.record(kind, name, status, detail=None, *, duration_ms: int | None = None, run_id: str | None = None, text_limit: int = 500) -> dict[str, Any]` com chaves `id, at, kind, name, status, detail, run_id, duration_ms`. `run_id` omitido usa `current_run_id`.
  - `AuditLog.subscribe(maxsize: int = 1000) -> asyncio.Queue`, `unsubscribe(queue) -> None`, `has_subscribers() -> bool`.
  - `AuditLog.since(after_id: int, limit: int = 500) -> list[dict]` (ascendente), `AuditLog.run(run_id: str) -> list[dict]` (ascendente), `AuditLog.runs(limit: int = 30) -> list[dict]` com `{run_id, started_at, events, errors, duration_ms}`.
  - `AuditLog.recent(limit)` continua devolvendo `list[dict]`, agora com as chaves novas.

- [ ] **Step 1: Escrever os testes que falham**
  - `test_record_returns_event_and_stamps_run_id`: dentro de `run_scope("abc123")`, `record("tool","x","ok",{"a":1},duration_ms=7)` devolve `run_id == "abc123"`, `duration_ms == 7`, `detail == {"a": 1}`.
  - `test_run_scope_restores_previous_value`: depois do `with`, `current_run_id.get() is None`.
  - `test_subscriber_receives_events_from_worker_thread`: `queue = audit.subscribe()` dentro de um loop; `await asyncio.to_thread(audit.record, "system","startup","ok")`; `(await asyncio.wait_for(queue.get(), 1))["kind"] == "system"`.
  - `test_full_queue_drops_oldest`: `subscribe(maxsize=2)`, 3 eventos, o assinante vê os 2 mais novos e o `record` não levanta exceção.
  - `test_unsubscribe_clears_subscribers`: `has_subscribers()` volta a `False`.
  - `test_since_and_run_are_ascending_and_filtered`.
  - `test_text_limit_and_redaction`: `detail={"token":"s3","text":"x"*900}` → `token == "***"`, `len(text) == 501`; com `text_limit=4000` o texto de 900 passa inteiro.
  - `test_migrates_legacy_audit_table`: cria SQLite com a tabela `audit` antiga (sem `run_id`), abre com `Database(path)` e `record(...)` funciona; `PRAGMA table_info(audit)` contém `run_id` e `duration_ms`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_audit_bus.py -v`
Expected: FAIL (`ModuleNotFoundError: nickel.core.trace`).

- [ ] **Step 3: Implementar `trace.py`, a migração e o `AuditLog`**
  - `Database.__init__` chama `_migrate()` depois do `executescript`: lê `PRAGMA table_info(audit)` e acrescenta `run_id TEXT` e `duration_ms INTEGER` se faltarem; cria `idx_audit_run ON audit(run_id)`. Colunas novas também entram no `CREATE TABLE` do `SCHEMA`.
  - `AuditLog` guarda `_subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop]`. `subscribe()` captura `asyncio.get_running_loop()`. `record()` entrega com `loop.call_soon_threadsafe(_offer, queue, event)`, onde `_offer` descarta o item mais antigo quando a fila está cheia. Toda falha ao entregar é engolida (log em `debug`), porque auditar nunca derruba o fluxo.
  - `_redact(detail, limit=500)` passa a receber o limite.

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_audit_bus.py -v && pytest -q`
Expected: PASS e os 102 testes antigos continuam passando.

- [ ] **Step 5: Commit**

```bash
git add nickel/core/trace.py nickel/core/db.py nickel/core/stores.py tests/test_audit_bus.py
git commit -m "feat(audit): AuditLog como barramento de eventos com run_id"
```

---

### Task 2: Catálogo de eventos e teste de completude

**Files:**
- Create: `nickel/core/events.py`
- Test: `tests/test_event_catalog.py`

**Interfaces:**
- Produces:
  - `EventSpec` (frozen dataclass): `kind, description, statuses: tuple[str, ...], fields: tuple[str, ...], source: str`.
  - `CATALOG: dict[str, EventSpec]` com os kinds `oauth, whatsapp, outbound, confirmation, tool, llm, turn, route, prompt, reasoning, voice, system`.
  - Estados `turn`: `start, done, error`. `route`: `resolved`. `prompt`: `built`. `llm`: `start, done, error`. `reasoning`: `progress, final`. `tool`: `start, ok, error`. `confirmation`: `requested, confirmed, cancelled, dropped`. `voice`: `listening, transcribing, thinking, speaking, idle, error`. `system`: `startup, shutdown, health`.
  - `PHASE_LABELS: dict[str, str]` para `idle, routing, prompting, thinking, answering, tool, confirming, listening, speaking, error`.
  - `PHASES: dict[tuple[str, str], str]`: `turn/start→routing`, `route/resolved→prompting`, `prompt/built→thinking`, `llm/start→thinking`, `reasoning/progress→thinking`, `llm/done→answering`, `tool/start→tool`, `tool/ok→thinking`, `tool/error→thinking`, `confirmation/requested→confirming`, `turn/done→idle`, `turn/error→error`, `llm/error→error`, `voice/listening→listening`, `voice/speaking→speaking`, `voice/idle→idle`.
  - `phase_for(kind: str, status: str) -> str | None`.
  - `TURN_FLOW: tuple[tuple[str, str], ...]` (ordem de um turno normal: `turn/start, route/resolved, prompt/built, llm/start, reasoning/final, llm/done, tool/start, tool/ok, llm/start, llm/done, turn/done`).

- [ ] **Step 1: Escrever os testes que falham**
  - `test_phase_for_known_and_unknown`: `phase_for("llm","start") == "thinking"`, `phase_for("oauth","connected") is None`.
  - `test_every_phase_value_has_a_label`.
  - `test_all_record_calls_use_cataloged_kind_and_status`: varre `nickel/**/*.py` com `ast`, coleta cada `X.audit.record("<kind>", ..., "<status>")` com literais; falha listando os que não estão em `CATALOG[kind].statuses` (statuses dinâmicos, como `"ok" if ... else "error"`, são ignorados).
  - `test_every_cataloged_kind_is_emitted_somewhere`: cada kind do catálogo aparece como literal em algum `record(...)` ou `emit(...)` do código. Nasce vermelho e fica verde ao final da Task 6.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_event_catalog.py -v`
Expected: FAIL (módulo inexistente).

- [ ] **Step 3: Implementar `events.py`** com as estruturas acima. `source` cita o módulo que emite (ex.: `nickel/core/agent.py`). Ainda não instrumente o agente.

- [ ] **Step 4: Rodar**

Run: `pytest tests/test_event_catalog.py -v`
Expected: PASS nos três primeiros testes; `test_every_cataloged_kind_is_emitted_somewhere` marcado `@pytest.mark.xfail(strict=True, reason="fecha na Task 6")`.

- [ ] **Step 5: Commit**

```bash
git add nickel/core/events.py tests/test_event_catalog.py
git commit -m "feat(audit): catálogo de eventos, fases e fluxo de um turno"
```

---

### Task 3: Streaming no cliente LLM

**Files:**
- Modify: `nickel/core/llm.py` (`LLMReply`, `LLMClient`, `OllamaClient.chat`, `OpenAICompatClient.chat`, `build_payload` de ambos), `nickel/config.py` (`llm_stream`)
- Create: `tests/fixtures/` (fixtures SSE/NDJSON)
- Test: `tests/test_llm_streaming.py`
- Modify: `tests/conftest.py` (`FakeLLM.chat` aceita `on_delta=None`)

**Interfaces:**
- Produces:
  - `DeltaCallback = Callable[[str, str], None]`, com `(canal, texto)` e canal `"reasoning"` ou `"content"`.
  - `LLMReply.reasoning: str = ""` e `LLMReply.usage: dict[str, float]` com as chaves `prompt_tokens, completion_tokens, tokens_per_second, duration_ms` (as que o servidor informar).
  - `ThinkSplitter.feed(chunk: str) -> list[tuple[str, str]]` e `.flush()`: separa `<think>…</think>` em canal `reasoning` e o restante em `content`, inclusive com a tag partida entre chunks.
  - `OllamaClient.chat(messages, tools=None, options=None, on_delta=None)` e `OpenAICompatClient.chat(...)` idem. `supports_stream = True` nas duas classes. `Settings.llm_stream: bool = True` (`LLM_STREAM`).

- [ ] **Step 1: Escrever os testes que falham** (httpx `MockTransport`, como em `test_llm_providers.py`)
  - `test_without_on_delta_payload_stays_non_streaming`: `build_payload(...)["stream"] is False`.
  - `test_openai_stream_collects_content_reasoning_and_usage`: SSE com `delta.reasoning_content`, depois `delta.content`, e um chunk final com `usage`/`timings`; o `on_delta` recebe os canais na ordem, `reply.reasoning`, `reply.content` e `reply.usage["completion_tokens"]` estão corretos e o payload leva `stream_options={"include_usage": true}`.
  - `test_openai_stream_assembles_tool_call_arguments_split_in_deltas`: `tool_calls[0].function.arguments` em 3 pedaços → `reply.tool_calls[0].arguments == {...}`.
  - `test_ollama_stream_reads_thinking_and_eval_counts`: NDJSON com `message.thinking`, `message.content` e o final `done` com `eval_count`/`eval_duration`.
  - `test_think_splitter_handles_tag_split_across_chunks`: `feed("<thi")`, `feed("nk>ab</th")`, `feed("ink>ok")` → reasoning `"ab"`, content `"ok"`.
  - `test_stream_cut_midway_raises_llm_error_with_partial_reasoning`: a conexão cai após dois chunks → `LLMError` e `on_delta` já recebeu o parcial.
  - `test_retry_only_before_first_byte`: 503 seguido de 200 tenta de novo; falha depois do primeiro byte não tenta de novo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_llm_streaming.py -v`
Expected: FAIL (`on_delta` não existe).

- [ ] **Step 3: Implementar**
  - Com `on_delta`, o payload sai com `stream: True`; na OpenAI-compat acrescenta `stream_options`. Sem `on_delta`, nada muda.
  - OpenAI-compat: `client.stream("POST", ...)` e `aiter_lines()`; ignora linhas que não começam com `data:` e encerra em `[DONE]`. Os `tool_calls` acumulam por `index`. Os tokens vêm de `usage`/`timings` (`predicted_n`, `predicted_per_second`).
  - Ollama: `aiter_lines()` em NDJSON; `eval_count / eval_duration` dão os tokens por segundo.
  - Se `delta.reasoning_content` ou `message.thinking` não existir, passa o `content` pelo `ThinkSplitter`.
  - `_parse_message` continua removendo `<think>` do `content` final (comportamento atual).
  - Em `conftest.FakeLLM.chat`, `on_delta=None` entra na assinatura e é ignorado.

- [ ] **Step 4: Rodar tudo**

Run: `pytest tests/test_llm_streaming.py tests/test_llm_providers.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 5: Fixture real (só se o llama-server estiver no ar; senão pule e registre no PR)**

Run: `curl -N http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"qwen3.6-35b-a3b","stream":true,"stream_options":{"include_usage":true},"chat_template_kwargs":{"enable_thinking":true},"messages":[{"role":"user","content":"Diga oi em uma frase."}]}' > tests/fixtures/llamacpp-stream.sse`
Adicione `test_parses_real_llamacpp_stream` lendo o arquivo. Expected: PASS. Se o campo do raciocínio no servidor real não for `reasoning_content`, ajuste o parser e documente em `docs/deploy/local-windows-llamacpp.md`.

- [ ] **Step 6: Commit**

```bash
git add nickel/core/llm.py nickel/config.py tests/test_llm_streaming.py tests/fixtures tests/conftest.py
git commit -m "feat(llm): streaming opcional com raciocínio, tool calls e uso"
```

---

### Task 4: ReasoningTracker e resumo determinístico

**Files:**
- Create: `nickel/core/reasoning.py`
- Test: `tests/test_reasoning.py`

**Interfaces:**
- Consumes: `AuditLog.record(..., text_limit=...)` (Task 1), `DeltaCallback` (Task 3).
- Produces:
  - `ReasoningSummary` (frozen): `headline: str, conclusion: str, chars: int, tokens_est: int, tools_mentioned: tuple[str, ...]`.
  - `summarize_reasoning(text: str, tool_names: Iterable[str] = ()) -> ReasoningSummary`: `headline` é a primeira frase (até 140 caracteres, com `…` se cortada), `conclusion` a última frase, `tokens_est = ceil(len(text)/4)` e `tools_mentioned` os nomes de ferramenta citados no texto.
  - `ReasoningTracker(audit, *, step: int, tool_names=(), interval_s: float = 0.4, tail_chars: int = 600, clock=time.monotonic)` com `feed(channel: str, text: str) -> None` e `finish() -> ReasoningSummary`.
  - `reasoning/progress` (no máximo um a cada `interval_s`) leva `{step, chars, tokens_est, headline, tail, content_chars}`. `reasoning/final` leva `{step, text, headline, conclusion, chars, tokens_est, tools_mentioned}` e só é emitido se houve raciocínio.

- [ ] **Step 1: Escrever os testes que falham** (relógio falso)
  - `test_summary_headline_conclusion_and_tools`: texto com 3 frases citando `reminder_create` → valores exatos.
  - `test_summary_truncates_headline_at_140_chars`.
  - `test_progress_is_throttled`: 50 `feed` dentro de 0,1 s → 1 `progress`; após avançar o relógio em 0,5 s, outro.
  - `test_content_channel_does_not_emit_reasoning_events`: só `content` → nenhum `reasoning/*`.
  - `test_final_event_keeps_up_to_4000_chars_and_emitted_once`.
  - `test_finish_without_reasoning_emits_nothing`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_reasoning.py -v`
Expected: FAIL (módulo inexistente).

- [ ] **Step 3: Implementar** conforme as assinaturas. `finish()` é idempotente. O resumo não chama nenhum modelo.

- [ ] **Step 4: Rodar**

Run: `pytest tests/test_reasoning.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nickel/core/reasoning.py tests/test_reasoning.py
git commit -m "feat(audit): rastreador e resumo determinístico do raciocínio"
```

---

### Task 5: Instrumentar o agente (turno, rota, prompt, modelo, ferramentas)

**Files:**
- Modify: `nickel/core/agent.py` (`Turn`, `handle`, `confirm`, `cancel`, `_run_tool`, `_run_llm`), `nickel/config.py` se faltar algo
- Modify: `tests/conftest.py` (`StreamingFakeLLM`)
- Test: `tests/test_agent_events.py`

**Interfaces:**
- Consumes: `run_scope`/`new_run_id` (T1), `CATALOG` (T2), `on_delta` e `LLMReply.reasoning/usage` (T3), `ReasoningTracker` (T4).
- Produces:
  - `Turn.think: bool | None = None` (sobrescreve `think` nas opções do LLM quando definido).
  - Eventos por turno, todos com o mesmo `run_id`: `turn/start {channel, workspace, chars}`; `route/resolved {command, workspace, switched, auto}`; `prompt/built {messages, history, tools, system_chars, est_tokens}`; `llm/start {step, model, backend}`; `llm/done {step, duration_ms, prompt_tokens, completion_tokens, tokens_per_second, tool_calls}`; `llm/error {step, detail}`; `tool/start {arguments}`; `tool/ok|error {arguments, summary}` com `duration_ms`; `turn/done {duration_ms, steps, reply_chars}`; `turn/error {detail}`.
  - `StreamingFakeLLM(replies, deltas)` em `conftest.py` (`supports_stream = True`; chama `on_delta` com os `deltas` roteirizados antes de devolver o `LLMReply`).

- [ ] **Step 1: Escrever os testes que falham**
  - `test_turn_emits_ordered_events_with_single_run_id`: fluxo com uma ferramenta; a sequência `(kind,status)` contém, em ordem, `turn/start, route/resolved, prompt/built, llm/start, llm/done, tool/start, tool/ok, llm/start, llm/done, turn/done`, todos com o mesmo `run_id` não nulo.
  - `test_reasoning_events_only_when_model_streams_reasoning`: com `StreamingFakeLLM` e deltas de `reasoning`, há um `reasoning/final` com `headline`; com o `FakeLLM` simples não há nenhum `reasoning/*`.
  - `test_tool_events_carry_duration_and_redacted_arguments`.
  - `test_llm_error_records_llm_error_and_turn_error_and_returns_reply`: `LLMError` → `llm/error` e `turn/error`, e a resposta de erro ao usuário continua igual à de hoje.
  - `test_turn_think_override_reaches_llm_options`: `Turn(think=True)` → `options["think"] is True`.
  - `test_confirm_and_cancel_share_a_run_scope` (confirmações geram `run_id` próprio).
  - `test_non_stream_llm_never_gets_on_delta`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_agent_events.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar**
  - `handle`, `confirm` e `cancel` rodam dentro de `run_scope(new_run_id())`; o tempo total usa `time.monotonic()`.
  - `_run_llm` passa `on_delta` somente se `getattr(llm, "supports_stream", False) and settings.llm_stream`, usando um `ReasoningTracker` por chamada (`step` = índice do laço); `finish()` roda também no ramo de erro.
  - `_run_tool` emite `tool/start` antes e `duration_ms` depois. O campo `summary` de `tool/ok` continua limitado pelo `_redact`.
  - A emissão existente de `llm/error` com `settings.llm_model` passa a incluir `step`.

- [ ] **Step 4: Rodar tudo**

Run: `pytest tests/test_agent_events.py -v && pytest -q`
Expected: PASS e os testes antigos do agente continuam verdes.

- [ ] **Step 5: Commit**

```bash
git add nickel/core/agent.py tests/conftest.py tests/test_agent_events.py
git commit -m "feat(agent): eventos reais de turno, prompt, modelo, raciocínio e ferramentas"
```

---

### Task 6: Instrumentar o resto do projeto (voz, WhatsApp, outbound, sistema)

**Files:**
- Modify: `nickel/channels/voice.py` (estados), `nickel/channels/whatsapp.py:164` (resposta e erro), `nickel/core/outbound.py:40`, `nickel/app.py` (`lifespan`: `system/startup`, `system/shutdown`, `system/health`)
- Modify: `tests/test_event_catalog.py` (remover o `xfail`)
- Test: `tests/test_system_events.py`

**Interfaces:**
- Consumes: `AuditLog.record`, `run_scope`, `CATALOG`.
- Produces:
  - `voice/{listening,transcribing,thinking,speaking,idle,error}` a cada troca de estado do `VoiceController` (detalhe: `{chars}` na transcrição, `{detail}` no erro). A sessão de voz roda em `run_scope` para o mesmo `run_id` do turno do agente.
  - `whatsapp/replied {chars, voice: bool}` e `whatsapp/error {detail}` (o `received` já existe).
  - `system/startup {version, llm, workspace_count}`, `system/shutdown`, `system/health {llm, whatsapp, google, spotify, obsidian, voice}` emitido no startup após a consulta de `/api/state`.

- [ ] **Step 1: Escrever os testes que falham**
  - `test_voice_state_changes_emit_events` (VoiceController com recorder/STT falsos).
  - `test_whatsapp_reply_and_error_events`.
  - `test_outbound_event_keeps_existing_shape`.
  - `test_lifespan_emits_startup_and_shutdown` (TestClient com `background=False`).
  - `test_health_event_contains_service_snapshot_without_secrets`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_system_events.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar** os pontos acima e remover o `xfail` de `test_every_cataloged_kind_is_emitted_somewhere`.

- [ ] **Step 4: Rodar tudo**

Run: `pytest -q`
Expected: PASS, incluindo o teste de completude do catálogo.

- [ ] **Step 5: Commit**

```bash
git add nickel tests
git commit -m "feat(audit): eventos de voz, WhatsApp, outbound e sistema"
```

---

### Task 7: API: SSE, execuções, relatório, catálogo e `think` no chat

**Files:**
- Create: `nickel/core/report.py`
- Modify: `nickel/app.py` (rotas novas e `/api/chat`)
- Test: `tests/test_monitor_api.py`

**Interfaces:**
- Consumes: `AuditLog.subscribe/since/run/runs` (T1), `CATALOG/PHASES/PHASE_LABELS` (T2).
- Produces:
  - `report.render_run_report(events: list[dict]) -> str`: Markdown com título (`run_id`, data, duração), tabela de etapas (`hora | tipo | nome | status | ms`), seção "Ferramentas", seção "Raciocínio" (headline e conclusão, ou "sem raciocínio expandido") e seção "Erros".
  - `GET /api/events/stream?after=<int>&once=<bool>`: `text/event-stream`; cada evento é `id: <id>\nevent: audit\ndata: <json em uma linha>\n\n`; comentário `: ping` a cada 15 s; `after` omitido reprisa os últimos 100; o cabeçalho `Last-Event-ID` vale como `after`; `once=true` fecha após a reprise; o assinante sai do barramento num `finally`.
  - `GET /api/events/catalog` → `{kinds, phases: {"kind/status": phase}, labels}`.
  - `GET /api/runs?limit=` e `GET /api/runs/{run_id}` (404 se não houver) e `GET /api/runs/{run_id}/report.md` (`text/markdown`).
  - `POST /api/chat` aceita `think: bool | null` e repassa para `Turn.think`.

- [ ] **Step 1: Escrever os testes que falham**
  - `test_stream_replays_last_events_then_closes_with_once`: 3 eventos gravados → 3 blocos SSE com `id` crescente.
  - `test_stream_respects_after_and_last_event_id`.
  - `test_stream_frames_survive_newlines_and_unicode_in_detail`: `data:` sempre em uma linha, JSON válido.
  - `test_stream_unsubscribes_on_client_disconnect` (`has_subscribers()` volta a `False`).
  - `test_runs_list_detail_and_404`.
  - `test_report_markdown_contains_steps_tools_and_errors`.
  - `test_catalog_endpoint_matches_module`.
  - `test_chat_accepts_think_flag`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_monitor_api.py -v`
Expected: FAIL (404 nas rotas).

- [ ] **Step 3: Implementar** com `StreamingResponse` e um gerador assíncrono (`await asyncio.wait_for(queue.get(), 15)` para o ping). Serialização com `json.dumps(..., ensure_ascii=False)`, que já escapa `\n`.

- [ ] **Step 4: Rodar tudo**

Run: `pytest tests/test_monitor_api.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nickel/core/report.py nickel/app.py tests/test_monitor_api.py
git commit -m "feat(api): SSE de eventos, execuções, relatório e catálogo"
```

---

### Task 8: Núcleo do monitor no frontend (reducer puro testado)

**Files:**
- Create: `nickel/ui/static/monitor-core.js`, `tests/js/monitor-core.test.mjs`

**Interfaces:**
- Consumes: formato de evento e `GET /api/events/catalog` (Task 7).
- Produces (exports ES module):
  - `initialState() -> {phase, since, runId, reasoning: {tail, headline, chars, tokens, active}, timeline: [], runs: {}}`
  - `applyEvent(state, event, catalog) -> state` (puro): atualiza `phase` por `catalog.phases[kind/status]`; `reasoning/progress` atualiza `reasoning`; `reasoning/final` fixa o resumo e `active=false`; `turn/start` zera `reasoning` e fixa `runId`; mantém no máximo 500 itens em `timeline`; eventos fora de ordem (id menor ou igual ao último) são ignorados.
  - `groupByRun(events) -> [{runId, startedAt, events, errors, durationMs}]`
  - `formatDuration(ms) -> string` (`"850 ms"`, `"2,4 s"`, `"1 min 05 s"`).

- [ ] **Step 1: Escrever os testes que falham** (`node:test`)
  - `applyEvent muda a fase pela tabela do catálogo`.
  - `ignora evento repetido ou fora de ordem`.
  - `reasoning/progress atualiza tail e headline; final desativa`.
  - `turn/start zera o raciocínio anterior`.
  - `timeline respeita o limite de 500 itens`.
  - `groupByRun agrupa e conta erros`.
  - `formatDuration` com os três formatos.
  - `evento de tipo desconhecido não quebra e não muda a fase`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `node --test tests/js`
Expected: FAIL (módulo inexistente).

- [ ] **Step 3: Implementar `monitor-core.js`**, sem DOM e sem `fetch`.

- [ ] **Step 4: Rodar**

Run: `node --test tests/js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nickel/ui/static/monitor-core.js tests/js
git commit -m "feat(ui): reducer puro do monitor com testes em node"
```

---

### Task 9: Aba Monitor (DOM, SSE e estilo)

**Files:**
- Modify: `nickel/ui/static/index.html` (abas "Conversa" e "Monitor", checkbox "Mostrar raciocínio"), `nickel/ui/static/style.css`
- Create: `nickel/ui/static/monitor.js`, `nickel/ui/static/monitor.css`
- Test: `tests/test_ui_static.py`

**Interfaces:**
- Consumes: `monitor-core.js` (T8), `/api/events/stream`, `/api/events/catalog`, `/api/runs`, `/api/runs/{id}/report.md`.
- Produces na tela:
  - Faixa de estado: rótulo da fase (`PHASE_LABELS`), cronômetro desde `since`, cor por fase e pulso suave em `thinking`/`speaking`; `aria-live="polite"` no rótulo e `prefers-reduced-motion` respeitado.
  - Painel "Raciocínio": resumo (headline, caracteres, tokens estimados, tokens/s do último `llm/done`), trecho final (`tail`) em fonte monoespaçada e "Ver completo" (usa `reasoning/final.text`). Sem raciocínio, mostra "Sem raciocínio expandido (think desligado)" e as fases.
  - Linha do tempo agrupada por execução, com filtros por tipo, detalhe JSON expansível e duração; lista de execuções com link "Baixar relatório".
  - Conexão `EventSource` com reconexão e `after=<último id>`; indicador "ao vivo / reconectando".
  - O checkbox "Mostrar raciocínio" envia `think: true` no `/api/chat` e guarda a escolha em `localStorage` (com `try/catch`).

- [ ] **Step 1: Escrever o teste que falha**
  - `test_static_monitor_assets_are_served_and_referenced`: `GET /static/monitor.js`, `/static/monitor-core.js`, `/static/monitor.css` → 200; `GET /` contém `id="monitor"` e as três referências.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_ui_static.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar** a UI. Textos em PT-BR no imperativo ("Mostrar raciocínio", "Baixar relatório"). Sem CDN e sem build.

- [ ] **Step 4: Rodar os testes**

Run: `pytest -q && node --test tests/js`
Expected: PASS.

- [ ] **Step 5: Verificação visual** (Playwright/navegador do app contra `nickel serve` com o llama-server ou o Ollama)
  Envie uma mensagem com "Mostrar raciocínio" ligado. Expected: a faixa passa por Roteando → Montando prompt → Pensando → Respondendo → Ocioso; o painel de raciocínio enche em tempo real; a linha do tempo mostra os eventos do turno com durações; "Baixar relatório" devolve o Markdown. Derrube o servidor LLM no meio de um turno. Expected: a fase vira "Erro" e a faixa mostra "reconectando" sem travar.

- [ ] **Step 6: Commit**

```bash
git add nickel/ui/static tests/test_ui_static.py
git commit -m "feat(ui): aba Monitor com estado, raciocínio ao vivo e linha do tempo"
```

---

### Task 10: Documentação de processos gerada do código

**Files:**
- Create: `nickel/core/docs_gen.py`, `docs/adr/0004-monitor-e-auditoria.md`, `docs/processos/catalogo-de-eventos.md` e `docs/processos/fluxo-de-um-turno.md` (gerados)
- Modify: `nickel/cli.py` (subcomando `audit`), `README.md`
- Test: `tests/test_docs_gen.py`

**Interfaces:**
- Consumes: `CATALOG, PHASES, PHASE_LABELS, TURN_FLOW` (T2), `render_run_report` (T7), `AuditLog.run/runs`.
- Produces:
  - `render_catalog_md() -> str` (tabela por kind: descrição, estados, campos, fonte; mais a tabela de fases) e `render_turn_flow_md() -> str` (diagrama Mermaid `sequenceDiagram` a partir de `TURN_FLOW`).
  - CLI: `nickel audit docs [--out docs/processos]` regrava os dois arquivos; `nickel audit report <run_id>` imprime o relatório; `nickel audit export [--since ISO] [--format jsonl|md]`.

- [ ] **Step 1: Escrever os testes que falham**
  - `test_committed_docs_match_generator`: o conteúdo dos arquivos em `docs/processos/` é igual ao do gerador (barra divergência).
  - `test_catalog_md_lists_every_kind_and_status`.
  - `test_turn_flow_mermaid_has_one_arrow_per_step`.
  - `test_cli_audit_report_prints_markdown_for_existing_run` e `test_cli_audit_report_unknown_run_exits_nonzero`.
  - `test_cli_audit_export_jsonl_one_event_per_line`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_docs_gen.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar**, rodar `python -m nickel audit docs` para gerar os arquivos e escrever o ADR-0004 (decisão: `AuditLog` como barramento, SSE, resumo determinístico, catálogo como fonte única) mais uma seção "Monitor e auditoria" no README.

- [ ] **Step 4: Rodar tudo**

Run: `pytest -q && node --test tests/js && python -m pyflakes nickel tests`
Expected: PASS e `pyflakes` sem saída.

- [ ] **Step 5: Commit**

```bash
git add nickel docs README.md tests
git commit -m "docs(audit): catálogo e fluxo gerados do código, CLI de auditoria e ADR-0004"
```
