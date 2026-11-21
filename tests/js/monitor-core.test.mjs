import test from "node:test";
import assert from "node:assert/strict";
import {
  initialState,
  applyEvent,
  groupByRun,
  formatDuration,
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
