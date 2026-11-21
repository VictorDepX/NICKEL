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
