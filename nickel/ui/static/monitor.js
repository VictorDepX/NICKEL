// Aba Monitor: liga o SSE de auditoria ao reducer puro e desenha o estado.
// Regra de segurança: textos de eventos vêm do LLM e das ferramentas, então
// tudo entra no DOM por textContent/append (nunca como HTML).
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
} from "/static/monitor-core.js";

const $ = (id) => document.getElementById(id);
const GROUPS_SHOWN = 30;
const EVENTS_PER_GROUP = 200;

let catalog = { kinds: {}, phases: {}, labels: {} };
let state = initialState();
let source = null;
let renderQueued = false;
let runsTimer = null;
let timelineKey = "";
let filtersKey = "";
let filterVersion = 0;
const hiddenKinds = new Set();
let onlyErrors = false;
const openEvents = new Set();
const runChoice = new Map();

// ------------------------------------------------------------ utilidades

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (typeof value === "boolean") el[key] = value;
    else el.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

const label = (phase) => (catalog.labels && catalog.labels[phase]) || phase;
const visible = () => !$("monitor").hidden;
const short = (id) => (id ? String(id).slice(0, 8) : "—");
const clip = (text, max = 120) => {
  const s = String(text ?? "").replace(/\s+/g, " ").trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
};

function num(value, digits = 0) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("pt-BR", { maximumFractionDigits: digits });
}

function clockTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatClock(ms) {
  if (ms == null) return "—";
  if (ms < 60000) return `${Math.floor(ms / 1000)} s`;
  if (ms < 3600000) return formatDuration(Math.floor(ms / 1000) * 1000);
  const hours = Math.floor(ms / 3600000);
  const minutes = String(Math.floor((ms % 3600000) / 60000)).padStart(2, "0");
  return `${hours} h ${minutes} min`;
}

function setFacts(dl, pairs) {
  dl.replaceChildren(
    ...pairs.filter(([, value]) => value != null && value !== "").flatMap(([term, value]) => [h("dt", {}, term), h("dd", {}, value)]),
  );
}

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

const currentRunEvents = () => (state.runId ? state.timeline.filter((e) => e.run_id === state.runId) : []);

// ------------------------------------------------------------ faixa de estado

function setConn(live) {
  const pill = $("conn");
  pill.className = `pill ${live ? "ok" : "warn"}`;
  setText(pill, live ? "ao vivo" : "reconectando…");
}

function renderPhaseDot() {
  $("tab-monitor-dot").dataset.phase = state.phase;
}

function renderBand(phases) {
  $("phase-band").dataset.phase = state.phase;
  setText($("phase-label"), label(state.phase));
  const running = state.phase !== "idle" && state.phase !== "error";
  const trail = phases.slice(-8);
  $("phase-trail").replaceChildren(
    ...trail.map((p, i) => {
      const last = i === trail.length - 1;
      return h(
        "li",
        { dataset: { phase: p.phase }, "aria-current": last && running ? "step" : null },
        label(p.phase),
        p.ms != null ? h("span", { class: "ms" }, formatDuration(p.ms)) : null,
      );
    }),
  );
  tick();
}

function tick() {
  setText($("phase-timer"), formatClock(elapsedMs(state.since, Date.now())));
}

// ------------------------------------------------------------ raciocínio

function renderReasoning(phases) {
  const r = state.reasoning;
  const has = hasReasoning(r);
  const panel = $("reasoning");
  panel.dataset.active = String(Boolean(r.active));
  panel.dataset.has = String(has);

  setText($("reasoning-headline"), has ? r.headline || "" : "");
  const llm = state.lastLlm || {};
  setFacts($("reasoning-facts"), has
    ? [
      ["Estado", r.active ? "pensando…" : "concluído"],
      ["Caracteres", num(r.chars)],
      ["Tokens estimados", num(r.tokens)],
      ["Tokens/s", llm.tokensPerSecond != null ? num(llm.tokensPerSecond, 1) : null],
    ]
    : []);

  const tail = $("reasoning-tail");
  tail.hidden = !has;
  const text = r.active ? r.tail : r.tail || (r.final || "").slice(-600);
  if (tail.textContent !== text) {
    tail.textContent = text;
    tail.scrollTop = tail.scrollHeight;
  }

  $("reasoning-empty").hidden = has;
  if (!has) {
    $("reasoning-phases").replaceChildren(
      ...phases.map((p) => h("li", { dataset: { phase: p.phase } }, label(p.phase), p.ms != null ? h("span", { class: "ms" }, formatDuration(p.ms)) : null)),
    );
  }

  const full = $("reasoning-full");
  full.hidden = !r.final;
  setText($("reasoning-full-text"), r.final || "");
}

// ------------------------------------------------------------ resumo do turno

const STATUS_LABEL = { running: "Em andamento", done: "Concluído", error: "Erro" };

function renderSummary(events) {
  const s = runSummary(events);
  const empty = s.status === "empty";
  $("summary-empty").hidden = !empty;
  if (empty) {
    setFacts($("summary-basic"), []);
    setFacts($("summary-tech"), []);
    $("summary-tools").replaceChildren();
    return;
  }
  setFacts($("summary-basic"), [
    ["Estado", STATUS_LABEL[s.status]],
    ["Canal", s.channel],
    ["Área", s.workspace],
    ["Comando", s.command],
    ["Duração", s.status === "running" ? "em andamento" : formatDuration(s.durationMs)],
    ["Passos", s.steps != null ? num(s.steps) : null],
    ["Ferramentas usadas", num(s.toolCalls.length)],
    ["Resposta", s.replyChars != null ? `${num(s.replyChars)} caracteres` : null],
    ["Erros", s.errors ? num(s.errors) : null],
    ["Motivo do erro", s.error ? clip(s.error, 300) : null],
  ]);
  const backend = s.requestedBackend && s.requestedBackend !== s.backend ? `${s.backend} (pedido: ${s.requestedBackend})` : s.backend;
  setFacts($("summary-tech"), [
    ["Execução", state.runId],
    ["Modelo", s.model],
    ["Backend", backend],
    ["Chamadas ao modelo", num(s.llmCalls)],
    ["Mensagens no prompt", s.messages != null ? num(s.messages) : null],
    ["Histórico", s.history != null ? num(s.history) : null],
    ["Ferramentas disponíveis", s.tools != null ? num(s.tools) : null],
    ["Prompt do sistema", s.systemChars != null ? `${num(s.systemChars)} caracteres` : null],
    ["Tokens estimados do prompt", s.estTokens != null ? num(s.estTokens) : null],
    ["Tokens do prompt", s.promptTokens != null ? num(s.promptTokens) : null],
    ["Tokens gerados", s.completionTokens != null ? num(s.completionTokens) : null],
    ["Tokens/s", s.tokensPerSecond != null ? num(s.tokensPerSecond, 1) : null],
    ["Entrada", s.inputChars != null ? `${num(s.inputChars)} caracteres` : null],
  ]);
  $("summary-tools").replaceChildren(
    ...s.toolCalls.map((t) =>
      h(
        "li",
        { class: t.ok ? "ok" : "bad" },
        h("span", { class: "mono" }, `${t.ok ? "✓" : "✗"} ${t.name}`),
        t.durationMs != null ? h("span", { class: "ms" }, formatDuration(t.durationMs)) : null,
        t.summary ? h("span", { class: "hint" }, clip(t.summary)) : null,
      ),
    ),
  );
}

// ------------------------------------------------------------ linha do tempo

function knownKinds() {
  const kinds = new Set(Object.keys(catalog.kinds || {}));
  for (const e of state.timeline) kinds.add(e.kind);
  return [...kinds].sort();
}

function renderFilters() {
  const kinds = knownKinds();
  const key = kinds.join(",");
  if (key === filtersKey) return;
  filtersKey = key;
  $("kind-filters").replaceChildren(
    h("legend", { class: "sr-only" }, "Filtrar por tipo de evento"),
    ...kinds.map((kind) =>
      h(
        "label",
        { class: "chip", title: (catalog.kinds[kind] || {}).description || null },
        h("input", {
          type: "checkbox",
          checked: !hiddenKinds.has(kind),
          onchange: (event) => {
            if (event.target.checked) hiddenKinds.delete(kind);
            else hiddenKinds.add(kind);
            filterVersion += 1;
            scheduleRender();
          },
        }),
        kind,
      ),
    ),
  );
}

function eventHint(e) {
  const d = e.detail || {};
  switch (`${e.kind}/${e.status}`) {
    case "turn/start": return [d.channel && `canal ${d.channel}`, d.workspace, d.chars != null && `${d.chars} caracteres`].filter(Boolean).join(" · ");
    case "route/resolved": return [d.workspace, d.command, d.switched && "trocou de área"].filter(Boolean).join(" · ");
    case "prompt/built": return `${num(d.messages)} mensagens · ~${num(d.est_tokens)} tokens`;
    case "llm/start": return [d.step != null && `passo ${d.step}`, d.model, d.backend].filter(Boolean).join(" · ");
    case "llm/done": return [d.completion_tokens != null && `${num(d.completion_tokens)} tokens`, d.tokens_per_second != null && `${num(d.tokens_per_second, 1)} tok/s`, d.tool_calls && `${d.tool_calls} chamadas`].filter(Boolean).join(" · ");
    case "reasoning/progress": return `${num(d.chars)} caracteres`;
    case "reasoning/final": return d.headline || "";
    case "tool/ok":
    case "tool/error": return d.summary || "";
    case "turn/done": return [d.steps != null && `${d.steps} passos`, d.reply_chars != null && `${num(d.reply_chars)} caracteres`].filter(Boolean).join(" · ");
    default: return d.detail || "";
  }
}

function eventItem(e) {
  const details = h(
    "details",
    {
      class: "event",
      dataset: { status: e.status, eventId: String(e.id) },
      open: openEvents.has(e.id),
      ontoggle: (event) => {
        const el = event.currentTarget;
        if (el.open) {
          openEvents.add(e.id);
          if (!el.querySelector("pre")) el.append(detailBlock(e));
        } else {
          openEvents.delete(e.id);
        }
      },
    },
    h(
      "summary",
      {},
      h("time", { datetime: e.at }, clockTime(e.at)),
      h("span", { class: "what mono" }, `${e.kind}/${e.name}`),
      h("span", { class: "status" }, e.status),
      e.duration_ms != null ? h("span", { class: "ms" }, formatDuration(e.duration_ms)) : null,
      h("span", { class: "hint" }, clip(eventHint(e))),
    ),
  );
  if (details.open) details.append(detailBlock(e));
  return h("li", {}, details);
}

function detailBlock(e) {
  let json;
  try {
    json = JSON.stringify(e.detail ?? {}, null, 2);
  } catch {
    json = String(e.detail);
  }
  return h("pre", { class: "json" }, json);
}

function renderTimeline() {
  const kinds = hiddenKinds.size ? new Set(knownKinds().filter((k) => !hiddenKinds.has(k))) : null;
  const events = filterTimeline(state.timeline, { kinds, onlyErrors });
  const groups = groupByRun(events).slice(0, GROUPS_SHOWN);
  const container = $("timeline-groups");
  const focused = document.activeElement && container.contains(document.activeElement)
    ? document.activeElement.closest("[data-event-id], [data-run-key]")
    : null;
  const focusKey = focused ? focused.dataset.eventId || `run:${focused.dataset.runKey}` : null;

  if (!groups.length) {
    container.replaceChildren(h("p", { class: "hint" }, state.timeline.length ? "Nada com esses filtros." : "Nenhum evento ainda."));
    return;
  }
  container.replaceChildren(
    ...groups.map((g, index) => {
      const key = g.runId ?? "";
      const open = runChoice.has(key) ? runChoice.get(key) : index === 0;
      // A lista de eventos só é montada quando o grupo está aberto (menos DOM a cada evento).
      const fill = (el) => {
        if (el.querySelector("ol.events")) return;
        const shown = g.events.slice(-EVENTS_PER_GROUP);
        if (g.events.length > shown.length) el.append(h("p", { class: "hint" }, `Mostrando os últimos ${shown.length} de ${g.events.length}.`));
        el.append(h("ol", { class: "events" }, shown.map(eventItem)));
      };
      const group = h(
        "details",
        {
          class: "run-group",
          dataset: { runKey: key, errors: String(g.errors > 0) },
          open,
          ontoggle: (event) => {
            const el = event.currentTarget;
            if (el.open !== open) runChoice.set(key, el.open);
            if (el.open) fill(el);
          },
        },
        h(
          "summary",
          {},
          h("span", { class: "mono" }, g.runId ? `execução ${short(g.runId)}` : "sem execução"),
          h("time", { datetime: g.startedAt }, clockTime(g.startedAt)),
          h("span", { class: "hint" }, `${g.events.length} eventos`),
          g.errors ? h("span", { class: "errors" }, `${g.errors} ${g.errors === 1 ? "erro" : "erros"}`) : null,
          g.durationMs ? h("span", { class: "ms" }, formatDuration(g.durationMs)) : null,
        ),
      );
      if (open) fill(group);
      return group;
    }),
  );

  if (focusKey) {
    const target = focusKey.startsWith("run:")
      ? container.querySelector(`[data-run-key="${CSS.escape(focusKey.slice(4))}"] > summary`)
      : container.querySelector(`[data-event-id="${CSS.escape(focusKey)}"] > summary`);
    if (target) target.focus({ preventScroll: true });
  }
}

// ------------------------------------------------------------ execuções

async function refreshRuns() {
  const list = $("runs-list");
  let runs;
  try {
    const response = await fetch("/api/runs?limit=20");
    if (!response.ok) throw new Error(String(response.status));
    runs = await response.json();
  } catch {
    list.replaceChildren(h("li", { class: "hint" }, "Não foi possível carregar as execuções."));
    return;
  }
  if (!runs.length) {
    list.replaceChildren(h("li", { class: "hint" }, "Nenhuma execução registrada."));
    return;
  }
  list.replaceChildren(
    ...runs.map((run) =>
      h(
        "li",
        { class: "row" },
        h(
          "div",
          {},
          h("div", {}, h("span", { class: "mono" }, short(run.run_id)), " ", h("span", { class: "hint" }, clockTime(run.started_at))),
          h(
            "div",
            { class: "hint" },
            [`${num(run.events)} eventos`, run.errors ? `${num(run.errors)} ${run.errors === 1 ? "erro" : "erros"}` : null, run.duration_ms != null ? formatDuration(run.duration_ms) : null]
              .filter(Boolean)
              .join(" · "),
          ),
        ),
        h("a", { class: "button", href: `/api/runs/${encodeURIComponent(run.run_id)}/report.md`, download: "" }, "Baixar relatório"),
      ),
    ),
  );
}

function scheduleRunsRefresh() {
  clearTimeout(runsTimer);
  runsTimer = setTimeout(refreshRuns, 400);
}

// ------------------------------------------------------------ ciclo

function render() {
  renderQueued = false;
  renderPhaseDot();
  if (!visible()) return;
  const events = currentRunEvents();
  const phases = runPhases(events, catalog);
  renderBand(phases);
  renderReasoning(phases);
  renderSummary(events);
  renderFilters();
  const key = `${state.lastId}:${filterVersion}`;
  if (key !== timelineKey) {
    timelineKey = key;
    renderTimeline();
  }
}

function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(render);
}

function onAudit(message) {
  let event;
  try {
    event = JSON.parse(message.data);
  } catch {
    return;
  }
  const next = applyEvent(state, event, catalog);
  if (next === state) return;
  state = next;
  if (event.kind === "turn" && (event.status === "done" || event.status === "error")) scheduleRunsRefresh();
  scheduleRender();
}

function connect(after) {
  if (source) source.close();
  // Sem `after`, o servidor reenvia os últimos eventos; nas reconexões automáticas
  // o navegador manda Last-Event-ID sozinho. Se a conexão fechar de vez, reabrimos com after.
  source = new EventSource(after ? `/api/events/stream?after=${after}` : "/api/events/stream");
  source.addEventListener("open", () => setConn(true));
  source.addEventListener("audit", onAudit);
  source.addEventListener("error", () => {
    setConn(false);
    if (source.readyState === EventSource.CLOSED) setTimeout(() => connect(state.lastId), 3000);
  });
}

async function loadCatalog() {
  for (;;) {
    try {
      const response = await fetch("/api/events/catalog");
      if (!response.ok) throw new Error(String(response.status));
      return await response.json();
    } catch {
      setConn(false);
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
  }
}

async function main() {
  $("only-errors").addEventListener("change", (event) => {
    onlyErrors = event.target.checked;
    filterVersion += 1;
    scheduleRender();
  });
  window.addEventListener("nickel:tab", (event) => {
    if (event.detail === "monitor") {
      timelineKey = "";
      scheduleRender();
    }
  });
  setInterval(() => visible() && tick(), 1000);
  scheduleRender();
  catalog = await loadCatalog();
  filtersKey = "";
  connect(null);
  refreshRuns();
  scheduleRender();
}

main();
