// Aba Monitor: liga o SSE de auditoria ao reducer puro e desenha o estado.
// Regra de segurança: textos de eventos vêm do LLM e das ferramentas, então
// tudo entra no DOM por textContent/append (nunca como HTML).
import {
  initialState,
  applyEvent,
  groupByRun,
  formatDuration,
  filterTimeline,
  runSummary,
  runPhases,
  elapsedMs,
  reasoningSteps,
  reasoningView,
  eventHint,
  num,
  speechSignal,
  fakeActionLabel,
  timelineKey as computeTimelineKey,
  chatStatus,
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

// ------------------------------------------------------------ status no chat

let chatActive = false;

function renderChatStatus() {
  const box = $("chat-status");
  if (!box) return;
  const st = chatStatus(state, Date.now());
  chatActive = st.active;
  box.dataset.phase = st.phase;
  box.dataset.active = String(st.active);
  setText($("chat-status-text"), st.active ? `${st.text}…` : st.text);
  setText($("chat-status-detail"), st.detail ? `· ${st.detail}` : "");
  setText($("chat-status-time"), st.active && st.elapsedMs != null ? formatClock(st.elapsedMs) : "");
}

// ------------------------------------------------------------ memória do sistema

const GIB = 1024 ** 3;
const MEM_SERIES = [
  { key: "used", label: "RAM usada (total)", cls: "s1", area: true },
  { key: "llama", label: "llama-server (modelo)", cls: "s2" },
  { key: "nickel", label: "NICKEL", cls: "s3" },
];
const SVG_NS = "http://www.w3.org/2000/svg";
let memTimer = null;
let memData = null;

const gb = (bytes) => `${num(bytes / GIB, 1)} GB`;

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) if (value != null) el.setAttribute(key, String(value));
  el.append(...children);
  return el;
}

function memLevel(last) {
  const free = last.available / GIB;
  if (free < 1) return ["bad", "pouca RAM livre"];
  if (free < 2.5) return ["warn", "RAM apertada"];
  return ["ok", "RAM folgada"];
}

function drawMemChart(samples) {
  const box = $("sysmem-chart");
  const width = Math.max(260, box.clientWidth || 520);
  const height = 170;
  const pad = { l: 44, r: 10, t: 8, b: 22 };
  const total = samples[samples.length - 1].total;
  const t0 = samples[0].t;
  const t1 = Math.max(samples[samples.length - 1].t, t0 + 1);
  const x = (t) => pad.l + ((t - t0) / (t1 - t0)) * (width - pad.l - pad.r);
  const y = (v) => pad.t + (1 - v / total) * (height - pad.t - pad.b);
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img", "aria-label": "Uso de memória RAM nos últimos minutos" });
  const step = total / GIB > 24 ? 8 : 4;
  for (let g = 0; g <= total / GIB + 0.01; g += step) {
    root.append(
      svg("line", { x1: pad.l, x2: width - pad.r, y1: y(g * GIB), y2: y(g * GIB), class: "grid" }),
      svg("text", { x: pad.l - 6, y: y(g * GIB) + 4, class: "axis", "text-anchor": "end" }, `${g} GB`),
    );
  }
  root.append(svg("line", { x1: pad.l, x2: width - pad.r, y1: y(total), y2: y(total), class: "limit" }));
  const minutes = Math.round((t1 - t0) / 60);
  root.append(
    svg("text", { x: pad.l, y: height - 6, class: "axis" }, minutes >= 1 ? `há ${minutes} min` : "agora"),
    svg("text", { x: width - pad.r, y: height - 6, class: "axis", "text-anchor": "end" }, "agora"),
  );
  for (const serie of MEM_SERIES) {
    const pts = samples.map((p) => `${x(p.t).toFixed(1)},${y(p[serie.key] || 0).toFixed(1)}`);
    if (serie.area) {
      root.append(svg("path", { d: `M${x(t0)},${y(0)} L${pts.join(" L")} L${x(samples[samples.length - 1].t)},${y(0)} Z`, class: `area ${serie.cls}` }));
    }
    root.append(svg("polyline", { points: pts.join(" "), class: `line ${serie.cls}` }));
    const last = samples[samples.length - 1];
    root.append(svg("circle", { cx: x(last.t), cy: y(last[serie.key] || 0), r: 4, class: `end ${serie.cls}` }));
  }
  // Hover: linha vertical + valores do ponto mais próximo.
  const cross = svg("line", { y1: pad.t, y2: height - pad.b, class: "cross", visibility: "hidden" });
  const tip = h("div", { class: "sysmem-tip", hidden: true });
  const hit = svg("rect", { x: pad.l, y: pad.t, width: width - pad.l - pad.r, height: height - pad.t - pad.b, fill: "transparent" });
  hit.addEventListener("pointermove", (event) => {
    const rect = root.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    const t = t0 + ((px - pad.l) / (width - pad.l - pad.r)) * (t1 - t0);
    const p = samples.reduce((a, b) => (Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a));
    cross.setAttribute("x1", x(p.t));
    cross.setAttribute("x2", x(p.t));
    cross.setAttribute("visibility", "visible");
    tip.replaceChildren(
      h("b", {}, new Date(p.t * 1000).toLocaleTimeString("pt-BR")),
      ...MEM_SERIES.map((s) => h("div", {}, h("span", { class: `swatch ${s.cls}` }), `${s.label}: ${gb(p[s.key] || 0)}`)),
      h("div", {}, `Livre: ${gb(p.available)}`),
    );
    tip.hidden = false;
    tip.style.left = `${Math.min(rect.width - 190, Math.max(0, event.clientX - rect.left + 12))}px`;
  });
  hit.addEventListener("pointerleave", () => {
    cross.setAttribute("visibility", "hidden");
    tip.hidden = true;
  });
  root.append(cross, hit);
  box.replaceChildren(root, tip);
}

function renderMemory() {
  const panel = $("sysmem");
  if (!memData || !memData.available || !memData.samples.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const samples = memData.samples;
  const last = samples[samples.length - 1];
  const [level, levelText] = memLevel(last);
  const pill = $("sysmem-level");
  pill.className = `pill ${level}`;
  setText(pill, levelText);
  setFacts($("sysmem-facts"), [
    ["Usada", `${gb(last.used)} de ${gb(last.total)} (${num((last.used / last.total) * 100)}%)`],
    ["Livre", gb(last.available)],
    ["llama-server", last.llama ? gb(last.llama) : "não encontrado"],
    ["NICKEL", gb(last.nickel)],
  ]);
  $("sysmem-legend").replaceChildren(
    ...MEM_SERIES.map((s) => h("li", {}, h("span", { class: `swatch ${s.cls}`, "aria-hidden": "true" }), s.label)),
  );
  drawMemChart(samples);
  const rows = samples.slice(-12).reverse();
  $("sysmem-table").replaceChildren(
    h("thead", {}, h("tr", {}, h("th", {}, "Hora"), ...MEM_SERIES.map((s) => h("th", {}, s.label)), h("th", {}, "Livre"))),
    h("tbody", {}, ...rows.map((p) => h("tr", {},
      h("td", {}, new Date(p.t * 1000).toLocaleTimeString("pt-BR")),
      ...MEM_SERIES.map((s) => h("td", {}, gb(p[s.key] || 0))),
      h("td", {}, gb(p.available)),
    ))),
  );
}

async function refreshMemory() {
  clearTimeout(memTimer);
  try {
    const response = await fetch("/api/system/memory");
    if (response.ok) memData = await response.json();
  } catch {
    /* mantém a última leitura */
  }
  if (visible()) renderMemory();
  memTimer = setTimeout(refreshMemory, visible() ? 5000 : 30000);
}

// ------------------------------------------------------------ raciocínio

const REASONING_EMPTY = {
  empty: "Nenhum turno ainda.",
  waiting: "Aguardando o modelo…",
  off: "Sem raciocínio expandido (think desligado)",
  skipped: "O modelo não raciocinou neste passo (think ligado)",
  none: "Sem raciocínio neste turno.",
};
let selectedStep = null;
let selectedRun = null;

function renderStepChips(steps, shown) {
  const box = $("reasoning-steps");
  box.hidden = steps.length < 2;
  const key = `${steps.map((s) => s.step).join(",")}|${shown}`;
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.replaceChildren(
    ...steps.map((s) =>
      h(
        "button",
        {
          type: "button",
          class: "chip",
          "aria-pressed": String(s.step === shown),
          onclick: () => {
            const latest = steps[steps.length - 1].step;
            selectedStep = s.step === latest ? null : s.step;
            scheduleRender();
          },
        },
        `passo ${s.step}`,
      ),
    ),
  );
}

function renderReasoning(phases) {
  if (state.runId !== selectedRun) {
    selectedRun = state.runId;
    selectedStep = null;
  }
  const steps = reasoningSteps(state);
  const view = reasoningView(state);
  const has = view === "reasoning";
  const picked = steps.find((s) => s.step === selectedStep);
  const r = picked || state.reasoning;
  const shown = picked ? picked.step : steps.length ? steps[steps.length - 1].step : null;
  renderStepChips(steps, shown);

  const panel = $("reasoning");
  panel.dataset.active = String(Boolean(has && r.active));
  panel.dataset.view = view;

  setText($("reasoning-headline"), has ? r.headline || "" : "");
  const llm = state.lastLlm || {};
  setFacts($("reasoning-facts"), has
    ? [
      ["Passo", steps.length > 1 ? String(shown) : null],
      ["Estado", r.active ? "pensando…" : "concluído"],
      ["Caracteres", num(r.chars)],
      ["Tokens estimados", num(r.tokens)],
      ["Tokens/s", llm.tokensPerSecond != null ? num(llm.tokensPerSecond, 1) : null],
    ]
    : []);

  const tail = $("reasoning-tail");
  tail.hidden = !has;
  const text = has ? (r.active ? r.tail : r.tail || (r.final || "").slice(-600)) : "";
  if (tail.textContent !== text) {
    // Só acompanha o fim se o usuário já estava perto dele (não puxa quem está lendo acima).
    const nearBottom = tail.scrollHeight - tail.scrollTop - tail.clientHeight < 24;
    tail.textContent = text;
    if (nearBottom) tail.scrollTop = tail.scrollHeight;
  }

  $("reasoning-empty").hidden = has;
  if (!has) {
    setText($("reasoning-empty-text"), REASONING_EMPTY[view] || "");
    $("reasoning-phases").replaceChildren(
      ...phases.map((p) => h("li", { dataset: { phase: p.phase } }, label(p.phase), p.ms != null ? h("span", { class: "ms" }, formatDuration(p.ms)) : null)),
    );
  }

  const full = $("reasoning-full");
  full.hidden = !has || !r.final;
  setText($("reasoning-full-text"), has ? r.final || "" : "");
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
    ["Aviso", fakeActionLabel(s)],
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

function eventItem(e) {
  const details = h(
    "details",
    {
      class: "event",
      dataset: { status: e.status, eventId: String(e.id) },
      open: openEvents.has(e.id),
      ontoggle: (event) => {
        const el = event.currentTarget;
        if (!el.isConnected) {
          if (el.open) openEvents.add(e.id);
          else openEvents.delete(e.id);
          return forceTimeline();
        }
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

// A linha do tempo cresce por anexação: grupos e itens já desenhados não são recriados,
// então cliques, seleção de texto e <details> abertos sobrevivem aos eventos ao vivo.
// Reconstrução completa só quando muda a estrutura (filtro ou execução nova) e nunca
// com o ponteiro pressionado ou com texto selecionado dentro da linha do tempo.
const groupRefs = new Map();
let structureKey = null;
let pointerDown = false;

function timelineFilter() {
  const kinds = hiddenKinds.size ? new Set(knownKinds().filter((k) => !hiddenKinds.has(k))) : null;
  return { kinds, onlyErrors };
}

function timelineBusy() {
  if (pointerDown) return true;
  const selection = document.getSelection();
  if (!selection || selection.isCollapsed) return false;
  const container = $("timeline-groups");
  return container.contains(selection.anchorNode) || container.contains(selection.focusNode);
}

function forceTimeline() {
  structureKey = null;
  timelineKey = "";
  scheduleRender();
}

function setGroupMeta(ref) {
  const g = ref.group;
  ref.el.dataset.errors = String(g.errors > 0);
  setText(ref.countEl, `${g.events.length} eventos`);
  setText(ref.errorsEl, g.errors ? `${g.errors} ${g.errors === 1 ? "erro" : "erros"}` : "");
  ref.errorsEl.hidden = !g.errors;
  setText(ref.durationEl, g.durationMs ? formatDuration(g.durationMs) : "");
}

function appendEvents(ref) {
  // Itens que saíram da linha do tempo (ex.: `reasoning/progress` trocado pelo mais novo) saem do DOM.
  const alive = new Set(ref.group.events.map((e) => String(e.id)));
  for (const item of [...ref.list.children]) {
    const id = item.firstElementChild && item.firstElementChild.dataset.eventId;
    if (id && !alive.has(id)) item.remove();
  }
  const fresh = ref.group.events.filter((e) => e.id > ref.lastId);
  if (fresh.length) {
    ref.list.append(...fresh.slice(-EVENTS_PER_GROUP).map(eventItem));
    ref.lastId = fresh[fresh.length - 1].id;
  }
  while (ref.list.children.length > EVENTS_PER_GROUP) ref.list.firstElementChild.remove();
  const total = ref.group.events.length;
  ref.note.hidden = total <= ref.list.children.length;
  setText(ref.note, ref.note.hidden ? "" : `Mostrando os últimos ${ref.list.children.length} de ${total}.`);
}

function fillGroup(ref) {
  if (!ref.list) {
    ref.note = h("p", { class: "hint", hidden: true });
    ref.list = h("ol", { class: "events" });
    ref.el.append(ref.note, ref.list);
  }
  appendEvents(ref);
}

function buildGroup(g, index) {
  const key = g.runId ?? "";
  const open = runChoice.has(key) ? runChoice.get(key) : index === 0;
  const ref = { group: g, list: null, note: null, lastId: 0 };
  ref.countEl = h("span", { class: "hint" });
  ref.errorsEl = h("span", { class: "errors" });
  ref.durationEl = h("span", { class: "ms" });
  ref.el = h(
    "details",
    {
      class: "run-group",
      dataset: { runKey: key },
      open,
      ontoggle: (event) => {
        const el = event.currentTarget;
        if (el.open !== open) runChoice.set(key, el.open);
        if (!el.isConnected) return forceTimeline();
        if (el.open) fillGroup(ref);
      },
    },
    h(
      "summary",
      {},
      h("span", { class: "mono" }, g.runId ? `execução ${short(g.runId)}` : "sem execução"),
      h("time", { datetime: g.startedAt }, clockTime(g.startedAt)),
      ref.countEl,
      ref.errorsEl,
      ref.durationEl,
    ),
  );
  setGroupMeta(ref);
  if (open) fillGroup(ref);
  groupRefs.set(key, ref);
  return ref.el;
}

function rebuildTimeline(groups) {
  const container = $("timeline-groups");
  const focused = document.activeElement && container.contains(document.activeElement)
    ? document.activeElement.closest("[data-event-id], [data-run-key]")
    : null;
  const focusKey = focused ? focused.dataset.eventId || `run:${focused.dataset.runKey}` : null;
  groupRefs.clear();
  if (!groups.length) {
    container.replaceChildren(h("p", { class: "hint" }, state.timeline.length ? "Nada com esses filtros." : "Nenhum evento ainda."));
    return;
  }
  container.replaceChildren(...groups.map(buildGroup));
  if (focusKey) {
    const target = focusKey.startsWith("run:")
      ? container.querySelector(`[data-run-key="${CSS.escape(focusKey.slice(4))}"] > summary`)
      : container.querySelector(`[data-event-id="${CSS.escape(focusKey)}"] > summary`);
    if (target) target.focus({ preventScroll: true });
  }
}

// Devolve false quando a reconstrução foi adiada (o chamador tenta de novo).
function renderTimeline(groups) {
  const structure = `${filterVersion}|${groups.map((g) => g.runId ?? "").join("|")}`;
  if (structure === structureKey && groups.length) {
    for (const g of groups) {
      const ref = groupRefs.get(g.runId ?? "");
      ref.group = g;
      setGroupMeta(ref);
      if (ref.list) appendEvents(ref);
    }
    return true;
  }
  if (timelineBusy()) return false;
  rebuildTimeline(groups);
  structureKey = structure;
  return true;
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
  renderChatStatus();
  if (!visible()) return;
  const events = currentRunEvents();
  const phases = runPhases(events, catalog);
  renderBand(phases);
  renderReasoning(phases);
  renderSummary(events);
  renderFilters();
  const filter = timelineFilter();
  const key = computeTimelineKey(state.timeline, filter, filterVersion);
  if (key !== timelineKey) {
    const groups = groupByRun(filterTimeline(state.timeline, filter)).slice(0, GROUPS_SHOWN);
    if (renderTimeline(groups)) timelineKey = key;
    else setTimeout(scheduleRender, 250);
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
  const speech = speechSignal(event);
  if (speech) window.dispatchEvent(new CustomEvent("nickel:speech", { detail: speech })); // app.js mostra/esconde "Parar"
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
  $("timeline-groups").addEventListener("pointerdown", () => { pointerDown = true; });
  const release = () => setTimeout(() => { pointerDown = false; }, 200);
  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);
  window.addEventListener("nickel:tab", (event) => {
    if (event.detail === "monitor") {
      timelineKey = "";
      scheduleRender();
      refreshMemory();
    }
  });
  setInterval(() => {
    if (visible()) tick();
    if (chatActive) renderChatStatus();
  }, 1000);
  refreshMemory();
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => visible() && renderMemory(), 200);
  });
  scheduleRender();
  catalog = await loadCatalog();
  filtersKey = "";
  connect(null);
  refreshRuns();
  scheduleRender();
}

main();
