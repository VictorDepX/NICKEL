import { expect, test } from "vitest";
import type { StoredMessage } from "./api";
import { activityPlacement, clock, pendingLocals, turnAnchor, turnView, type LocalMessage } from "./chat-turn";
import { applyEvent, initialState, type AuditEvent } from "./monitor-core";

const T0 = Date.parse("2026-11-27T15:00:00Z");
const at = (s: number) => new Date(T0 + s * 1000).toISOString();
let id = 0;
const ev = (kind: string, name: string, status: string, s: number, detail: Record<string, unknown> = {}, extra: Partial<AuditEvent> = {}): AuditEvent => ({
  id: ++id, kind, name, status, at: at(s), run_id: "r1", detail, duration_ms: null, ...extra,
});
const feed = (events: AuditEvent[]) => events.reduce((state, e) => applyEvent(state, e, { phases: {} }), initialState());

test("sem turno: null", () => {
  expect(turnView(initialState())).toBeNull();
});

test("uma ferramenta por tool/start, com argumentos, resultado e estado", () => {
  const state = feed([
    ev("turn", "ui", "start", 0),
    ev("tool", "reminder_create", "start", 1, { arguments: { text: "água" } }),
    ev("tool", "reminder_create", "ok", 2, { arguments: { text: "água" }, summary: "Lembrete criado" }, { duration_ms: 120 }),
    ev("tool", "<fake>", "error", 3, { detail: "afirmou" }),
    ev("tool", "spotify_play", "start", 4, { arguments: {} }),
    ev("tool", "spotify_play", "error", 5, { summary: "sem conta" }),
    ev("tool", "notes_search", "start", 6, { arguments: { q: "x" } }),
  ]);
  const view = turnView(state)!;
  expect(view.tools.map((t) => [t.name, t.state, t.output])).toEqual([
    ["reminder_create", "ok", "Lembrete criado"],
    ["spotify_play", "error", "sem conta"],
    ["notes_search", "running", null],
  ]);
  expect(view.tools[0].input).toEqual({ text: "água" });
  expect(view.tools[0].durationMs).toBe(120);
  expect(view.done).toBe(false);
});

test("raciocínio: caracteres somados e duração do llm/start até a resposta", () => {
  const state = feed([
    ev("turn", "ui", "start", 0),
    ev("llm", "m", "start", 1, { step: 0, think: true }),
    ev("reasoning", "model", "progress", 2, { step: 0, chars: 100, tail: "pensando" }),
    ev("reasoning", "model", "answering", 4.5, { step: 0 }),
    ev("reasoning", "model", "final", 6, { step: 0, chars: 120, text: "pensei bastante" }),
    ev("llm", "m", "done", 6, { step: 0, tokens_per_second: 21.5 }),
    ev("turn", "ui", "done", 7, {}, { duration_ms: 7000 }),
  ]);
  const view = turnView(state)!;
  expect(view.reasoning).toEqual({ text: "pensei bastante", chars: 120, active: false, durationMs: 3500 });
  expect(view.done).toBe(true);
  expect(view.durationMs).toBe(7000);
  expect(view.tokensPerSecond).toBe(21.5);
});

test("raciocínio em curso conta até agora", () => {
  const state = feed([
    ev("turn", "ui", "start", 0),
    ev("llm", "m", "start", 1, { step: 0 }),
    ev("reasoning", "model", "progress", 2, { step: 0, chars: 50, tail: "hmm" }),
  ]);
  const view = turnView(state, T0 + 5000)!;
  expect(view.reasoning?.active).toBe(true);
  expect(view.reasoning?.durationMs).toBe(4000);
});

const msg = (mid: number, role: string, content: string, created_at = at(0)): StoredMessage => ({
  id: mid, channel: "ui", role, content, attachments: [], created_at,
});

test("âncora: última resposta criada depois do início do turno (1 s de folga)", () => {
  const state = feed([ev("turn", "ui", "start", 10.6), ev("turn", "ui", "done", 10.9)]);
  const view = turnView(state);
  const list = [msg(1, "assistant", "velha", at(2)), msg(2, "user", "oi", at(10)), msg(3, "assistant", "nova", at(10))];
  expect(turnAnchor(list, view)).toBe(2);
  expect(turnAnchor(list.slice(0, 2), view)).toBe(-1);
});

test("mensagens locais somem quando o servidor grava uma igual mais nova", () => {
  const local = (key: string, role: LocalMessage["role"], content: string, afterId: number): LocalMessage => ({
    key, role, content, afterId, created_at: at(0),
  });
  const locals = [local("a", "user", "oi", 5), local("b", "assistant", "Olá!", 5), local("c", "assistant", "Essa ação não está mais pendente.", 5)];
  const server = [msg(5, "assistant", "Olá!"), msg(6, "user", "oi"), msg(7, "assistant", "Olá!")];
  expect(pendingLocals(server, locals).map((m) => m.key)).toEqual(["c"]);
  expect(pendingLocals(server.slice(0, 1), locals).map((m) => m.key)).toEqual(["a", "b", "c"]);
});

test("cronômetro mm:ss", () => {
  expect(clock(65_400)).toBe("01:05");
  expect(clock(null)).toBe("");
});

test("blocos: âncora quando há resposta; no fim só turno da ui em curso", () => {
  const ui = turnView(feed([ev("turn", "ui", "start", 0)]));
  const zap = turnView(feed([ev("turn", "whatsapp", "start", 0)]));
  const uiDone = turnView(feed([ev("turn", "ui", "start", 0), ev("turn", "ui", "error", 1)]));
  expect(ui?.channel).toBe("ui");
  expect(activityPlacement(ui, -1)).toBe("bottom");
  expect(activityPlacement(zap, -1)).toBe("none");
  expect(activityPlacement(zap, 3)).toBe("anchor");
  expect(activityPlacement(uiDone, -1)).toBe("none");
  expect(activityPlacement(null, -1)).toBe("none");
});
