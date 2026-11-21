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
  const next = {
    ...state,
    lastId: event.id,
    timeline: [...state.timeline, event].slice(-TIMELINE_LIMIT),
    runs: trackRun(state.runs, event),
  };

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
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
  const total = Math.round(ms / 1000);
  const min = Math.floor(total / 60);
  const sec = String(total % 60).padStart(2, "0");
  return `${min} min ${sec} s`;
}
