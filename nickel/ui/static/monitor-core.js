// Núcleo puro do monitor: sem DOM e sem fetch. A UI (Task 9) consome estas funções.

export const TIMELINE_LIMIT = 500;

const emptyReasoning = () => ({ tail: "", headline: "", chars: 0, tokens: 0, active: false });

export function initialState() {
  return {
    phase: "idle",
    since: null,
    runId: null,
    lastId: 0,
    reasoning: emptyReasoning(),
    lastLlm: null,
    timeline: [],
    runs: {},
  };
}

// Mantém só as execuções que ainda aparecem na linha do tempo (aba aberta por dias).
function pruneRuns(runs, timeline) {
  const alive = new Set(timeline.map((e) => e.run_id).filter(Boolean));
  const out = {};
  for (const [id, info] of Object.entries(runs)) if (alive.has(id)) out[id] = info;
  return out;
}

function trackRun(runs, event) {
  if (!event.run_id) return runs;
  const prev = runs[event.run_id] || { startedAt: event.at, events: 0, errors: 0 };
  return {
    ...runs,
    [event.run_id]: {
      ...prev,
      lastAt: event.at,
      events: prev.events + 1,
      errors: prev.errors + (event.status === "error" ? 1 : 0),
    },
  };
}

export function applyEvent(state, event, catalog) {
  if (!event || typeof event.id !== "number" || event.id <= state.lastId) return state;

  const detail = event.detail || {};
  const timeline = [...state.timeline, event].slice(-TIMELINE_LIMIT);
  let runs = trackRun(state.runs, event);
  if (state.timeline.length >= TIMELINE_LIMIT) runs = pruneRuns(runs, timeline);
  const next = { ...state, lastId: event.id, timeline, runs };

  const phase = ((catalog && catalog.phases) || {})[`${event.kind}/${event.status}`];
  if (phase && phase !== state.phase) {
    next.phase = phase;
    next.since = event.at;
  }

  const key = `${event.kind}/${event.status}`;
  if (key === "turn/start") {
    next.runId = event.run_id || null;
    next.reasoning = emptyReasoning();
  } else if (key === "reasoning/progress") {
    next.reasoning = {
      tail: detail.tail || "",
      headline: detail.headline || "",
      chars: detail.chars || 0,
      tokens: detail.tokens_est || 0,
      active: true,
    };
  } else if (key === "reasoning/final") {
    next.reasoning = {
      ...state.reasoning,
      headline: detail.headline || state.reasoning.headline,
      chars: detail.chars || state.reasoning.chars,
      tokens: detail.tokens_est || state.reasoning.tokens,
      active: false,
      final: detail.text || "",
    };
  } else if (key === "llm/done") {
    next.lastLlm = {
      tokensPerSecond: detail.tokens_per_second ?? null,
      completionTokens: detail.completion_tokens ?? null,
      promptTokens: detail.prompt_tokens ?? null,
    };
  }
  return next;
}

export function groupByRun(events) {
  const groups = new Map();
  for (const e of events) {
    const id = e.run_id ?? null;
    if (!groups.has(id)) groups.set(id, { runId: id, startedAt: e.at, events: [], firstId: e.id });
    const g = groups.get(id);
    g.events.push(e);
    if (e.id < g.firstId) { g.firstId = e.id; g.startedAt = e.at; }
  }
  const out = [];
  for (const g of groups.values()) {
    const closing = g.events.find(
      (e) => e.kind === "turn" && (e.status === "done" || e.status === "error") && e.duration_ms != null,
    );
    const durationMs = closing
      ? closing.duration_ms
      : g.events.reduce((sum, e) => sum + (e.duration_ms || 0), 0);
    out.push({
      runId: g.runId,
      startedAt: g.startedAt,
      events: g.events,
      errors: g.events.filter((e) => e.status === "error").length,
      durationMs,
      firstId: g.firstId,
    });
  }
  out.sort((a, b) => b.firstId - a.firstId);
  return out.map(({ firstId, ...rest }) => rest);
}

export function formatDuration(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "—";
  if (Math.round(ms) < 1000) return `${Math.round(ms)} ms`;
  const tenths = Math.round(ms / 100);
  if (tenths < 600) return `${(tenths / 10).toFixed(1).replace(".", ",")} s`;
  const total = Math.round(ms / 1000);
  const min = Math.floor(total / 60);
  const sec = String(total % 60).padStart(2, "0");
  return `${min} min ${sec} s`;
}

// `final === ""` (ou ausente após um passo sem raciocínio) conta como "sem raciocínio".
export function hasReasoning(reasoning) {
  if (!reasoning) return false;
  if (reasoning.final !== undefined) return reasoning.final !== "";
  return Boolean(reasoning.active || reasoning.tail);
}

export function filterTimeline(events, { kinds = null, onlyErrors = false } = {}) {
  return events.filter((e) => (!kinds || kinds.has(e.kind)) && (!onlyErrors || e.status === "error"));
}

const byId = (events) => events.slice().sort((a, b) => a.id - b.id);

export function runSummary(events) {
  const s = {
    status: events.length ? "running" : "empty",
    channel: null, workspace: null, command: null, inputChars: null,
    model: null, backend: null, requestedBackend: null, llmCalls: 0,
    messages: null, history: null, tools: null, systemChars: null, estTokens: null,
    promptTokens: null, completionTokens: null, tokensPerSecond: null,
    toolCalls: [], errors: 0, steps: null, durationMs: null, replyChars: null, error: null,
  };
  for (const e of byId(events)) {
    const d = e.detail || {};
    if (e.status === "error") s.errors += 1;
    switch (`${e.kind}/${e.status}`) {
      case "turn/start":
        s.channel = d.channel ?? null;
        s.workspace = d.workspace ?? null;
        s.inputChars = d.chars ?? null;
        break;
      case "route/resolved":
        s.command = d.command ?? null;
        if (d.workspace) s.workspace = d.workspace;
        break;
      case "prompt/built":
        s.messages = d.messages ?? null;
        s.history = d.history ?? null;
        s.tools = d.tools ?? null;
        s.systemChars = d.system_chars ?? null;
        s.estTokens = d.est_tokens ?? null;
        break;
      case "llm/start":
        s.llmCalls += 1;
        s.model = d.model ?? s.model;
        s.backend = d.backend ?? s.backend;
        s.requestedBackend = d.requested_backend ?? s.requestedBackend;
        break;
      case "llm/done":
        if (d.prompt_tokens != null) s.promptTokens = d.prompt_tokens;
        if (d.completion_tokens != null) s.completionTokens = (s.completionTokens || 0) + d.completion_tokens;
        if (d.tokens_per_second != null) s.tokensPerSecond = d.tokens_per_second;
        break;
      case "tool/ok":
      case "tool/error":
        s.toolCalls.push({ name: e.name, ok: e.status === "ok", summary: d.summary ?? null, durationMs: e.duration_ms ?? null });
        break;
      case "turn/done":
        s.status = "done";
        s.steps = d.steps ?? null;
        s.durationMs = e.duration_ms ?? d.duration_ms ?? null;
        s.replyChars = d.reply_chars ?? null;
        break;
      case "turn/error":
        s.status = "error";
        s.durationMs = e.duration_ms ?? d.duration_ms ?? null;
        s.error = d.detail ?? null;
        break;
    }
  }
  return s;
}

// Fases percorridas (sem repetições seguidas), com a duração de cada uma; a última fica em aberto.
export function runPhases(events, catalog) {
  const phases = (catalog && catalog.phases) || {};
  const out = [];
  for (const e of byId(events)) {
    const phase = phases[`${e.kind}/${e.status}`];
    if (!phase || (out.length && out[out.length - 1].phase === phase)) continue;
    out.push({ phase, at: e.at, ms: null });
  }
  for (let i = 0; i < out.length - 1; i++) {
    const ms = Date.parse(out[i + 1].at) - Date.parse(out[i].at);
    out[i].ms = Number.isFinite(ms) ? Math.max(0, ms) : null;
  }
  return out;
}

export function elapsedMs(since, nowMs) {
  if (!since) return null;
  const start = Date.parse(since);
  if (!Number.isFinite(start)) return null;
  return Math.max(0, nowMs - start);
}
