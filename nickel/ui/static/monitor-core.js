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
    reasoningSteps: {},
    llmDone: false,
    lastLlm: null,
    think: null,
    timeline: [],
    runs: {},
  };
}

const blank = (text) => !text || !String(text).trim();

// Raciocínio por passo: um passo só com espaços (ex.: "<think>\n" de template) nunca
// substitui nem apaga o raciocínio útil de outro passo.
function updateStep(steps, key, detail) {
  const step = String(detail.step ?? 0);
  const prev = steps[step];
  if (key === "reasoning/progress") {
    if (blank(detail.tail)) return steps;
    return {
      ...steps,
      [step]: {
        tail: detail.tail,
        headline: detail.headline || "",
        chars: detail.chars || 0,
        tokens: detail.tokens_est || 0,
        active: true,
      },
    };
  }
  if (blank(detail.text)) return prev ? { ...steps, [step]: { ...prev, active: false } } : steps;
  const base = prev || { tail: "", headline: "", chars: 0, tokens: 0 };
  return {
    ...steps,
    [step]: {
      ...base,
      headline: detail.headline || base.headline,
      chars: detail.chars || base.chars,
      tokens: detail.tokens_est || base.tokens,
      active: false,
      final: detail.text,
    },
  };
}

function latestReasoning(steps) {
  const list = stepList(steps);
  if (!list.length) return emptyReasoning();
  const { step, ...reasoning } = list[list.length - 1];
  return reasoning;
}

function stepList(steps) {
  return Object.entries(steps || {})
    .map(([step, r]) => ({ step: Number(step), ...r }))
    .filter(hasReasoning)
    .sort((a, b) => a.step - b.step);
}

// Passos do turno atual que têm raciocínio, em ordem.
export function reasoningSteps(state) {
  return stepList(state.reasoningSteps);
}

// O que o painel de raciocínio deve dizer quando não há texto para mostrar.
export function reasoningView(state) {
  if (!state.runId) return "empty";
  if (hasReasoning(state.reasoning)) return "reasoning";
  // think ligado e nenhum raciocínio: o modelo pulou (ex.: foi direto à tool). Desconhecido conta como desligado.
  if (state.llmDone) return state.think === true ? "skipped" : "off";
  if (state.phase === "idle" || state.phase === "error") return "none";
  return "waiting";
}

// Chave da linha do tempo filtrada: muda só se aparece um evento visível ou um grupo novo.
export function timelineKey(timeline, filter, version) {
  const visible = filterTimeline(timeline, filter || {});
  const last = visible.length ? visible[visible.length - 1].id : 0;
  const runs = new Set(visible.map((e) => e.run_id ?? null)).size;
  return `${version}:${last}:${runs}`;
}

// Mantém só as execuções que ainda aparecem na linha do tempo (aba aberta por dias).
function pruneRuns(runs, timeline) {
  const alive = new Set(timeline.map((e) => e.run_id).filter(Boolean));
  const out = {};
  for (const [id, info] of Object.entries(runs)) if (alive.has(id)) out[id] = info;
  return out;
}

function trackRun(runs, event, replaced) {
  if (!event.run_id) return runs;
  const prev = runs[event.run_id] || { startedAt: event.at, events: 0, errors: 0 };
  return {
    ...runs,
    [event.run_id]: {
      ...prev,
      lastAt: event.at,
      events: prev.events + (replaced ? 0 : 1),
      errors: prev.errors + (event.status === "error" ? 1 : 0),
    },
  };
}

const isProgress = (e) => e.kind === "reasoning" && e.status === "progress";
const stepOf = (e) => String((e.detail || {}).step ?? 0);

// Um `reasoning/progress` novo substitui o anterior do mesmo run e passo: o parcial chega
// até 2,5 vezes por segundo e, sem isto, empurraria `turn/start` para fora da linha do tempo.
function withoutOlderProgress(timeline, event) {
  if (!isProgress(event)) return timeline;
  const run = event.run_id ?? null;
  const step = stepOf(event);
  return timeline.filter((e) => !(isProgress(e) && (e.run_id ?? null) === run && stepOf(e) === step));
}

// Sinal de fala para a GUI: "start" mostra "Parar"; "end" (tts/done ou tts/error) esconde.
// Independe da fase: um tts/error sem tts/start (voz desligada) não muda a fase, mas encerra a fala.
// tts/skipped (nota de voz do WhatsApp pulada porque já havia fala) não é fim de fala: devolve null.
export function speechSignal(event) {
  if (!event || event.kind !== "tts") return null;
  if (event.status === "start") return "start";
  if (event.status === "done" || event.status === "error") return "end";
  return null;
}

// A fala roda em segundo plano e pode cruzar o turno seguinte: tts/start só assume a fase
// quando nada mais está em curso (idle, error ou outra fala), e tts/done/error só a devolvem
// quando ela ainda é "speaking". Fora disso o evento vai só para a linha do tempo.
const TTS_START_FROM = new Set(["idle", "error", "speaking"]);

function ttsMayChangePhase(event, current) {
  if (event.kind !== "tts") return true;
  if (event.status === "start") return TTS_START_FROM.has(current);
  if (event.status === "done" || event.status === "error") return current === "speaking";
  return true;
}

export function applyEvent(state, event, catalog) {
  if (!event || typeof event.id !== "number" || event.id <= state.lastId) return state;

  const detail = event.detail || {};
  const base = withoutOlderProgress(state.timeline, event);
  const timeline = [...base, event].slice(-TIMELINE_LIMIT);
  let runs = trackRun(state.runs, event, base.length < state.timeline.length);
  if (state.timeline.length >= TIMELINE_LIMIT) runs = pruneRuns(runs, timeline);
  const next = { ...state, lastId: event.id, timeline, runs };

  const phase = ((catalog && catalog.phases) || {})[`${event.kind}/${event.status}`];
  if (phase && phase !== state.phase && ttsMayChangePhase(event, state.phase)) {
    next.phase = phase;
    next.since = event.at;
  }

  const key = `${event.kind}/${event.status}`;
  if (key === "turn/start") {
    next.runId = event.run_id || null;
    next.reasoning = emptyReasoning();
    next.reasoningSteps = {};
    next.llmDone = false;
    next.lastLlm = null;
    next.think = null;
  } else if (key === "llm/start") {
    next.think = typeof detail.think === "boolean" ? detail.think : null;
  } else if (key === "reasoning/progress" || key === "reasoning/final") {
    next.reasoningSteps = updateStep(state.reasoningSteps || {}, key, detail);
    next.reasoning = latestReasoning(next.reasoningSteps);
  } else if (key === "llm/done") {
    next.llmDone = true;
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
    fakeAction: null,
  };
  for (const e of byId(events)) {
    const d = e.detail || {};
    // A nova tentativa pedida ao modelo não é erro do turno; o <fake> que persiste é.
    if (e.status === "error" && !isFakeRetry(e)) s.errors += 1;
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
        if (e.name === FAKE_TOOL) {
          // Não é ferramenta: o modelo afirmou uma ação sem chamá-la.
          s.fakeAction = d.detail || d.summary || "ação inventada pelo modelo";
          break;
        }
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

export const FAKE_TOOL = "<fake>";
const FAKE_RETRY_MARK = "pedindo nova tentativa";

function isFakeRetry(e) {
  const detail = (e.detail || {}).detail;
  return e.name === FAKE_TOOL && typeof detail === "string" && detail.includes(FAKE_RETRY_MARK);
}

// Texto do aviso no resumo: distingue a nova tentativa pedida da afirmação que persistiu.
export function fakeActionLabel(summary) {
  const detail = summary && summary.fakeAction;
  if (!detail) return null;
  if (String(detail).includes(FAKE_RETRY_MARK)) {
    return "o modelo afirmou uma ação sem chamar a ferramenta; nova tentativa pedida";
  }
  return `ação inventada pelo modelo: ${detail}`;
}

export function num(value, digits = 0) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("pt-BR", { maximumFractionDigits: digits });
}

// Resumo de uma linha de um evento, para a linha do tempo.
export function eventHint(e) {
  const d = e.detail || {};
  switch (`${e.kind}/${e.status}`) {
    case "turn/start": return [d.channel && `canal ${d.channel}`, d.workspace, d.chars != null && `${d.chars} caracteres`].filter(Boolean).join(" · ");
    case "route/resolved": return [d.workspace, d.command, d.switched && "trocou de área"].filter(Boolean).join(" · ");
    case "prompt/built": return `${num(d.messages)} mensagens · ~${num(d.est_tokens)} tokens`;
    case "llm/start": return [d.step != null && `passo ${d.step}`, d.model, d.backend].filter(Boolean).join(" · ");
    case "llm/done": return [
      d.completion_tokens != null && `${num(d.completion_tokens)} tokens`,
      d.tokens_per_second != null && `${num(d.tokens_per_second, 1)} tok/s`,
      Array.isArray(d.tool_calls) && d.tool_calls.length ? `${d.tool_calls.length} chamada(s): ${d.tool_calls.join(", ")}` : null,
    ].filter(Boolean).join(" · ");
    case "reasoning/progress": return `${num(d.chars)} caracteres`;
    case "reasoning/answering": return d.step != null ? `passo ${d.step}` : "";
    case "reasoning/final": return d.headline || "";
    case "tool/ok":
    case "tool/error": return d.summary || d.detail || "";
    case "turn/done": return [d.steps != null && `${d.steps} passos`, d.reply_chars != null && `${num(d.reply_chars)} caracteres`].filter(Boolean).join(" · ");
    case "tts/start": return [d.provider, d.voice, d.chars != null && `${num(d.chars)} caracteres`].filter(Boolean).join(" · ");
    case "tts/done": return [d.chars != null && `${num(d.chars)} caracteres`, d.interrupted && "interrompida"].filter(Boolean).join(" · ");
    case "tts/error":
    case "tts/skipped": return d.detail || "";
    default: return d.detail || "";
  }
}

export function elapsedMs(since, nowMs) {
  if (!since) return null;
  const start = Date.parse(since);
  if (!Number.isFinite(start)) return null;
  return Math.max(0, nowMs - start);
}
