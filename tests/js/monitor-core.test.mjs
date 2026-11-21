import test from "node:test";
import assert from "node:assert/strict";
import {
  initialState,
  applyEvent,
  groupByRun,
  formatDuration,
  hasReasoning,
  filterTimeline,
  runSummary,
  runPhases,
  elapsedMs,
  reasoningSteps,
  reasoningView,
  timelineKey,
  eventHint,
  speechSignal,
} from "../../nickel/ui/static/monitor-core.js";

const catalog = {
  phases: {
    "turn/start": "routing",
    "llm/start": "prompting",
    "reasoning/progress": "thinking",
    "tool/start": "tool",
    "turn/done": "idle",
    "turn/error": "error",
  },
  labels: { idle: "Ocioso", thinking: "Pensando" },
};

let nextId = 1;
const ev = (kind, status, extra = {}) => ({
  id: nextId++,
  at: "2026-11-19T10:00:00+00:00",
  kind,
  name: kind,
  status,
  detail: {},
  run_id: "r1",
  duration_ms: null,
  ...extra,
});

test("applyEvent muda a fase pela tabela do catálogo", () => {
  nextId = 1;
  let s = initialState();
  s = applyEvent(s, ev("turn", "start", { at: "2026-11-19T10:00:01+00:00" }), catalog);
  assert.equal(s.phase, "routing");
  assert.equal(s.since, "2026-11-19T10:00:01+00:00");
  assert.equal(s.runId, "r1");
  s = applyEvent(s, ev("tool", "start"), catalog);
  assert.equal(s.phase, "tool");
});

test("ignora evento repetido ou fora de ordem", () => {
  nextId = 1;
  const a = ev("turn", "start");
  const b = ev("tool", "start");
  let s = applyEvent(initialState(), a, catalog);
  s = applyEvent(s, b, catalog);
  const again = applyEvent(s, b, catalog);
  assert.equal(again, s);
  const old = applyEvent(s, { ...a, kind: "turn", status: "done" }, catalog);
  assert.equal(old.phase, "tool");
  assert.equal(old.timeline.length, 2);
});

test("reasoning/progress atualiza tail e headline; final desativa", () => {
  nextId = 1;
  let s = applyEvent(initialState(), ev("turn", "start"), catalog);
  s = applyEvent(
    s,
    ev("reasoning", "progress", {
      detail: { step: 1, chars: 120, tokens_est: 30, headline: "Analisando", tail: "...fim" },
    }),
    catalog,
  );
  assert.deepEqual(s.reasoning, {
    tail: "...fim", headline: "Analisando", chars: 120, tokens: 30, active: true,
  });
  assert.equal(s.phase, "thinking");
  s = applyEvent(
    s,
    ev("reasoning", "final", {
      detail: { step: 1, text: "texto completo", headline: "Resumo", chars: 200, tokens_est: 50 },
    }),
    catalog,
  );
  assert.equal(s.reasoning.active, false);
  assert.equal(s.reasoning.headline, "Resumo");
  assert.equal(s.reasoning.final, "texto completo");
});

test("turn/start zera o raciocínio anterior", () => {
  nextId = 1;
  let s = applyEvent(initialState(), ev("turn", "start", { run_id: "a" }), catalog);
  s = applyEvent(
    s,
    ev("reasoning", "progress", { run_id: "a", detail: { chars: 9, tokens_est: 3, headline: "h", tail: "t" } }),
    catalog,
  );
  s = applyEvent(s, ev("turn", "start", { run_id: "b" }), catalog);
  assert.equal(s.runId, "b");
  assert.deepEqual(s.reasoning, { tail: "", headline: "", chars: 0, tokens: 0, active: false });
});

test("timeline respeita o limite de 500 itens", () => {
  nextId = 1;
  let s = initialState();
  for (let i = 0; i < 520; i++) s = applyEvent(s, ev("tool", "start"), catalog);
  assert.equal(s.timeline.length, 500);
  assert.equal(s.timeline[0].id, 21);
  assert.equal(s.timeline[499].id, 520);
});

test("groupByRun agrupa e conta erros", () => {
  nextId = 1;
  const events = [
    ev("turn", "start", { run_id: "a" }),
    ev("llm", "done", { run_id: "a", duration_ms: 300 }),
    ev("tool", "error", { run_id: "a", duration_ms: 200 }),
    ev("turn", "start", { run_id: "b" }),
    ev("turn", "done", { run_id: "b", duration_ms: 5000 }),
    ev("llm", "done", { run_id: "b", duration_ms: 100 }),
    ev("system", "info", { run_id: null }),
  ];
  const g = groupByRun(events);
  assert.deepEqual(g.map((x) => x.runId), [null, "b", "a"]);
  const a = g.find((x) => x.runId === "a");
  assert.equal(a.events.length, 3);
  assert.equal(a.errors, 1);
  assert.equal(a.durationMs, 500);
  assert.equal(a.startedAt, events[0].at);
  const b = g.find((x) => x.runId === "b");
  assert.equal(b.durationMs, 5000);
  assert.equal(b.errors, 0);
});

test("formatDuration com os três formatos", () => {
  assert.equal(formatDuration(850), "850 ms");
  assert.equal(formatDuration(2400), "2,4 s");
  assert.equal(formatDuration(65000), "1 min 05 s");
});

test("evento de tipo desconhecido não quebra e não muda a fase", () => {
  nextId = 1;
  let s = applyEvent(initialState(), ev("turn", "start"), catalog);
  const next = applyEvent(s, ev("alienigena", "xyz"), catalog);
  assert.equal(next.phase, "routing");
  assert.equal(next.since, s.since);
  assert.equal(next.timeline.length, 2);
  assert.doesNotThrow(() => applyEvent(next, ev("x", "y"), {}));
});

test("llm/done guarda tokens por segundo", () => {
  nextId = 1;
  const s = applyEvent(
    initialState(),
    ev("llm", "done", { detail: { step: 1, prompt_tokens: 10, completion_tokens: 20, tokens_per_second: 33.5 } }),
    catalog,
  );
  assert.deepEqual(s.lastLlm, { tokensPerSecond: 33.5, completionTokens: 20, promptTokens: 10 });
});

test("formatDuration trata valores ausentes e arredonda para o minuto", () => {
  assert.equal(formatDuration(null), "—");
  assert.equal(formatDuration(undefined), "—");
  assert.equal(formatDuration(NaN), "—");
  assert.equal(formatDuration(59950), "1 min 00 s");
  assert.equal(formatDuration(59940), "59,9 s");
  assert.equal(formatDuration(999.6), "1,0 s");
  assert.equal(formatDuration(0), "0 ms");
});

test("runs fora da linha do tempo são podados", () => {
  nextId = 1;
  let s = initialState();
  for (let i = 0; i < 520; i++) s = applyEvent(s, ev("tool", "start", { run_id: `r${i}` }), catalog);
  const inTimeline = new Set(s.timeline.map((e) => e.run_id));
  assert.equal(Object.keys(s.runs).length, 500);
  for (const id of Object.keys(s.runs)) assert.ok(inTimeline.has(id), id);
  assert.equal(s.runs.r0, undefined);
  assert.equal(s.runs.r519.events, 1);
});

test("hasReasoning: final vazio conta como sem raciocínio", () => {
  assert.equal(hasReasoning(initialState().reasoning), false);
  assert.equal(hasReasoning({ tail: "", headline: "", chars: 0, tokens: 0, active: false, final: "" }), false);
  assert.equal(hasReasoning({ tail: "x", headline: "", chars: 1, tokens: 1, active: true }), true);
  assert.equal(hasReasoning({ tail: "", headline: "", chars: 0, tokens: 0, active: false, final: "pensei" }), true);
  assert.equal(hasReasoning(null), false);
});

test("filterTimeline por tipo e só erros", () => {
  nextId = 1;
  const events = [ev("turn", "start"), ev("tool", "error"), ev("llm", "done"), ev("llm", "error")];
  assert.equal(filterTimeline(events, {}).length, 4);
  assert.deepEqual(filterTimeline(events, { kinds: new Set(["llm"]) }).map((e) => e.id), [3, 4]);
  assert.deepEqual(filterTimeline(events, { onlyErrors: true }).map((e) => e.id), [2, 4]);
  assert.deepEqual(filterTimeline(events, { kinds: new Set(["llm"]), onlyErrors: true }).map((e) => e.id), [4]);
});

test("runSummary junta informações básicas e técnicas do turno", () => {
  nextId = 1;
  const events = [
    ev("turn", "start", { detail: { channel: "ui", workspace: "geral", chars: 12 } }),
    ev("route", "resolved", { detail: { command: null, workspace: "estudos", switched: true, auto: true } }),
    ev("prompt", "built", { detail: { messages: 7, history: 4, tools: 9, system_chars: 900, est_tokens: 420 } }),
    ev("llm", "start", { detail: { step: 1, model: "qwen", backend: "local", requested_backend: "auto" } }),
    ev("llm", "done", { duration_ms: 800, detail: { step: 1, prompt_tokens: 400, completion_tokens: 50, tokens_per_second: 20, tool_calls: 1 } }),
    ev("tool", "start", { name: "notes.search", detail: { arguments: { q: "x" } } }),
    ev("tool", "error", { name: "notes.search", duration_ms: 30, detail: { summary: "falhou" } }),
    ev("llm", "start", { detail: { step: 2, model: "qwen", backend: "local" } }),
    ev("llm", "done", { duration_ms: 500, detail: { step: 2, prompt_tokens: 480, completion_tokens: 30, tokens_per_second: 25 } }),
    ev("turn", "done", { duration_ms: 1500, detail: { duration_ms: 1500, steps: 2, reply_chars: 88 } }),
  ];
  const s = runSummary(events.slice().reverse());
  assert.equal(s.status, "done");
  assert.equal(s.channel, "ui");
  assert.equal(s.workspace, "estudos");
  assert.equal(s.inputChars, 12);
  assert.equal(s.model, "qwen");
  assert.equal(s.backend, "local");
  assert.equal(s.llmCalls, 2);
  assert.equal(s.messages, 7);
  assert.equal(s.estTokens, 420);
  assert.equal(s.promptTokens, 480);
  assert.equal(s.completionTokens, 80);
  assert.equal(s.tokensPerSecond, 25);
  assert.deepEqual(s.toolCalls, [{ name: "notes.search", ok: false, summary: "falhou", durationMs: 30 }]);
  assert.equal(s.errors, 1);
  assert.equal(s.steps, 2);
  assert.equal(s.durationMs, 1500);
  assert.equal(s.replyChars, 88);
  assert.equal(runSummary([]).status, "empty");
  const failed = runSummary([ev("turn", "start"), ev("turn", "error", { detail: { detail: "LLM caiu" } })]);
  assert.equal(failed.status, "error");
  assert.equal(failed.error, "LLM caiu");
});

test("runPhases lista as fases percorridas com a duração de cada uma", () => {
  nextId = 1;
  const at = (s) => `2026-11-19T10:00:0${s}+00:00`;
  const events = [
    ev("turn", "start", { at: at(0) }),
    ev("llm", "start", { at: at(1) }),
    ev("reasoning", "progress", { at: at(2) }),
    ev("route", "resolved", { at: at(3) }),
    ev("reasoning", "progress", { at: at(4) }),
    ev("turn", "done", { at: at(5) }),
  ];
  const p = runPhases(events, catalog);
  assert.deepEqual(p.map((x) => x.phase), ["routing", "prompting", "thinking", "idle"]);
  assert.deepEqual(p.map((x) => x.ms), [1000, 1000, 3000, null]);
  assert.deepEqual(runPhases(events, {}), []);
});

test("elapsedMs desde o início da fase", () => {
  assert.equal(elapsedMs(null, 0), null);
  assert.equal(elapsedMs("2026-11-19T10:00:00Z", Date.parse("2026-11-19T10:00:03Z")), 3000);
  assert.equal(elapsedMs("2026-11-19T10:00:05Z", Date.parse("2026-11-19T10:00:03Z")), 0);
  assert.equal(elapsedMs("lixo", 0), null);
});

test("raciocínio por passo: passo vazio não apaga o útil e a lista mostra cada passo", () => {
  nextId = 1;
  let s = applyEvent(initialState(), ev("turn", "start"), catalog);
  s = applyEvent(s, ev("reasoning", "progress", { detail: { step: 0, chars: 20, tokens_est: 5, headline: "Vou agendar", tail: "Vou agendar o lembrete" } }), catalog);
  s = applyEvent(s, ev("reasoning", "final", { detail: { step: 0, text: "Vou agendar o lembrete.", headline: "Vou agendar o lembrete.", chars: 23, tokens_est: 6 } }), catalog);
  s = applyEvent(s, ev("reasoning", "final", { detail: { step: 1, text: "\n", headline: "", chars: 1, tokens_est: 1 } }), catalog);
  s = applyEvent(s, ev("reasoning", "progress", { detail: { step: 1, chars: 2, tokens_est: 1, headline: "", tail: "  " } }), catalog);
  assert.equal(s.reasoning.final, "Vou agendar o lembrete.");
  assert.deepEqual(reasoningSteps(s).map((x) => x.step), [0]);
  s = applyEvent(s, ev("reasoning", "progress", { detail: { step: 1, chars: 9, tokens_est: 3, headline: "Confirmo", tail: "Confirmo." } }), catalog);
  assert.equal(s.reasoning.tail, "Confirmo.");
  assert.equal(s.reasoning.active, true);
  assert.deepEqual(reasoningSteps(s).map((x) => x.step), [0, 1]);
  assert.equal(reasoningSteps(s)[0].final, "Vou agendar o lembrete.");
  s = applyEvent(s, ev("turn", "start", { run_id: "r2" }), catalog);
  assert.deepEqual(reasoningSteps(s), []);
});

test("reasoningView: sem turno, aguardando, think desligado e com raciocínio", () => {
  nextId = 1;
  const cat = { phases: { ...catalog.phases, "prompt/built": "thinking", "llm/done": "answering" } };
  let s = initialState();
  assert.equal(reasoningView(s), "empty");
  s = applyEvent(s, ev("turn", "start"), cat);
  assert.equal(reasoningView(s), "waiting");
  s = applyEvent(s, ev("prompt", "built"), cat);
  assert.equal(s.phase, "thinking");
  assert.equal(reasoningView(s), "waiting");
  const off = applyEvent(s, ev("llm", "done", { detail: { step: 0 } }), cat);
  assert.equal(reasoningView(off), "off");
  const failed = applyEvent(s, ev("turn", "error"), cat);
  assert.equal(reasoningView(failed), "none");
  const thinking = applyEvent(s, ev("reasoning", "progress", { detail: { step: 0, chars: 3, tokens_est: 1, tail: "abc" } }), cat);
  assert.equal(reasoningView(thinking), "reasoning");
  const after = applyEvent(thinking, ev("llm", "done", { detail: { step: 0 } }), cat);
  assert.equal(reasoningView(after), "reasoning");
});

test("turn/start zera lastLlm", () => {
  nextId = 1;
  let s = applyEvent(initialState(), ev("llm", "done", { detail: { tokens_per_second: 40 } }), catalog);
  assert.equal(s.lastLlm.tokensPerSecond, 40);
  s = applyEvent(s, ev("turn", "start"), catalog);
  assert.equal(s.lastLlm, null);
});

test("timelineKey só muda quando o resultado filtrado muda", () => {
  nextId = 1;
  let s = applyEvent(initialState(), ev("turn", "start"), catalog);
  const noReasoning = { kinds: new Set(["turn", "tool"]) };
  const before = timelineKey(s.timeline, noReasoning, 0);
  s = applyEvent(s, ev("reasoning", "progress", { detail: { step: 0, tail: "x" } }), catalog);
  assert.equal(timelineKey(s.timeline, noReasoning, 0), before);
  assert.notEqual(timelineKey(s.timeline, {}, 0), before);
  assert.notEqual(timelineKey(s.timeline, noReasoning, 1), before);
  s = applyEvent(s, ev("tool", "start"), catalog);
  assert.notEqual(timelineKey(s.timeline, noReasoning, 0), before);
});

// ---------------------------------------------------------------- revisão final

test("linha do tempo guarda só o último progress de cada execução e passo", () => {
  nextId = 1;
  let s = applyEvent(initialState(), ev("turn", "start"), catalog);
  const progress = (step, run_id = "r1") => ev("reasoning", "progress", { run_id, detail: { step, tail: `p${nextId}` } });
  for (let i = 0; i < 5; i++) s = applyEvent(s, progress(0), catalog);
  s = applyEvent(s, progress(1), catalog);
  s = applyEvent(s, progress(1), catalog);
  s = applyEvent(s, progress(0, "r2"), catalog);
  s = applyEvent(s, ev("reasoning", "final", { detail: { step: 0, text: "fim" } }), catalog);
  const kept = s.timeline.map((e) => [e.run_id, e.kind, e.status, e.detail.step ?? null, e.id]);
  assert.deepEqual(kept, [
    ["r1", "turn", "start", null, 1],
    ["r1", "reasoning", "progress", 0, 6],
    ["r1", "reasoning", "progress", 1, 8],
    ["r2", "reasoning", "progress", 0, 9],
    ["r1", "reasoning", "final", 0, 10],
  ]);
  assert.equal(s.lastId, 10);
  assert.equal(reasoningSteps(s)[0].final, "fim");
});

test("muitos progress não empurram turn/start para fora da linha do tempo", () => {
  nextId = 1;
  let s = applyEvent(initialState(), ev("turn", "start"), catalog);
  for (let i = 0; i < 2000; i++) s = applyEvent(s, ev("reasoning", "progress", { detail: { step: 0, tail: "x" } }), catalog);
  assert.equal(s.timeline.length, 2);
  assert.equal(s.timeline[0].status, "start");
});

test("fase vai de Pensando para Respondendo quando chega reasoning/answering", () => {
  nextId = 1;
  const cat = {
    phases: { "turn/start": "routing", "llm/start": "thinking", "reasoning/progress": "thinking", "reasoning/answering": "answering", "turn/done": "idle" },
  };
  let s = applyEvent(initialState(), ev("turn", "start"), cat);
  s = applyEvent(s, ev("llm", "start", { detail: { step: 0 } }), cat);
  s = applyEvent(s, ev("reasoning", "progress", { detail: { step: 0, tail: "penso" } }), cat);
  assert.equal(s.phase, "thinking");
  s = applyEvent(s, ev("llm", "done", { detail: { step: 0, tool_calls: [] } }), cat);
  assert.equal(s.phase, "thinking"); // llm/done não inventa a fase
  s = applyEvent(s, ev("reasoning", "answering", { at: "2026-11-19T10:00:07.250+00:00", detail: { step: 0 } }), cat);
  assert.equal(s.phase, "answering");
  assert.equal(s.since, "2026-11-19T10:00:07.250+00:00");
  const phases = runPhases(s.timeline, cat).map((p) => p.phase);
  assert.deepEqual(phases, ["routing", "thinking", "answering"]);
});

test("runPhases mede durações com milissegundos", () => {
  nextId = 1;
  const cat = { phases: { "turn/start": "routing", "llm/start": "thinking", "turn/done": "idle" } };
  const events = [
    ev("turn", "start", { at: "2026-11-19T10:00:00.100+00:00" }),
    ev("llm", "start", { at: "2026-11-19T10:00:00.350+00:00" }),
    ev("turn", "done", { at: "2026-11-19T10:00:01+00:00" }), // formato antigo convive
  ];
  assert.deepEqual(runPhases(events, cat).map((p) => p.ms), [250, 650, null]);
});

test("eventHint de llm/done lista as chamadas pedidas", () => {
  nextId = 1;
  assert.equal(eventHint(ev("llm", "done", { detail: { tool_calls: ["echo", "notes_add"] } })), "2 chamada(s): echo, notes_add");
  assert.equal(eventHint(ev("llm", "done", { detail: { tool_calls: [], completion_tokens: 5 } })), "5 tokens");
});

test("<fake> aparece na linha do tempo e no resumo, fora das ferramentas usadas", () => {
  nextId = 1;
  const fake = ev("tool", "error", { name: "<fake>", detail: { detail: "modelo afirmou ação sem chamar a ferramenta" } });
  assert.equal(eventHint(fake), "modelo afirmou ação sem chamar a ferramenta");
  assert.equal(eventHint(ev("tool", "ok", { detail: { summary: "eco: a" } })), "eco: a");
  const s = runSummary([
    ev("turn", "start"),
    ev("tool", "ok", { name: "echo", duration_ms: 3, detail: { summary: "eco: a" } }),
    fake,
    ev("turn", "done", { duration_ms: 10, detail: { steps: 1 } }),
  ]);
  assert.deepEqual(s.toolCalls.map((t) => t.name), ["echo"]);
  assert.equal(s.fakeAction, "modelo afirmou ação sem chamar a ferramenta");
  assert.equal(runSummary([ev("turn", "start")]).fakeAction, null);
});

test("speechSignal: tts/start mostra Parar; tts/done e tts/error escondem, mesmo sem mudar a fase", () => {
  nextId = 1;
  assert.equal(speechSignal(ev("tts", "start")), "start");
  assert.equal(speechSignal(ev("tts", "done")), "end");
  assert.equal(speechSignal(ev("tts", "error", { detail: { detail: "voz indisponível" } })), "end");
  assert.equal(speechSignal(ev("voice", "speaking")), null);
  assert.equal(speechSignal(ev("turn", "done")), null);
  assert.equal(speechSignal(null), null);
});

const ttsCatalog = {
  phases: {
    ...catalog.phases,
    "llm/start": "thinking",
    "tts/start": "speaking",
    "tts/done": "idle",
    "tts/error": "error",
  },
};

test("applyEvent: tts/start só vira Falando a partir de idle, error ou speaking", () => {
  nextId = 1;
  let s = initialState();
  s = applyEvent(s, ev("tts", "start"), ttsCatalog);
  assert.equal(s.phase, "speaking"); // idle → speaking
  s = applyEvent(s, ev("tts", "start"), ttsCatalog);
  assert.equal(s.phase, "speaking"); // speaking → speaking (fala nova substitui a anterior)
  s = applyEvent(s, ev("turn", "error"), ttsCatalog);
  s = applyEvent(s, ev("tts", "start"), ttsCatalog);
  assert.equal(s.phase, "speaking"); // error → speaking

  s = applyEvent(s, ev("turn", "start"), ttsCatalog);
  s = applyEvent(s, ev("llm", "start"), ttsCatalog);
  const since = s.since;
  const start = ev("tts", "start", { at: "2026-11-19T10:05:00+00:00" });
  s = applyEvent(s, start, ttsCatalog);
  assert.equal(s.phase, "thinking"); // o próximo turno já começou: a fase não volta para Falando
  assert.equal(s.since, since);
  assert.equal(s.timeline[s.timeline.length - 1], start); // mas o evento entra na linha do tempo
});

test("applyEvent: tts/done e tts/error só mudam a fase quando ela é Falando", () => {
  nextId = 1;
  let s = initialState();
  s = applyEvent(s, ev("tts", "start"), ttsCatalog);
  s = applyEvent(s, ev("tts", "done"), ttsCatalog);
  assert.equal(s.phase, "idle");
  s = applyEvent(s, ev("tts", "start"), ttsCatalog);
  s = applyEvent(s, ev("tts", "error"), ttsCatalog);
  assert.equal(s.phase, "error");

  s = applyEvent(s, ev("turn", "start"), ttsCatalog);
  s = applyEvent(s, ev("llm", "start"), ttsCatalog);
  const done = ev("tts", "done", { detail: { chars: 3, interrupted: true } });
  s = applyEvent(s, done, ttsCatalog);
  assert.equal(s.phase, "thinking"); // a fala que terminou no meio do turno não marca Ocioso
  s = applyEvent(s, ev("tts", "error", { detail: { detail: "voz ocupada" } }), ttsCatalog);
  assert.equal(s.phase, "thinking"); // nem Erro
  assert.ok(s.timeline.includes(done));

  s = applyEvent(initialState(), ev("tts", "error", { detail: { detail: "voz indisponível" } }), ttsCatalog);
  assert.equal(s.phase, "idle"); // tts/error sem fala ativa (voz desligada) não vira Erro
});

test("eventHint resume os eventos de fala", () => {
  assert.equal(
    eventHint(ev("tts", "start", { detail: { provider: "voicestudio", voice: "marina", chars: 42 } })),
    "voicestudio · marina · 42 caracteres",
  );
  assert.equal(eventHint(ev("tts", "start", { detail: { provider: "piper", voice: "", chars: 1200 } })), "piper · 1.200 caracteres");
  assert.equal(eventHint(ev("tts", "done", { detail: { chars: 42 } })), "42 caracteres");
  assert.equal(eventHint(ev("tts", "done", { detail: { chars: 42, interrupted: true } })), "42 caracteres · interrompida");
  assert.equal(eventHint(ev("tts", "error", { detail: { source: "ui", detail: "voz ocupada" } })), "voz ocupada");
});
