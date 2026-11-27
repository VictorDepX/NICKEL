// Lógica pura da Conversa: o turno atual a partir do monitor e a reconciliação das mensagens locais.
import type { StoredMessage } from "./api";
import { FAKE_TOOL, reasoningSteps, type AuditEvent, type MonitorState } from "./monitor-core";

export type ToolCallState = "running" | "ok" | "error";

export interface TurnToolCall {
  id: number;
  name: string;
  state: ToolCallState;
  input: unknown;
  /** Resumo devolvido pela ferramenta (`detail.summary` de tool/ok | tool/error). */
  output: string | null;
  durationMs: number | null;
}

export interface TurnReasoning {
  text: string;
  chars: number;
  active: boolean;
  /** Do `llm/start` de cada passo até o modelo começar a responder (ou o raciocínio final). */
  durationMs: number | null;
}

export interface TurnView {
  runId: string;
  startedAt: string | null;
  done: boolean;
  durationMs: number | null;
  tokensPerSecond: number | null;
  reasoning: TurnReasoning | null;
  tools: TurnToolCall[];
}

const byId = (events: AuditEvent[]) => events.slice().sort((a, b) => a.id - b.id);
const stepOf = (e: AuditEvent) => Number(e.detail?.step ?? 0);

function reasoningDuration(events: AuditEvent[], steps: number[], active: boolean, nowMs: number): number | null {
  let total = 0;
  let known = false;
  for (const step of steps) {
    const start = events.find((e) => e.kind === "llm" && e.status === "start" && stepOf(e) === step);
    if (!start) continue;
    const end = events.find(
      (e) =>
        stepOf(e) === step &&
        ((e.kind === "reasoning" && (e.status === "answering" || e.status === "final")) ||
          (e.kind === "llm" && (e.status === "done" || e.status === "error"))),
    );
    const from = Date.parse(start.at);
    const to = end ? Date.parse(end.at) : active ? nowMs : NaN;
    if (Number.isFinite(from) && Number.isFinite(to)) {
      total += Math.max(0, to - from);
      known = true;
    }
  }
  return known ? total : null;
}

/** Turno atual do monitor (eventos com `run_id === state.runId`): raciocínio, ferramentas e números. */
export function turnView(state: MonitorState, nowMs = Date.now()): TurnView | null {
  if (!state.runId) return null;
  const events = byId(state.timeline.filter((e) => e.run_id === state.runId));
  const start = events.find((e) => e.kind === "turn" && e.status === "start");
  const end = events.find((e) => e.kind === "turn" && (e.status === "done" || e.status === "error"));
  const llmDone = [...events].reverse().find((e) => e.kind === "llm" && e.status === "done");

  const steps = reasoningSteps(state);
  let reasoning: TurnReasoning | null = null;
  if (steps.length) {
    const active = steps.some((s) => s.active);
    reasoning = {
      text: steps.map((s) => (s.final ?? s.tail ?? "").trim()).filter(Boolean).join("\n\n"),
      chars: steps.reduce((sum, s) => sum + (s.chars || 0), 0),
      active,
      durationMs: reasoningDuration(events, steps.map((s) => s.step), active, nowMs),
    };
  }

  const tools: TurnToolCall[] = [];
  const closed = new Set<number>();
  for (const e of events) {
    if (e.kind !== "tool" || e.status !== "start" || e.name === FAKE_TOOL) continue;
    const finish = events.find(
      (f) => f.id > e.id && !closed.has(f.id) && f.kind === "tool" && f.name === e.name && (f.status === "ok" || f.status === "error"),
    );
    if (finish) closed.add(finish.id);
    const summary = finish?.detail?.summary;
    tools.push({
      id: e.id,
      name: e.name,
      state: finish ? (finish.status === "ok" ? "ok" : "error") : "running",
      input: e.detail?.arguments,
      output: typeof summary === "string" && summary ? summary : null,
      durationMs: finish?.duration_ms ?? null,
    });
  }

  const tps = llmDone?.detail?.tokens_per_second;
  return {
    runId: state.runId,
    startedAt: start?.at ?? null,
    done: Boolean(end),
    durationMs: end?.duration_ms ?? null,
    tokensPerSecond: typeof tps === "number" ? tps : null,
    reasoning,
    tools,
  };
}

/**
 * Índice da resposta do assistente que pertence ao turno (a última criada depois do início dele).
 * `created_at` vem em segundos e `turn/start` em milissegundos: 1 s de folga.
 */
export function turnAnchor(messages: { role: string; created_at: string }[], turn: TurnView | null): number {
  if (!turn?.done || !turn.startedAt) return -1;
  const startMs = Date.parse(turn.startedAt);
  if (!Number.isFinite(startMs)) return -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "assistant") continue;
    const at = Date.parse(m.created_at);
    return Number.isFinite(at) && at + 1000 >= startMs ? i : -1;
  }
  return -1;
}

export interface LocalMessage {
  key: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  /** Maior id do servidor quando a mensagem local nasceu: só uma mensagem mais nova pode substituí-la. */
  afterId: number;
}

/** Esconde as mensagens locais que o servidor já gravou (mesmo papel e texto, id mais novo). */
export function pendingLocals(server: StoredMessage[], locals: LocalMessage[]): LocalMessage[] {
  const used = new Set<number>();
  return locals.filter((local) => {
    const match = server.find(
      (m) => !used.has(m.id) && m.id > local.afterId && m.role === local.role && m.content.trim() === local.content.trim(),
    );
    if (match) used.add(match.id);
    return !match;
  });
}

export const lastServerId = (messages: StoredMessage[] | undefined) =>
  messages?.length ? Math.max(...messages.map((m) => m.id)) : 0;

/** mm:ss para o cronômetro da linha de status. */
export function clock(ms: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return "";
  const total = Math.floor(ms / 1000);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/** Hora da mensagem: só HH:MM hoje; dia/mês antes disso. */
export function messageTime(iso: string, now = new Date()): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const sameDay = date.toDateString() === now.toDateString();
  return date.toLocaleString(
    "pt-BR",
    sameDay ? { hour: "2-digit", minute: "2-digit" } : { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" },
  );
}
