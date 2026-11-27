import test from "node:test";
import assert from "node:assert/strict";
import { initialState, applyEvent, chatStatus } from "../../nickel/ui/static/monitor-core.js";

const catalog = {
  phases: {
    "turn/start": "routing", "route/resolved": "prompting", "prompt/built": "thinking", "llm/start": "thinking",
    "reasoning/progress": "thinking", "reasoning/answering": "answering", "tool/start": "tool", "tool/ok": "thinking",
    "tool/error": "thinking", "confirmation/requested": "confirming", "turn/done": "idle", "turn/error": "error",
    "tts/start": "speaking", "tts/done": "idle", "tts/error": "error",
  },
};
const T0 = Date.parse("2026-11-26T15:00:00Z");
const at = (s) => new Date(T0 + s * 1000).toISOString();
let id = 0;
const ev = (kind, name, status, s, detail = {}, extra = {}) => ({ id: ++id, kind, name, status, at: at(s), run_id: "r1", detail, ...extra });

function feed(events) {
  return events.reduce((state, e) => applyEvent(state, e, catalog), initialState());
}

test("sem turno: Pronto, sem detalhes", () => {
  assert.deepEqual(chatStatus(initialState(), T0), { active: false, phase: "idle", text: "Pronto", detail: "", elapsedMs: null });
});

test("lendo o pedido sem pensar, com tempo desde o início do turno", () => {
  const s = feed([ev("turn", "ui", "start", 0), ev("llm", "m", "start", 1, { think: false })]);
  assert.deepEqual(chatStatus(s, T0 + 4000), { active: true, phase: "thinking", text: "Lendo o pedido", detail: "", elapsedMs: 4000 });
});

test("pensar ligado sem raciocínio ainda não diz Pensando", () => {
  const s = feed([ev("turn", "ui", "start", 0), ev("llm", "m", "start", 1, { think: true })]);
  assert.equal(chatStatus(s, T0 + 2000).text, "Lendo o pedido");
});

test("pensando com raciocínio em curso mostra os caracteres", () => {
  const s = feed([ev("turn", "ui", "start", 0), ev("llm", "m", "start", 1, { think: true }), ev("reasoning", "model", "progress", 2, { step: 0, chars: 1234, tail: "abc" })]);
  const st = chatStatus(s, T0 + 3000);
  assert.equal(st.text, "Pensando");
  assert.equal(st.detail, "1.234 caracteres de raciocínio");
});

test("ferramenta em execução e análise do resultado", () => {
  const base = [ev("turn", "ui", "start", 0), ev("llm", "m", "start", 1), ev("llm", "m", "done", 2), ev("tool", "reminder_create", "start", 3)];
  assert.equal(chatStatus(feed(base), T0 + 3500).text, "Executando reminder_create");
  const s = feed([...base, ev("tool", "reminder_create", "ok", 4), ev("llm", "m", "start", 4)]);
  assert.equal(chatStatus(s, T0 + 5000).text, "Analisando o resultado de reminder_create");
});

test("escrevendo e depois pronto com duração e tok/s", () => {
  const s1 = feed([ev("turn", "ui", "start", 0), ev("llm", "m", "start", 1), ev("reasoning", "model", "answering", 2)]);
  assert.equal(chatStatus(s1, T0 + 2500).text, "Escrevendo a resposta");
  const s2 = feed([
    ev("turn", "ui", "start", 0), ev("llm", "m", "start", 1),
    ev("llm", "m", "done", 3, { tokens_per_second: 17.94 }), ev("turn", "ui", "done", 3, {}, { duration_ms: 3200 }),
  ]);
  const st = chatStatus(s2, T0 + 9000);
  assert.equal(st.active, false);
  assert.equal(st.text, "Pronto");
  assert.match(st.detail, /^última resposta em .+ · 17,9 tok\/s$/);
});

test("fala conta o tempo desde o início da fala; erro mostra o motivo", () => {
  const s = feed([ev("turn", "ui", "start", 0), ev("turn", "ui", "done", 2, {}, { duration_ms: 2000 }), ev("tts", "edge", "start", 3)]);
  assert.deepEqual(
    [chatStatus(s, T0 + 5000).text, chatStatus(s, T0 + 5000).elapsedMs],
    ["Falando a resposta", 2000],
  );
  const e = applyEvent(s, ev("tts", "edge", "error", 6, { detail: "sem internet" }), catalog);
  assert.equal(chatStatus(e, T0 + 7000).text, "Erro: sem internet");
});
