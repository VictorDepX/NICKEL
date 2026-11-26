import { renderMarkdown, escapeHtml } from "/static/markdown.js";

const $ = (id) => document.getElementById(id);
const CHANNELS = { whatsapp: "whatsapp", voice: "voz", ui: "ui", lembrete: "lembrete" };
let lastMessageId = null;

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* armazenamento indisponível */ }
}

// "Pensar antes de responder" tem três estados: true/false depois que o usuário mexe na caixa;
// null enquanto ele não mexe, e aí o servidor decide (workspace ativo ou LLM_THINK).
const THINK_KEY = "nickel.think";

function thinkChoice() {
  const stored = storageGet(THINK_KEY);
  return stored === "1" ? true : stored === "0" ? false : null;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

function linkify(text) {
  return escapeHtml(text).replace(/https?:\/\/[^\s<]+/g, (url) => `<a href="${url}" target="_blank" rel="noopener">${url}</a>`);
}

function formatTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  const sameDay = date.toDateString() === new Date().toDateString();
  return date.toLocaleString("pt-BR", sameDay ? { hour: "2-digit", minute: "2-digit" } : { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function li(html, className = "") {
  const item = document.createElement("li");
  if (className) item.className = className;
  item.innerHTML = html;
  return item;
}

// ------------------------------------------------------------ fala
// "Parar" aparece entre `tts/start` e `tts/done`/`tts/error`: o monitor.js recebe os eventos ao vivo (SSE)
// e avisa com "nickel:speech". Ao clicar em "Ouvir", o botão aparece na hora, sem esperar o `tts/start`.
const VOICE_OFF_TITLE = "Voz desligada: configure TTS_PROVIDER (edge, VoiceStudio ou Piper) para ouvir as respostas.";
let voiceOn = true; // até /api/state dizer o contrário

function showStop(visible) {
  $("stop-speech").hidden = !visible;
}

// Sem provedor de voz, "Ouvir" e "Falar respostas" ficam desativados, com o motivo no título.
function setVoiceOn(on) {
  voiceOn = on;
  const toggle = $("speak");
  toggle.disabled = !on;
  toggle.parentElement.title = on ? toggle.parentElement.dataset.title : VOICE_OFF_TITLE;
  document.querySelectorAll("button.listen").forEach((button) => syncListen(button));
  if (!on) showStop(false);
}

function syncListen(button) {
  button.disabled = !voiceOn;
  button.title = voiceOn ? "Ouça esta resposta em voz alta" : VOICE_OFF_TITLE;
}

async function speakText(text) {
  showStop(true);
  try {
    await api("/api/tts/speak", { method: "POST", body: JSON.stringify({ text }) });
  } catch (error) {
    showStop(false);
    alert(`Falha ao falar: ${error.message}`);
  }
}

function listenButton(text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "listen";
  button.textContent = "Ouvir";
  syncListen(button);
  button.addEventListener("click", () => speakText(text));
  return button;
}

function renderMessages(messages) {
  const list = $("messages");
  const newest = messages.length ? messages[messages.length - 1].id : null;
  if (newest === lastMessageId) return;
  const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  list.replaceChildren();
  if (!messages.length) {
    list.append(li("Nada por aqui ainda. Fale pelo WhatsApp, pela voz ou escreva abaixo.", "empty"));
  }
  for (const message of messages) {
    const role = message.channel === "lembrete" ? "system" : message.role;
    const tools = (message.attachments || []).filter((a) => a.type === "tools").flatMap((a) => a.items || []);
    const media = (message.attachments || []).filter((a) => a.type === "image" || a.type === "audio").map((a) => (a.type === "image" ? "[imagem]" : "[áudio]"));
    const toolLine = tools.length
      ? `<div class="tools">${tools.map((t) => `${t.ok ? "✓" : "✗"} ${escapeHtml(t.name)}`).join(" · ")}</div>`
      : "";
    const item = li(
      `<div class="bubble${role === "assistant" ? " md" : ""}">${media.length ? escapeHtml(media.join(" ")) + " " : ""}${role === "assistant" ? renderMarkdown(message.content) : linkify(message.content)}</div>
       ${toolLine}
       <div class="meta"><span class="tag">${escapeHtml(CHANNELS[message.channel] || message.channel)}</span><span>${formatTime(message.created_at)}</span></div>`,
      `msg ${role}`,
    );
    if (role === "assistant" && message.content.trim()) item.querySelector(".meta").append(listenButton(message.content));
    list.append(item);
  }
  lastMessageId = newest;
  if (nearBottom || !lastMessageId) list.scrollTop = list.scrollHeight;
}

function renderPending(items) {
  const list = $("pending");
  list.replaceChildren();
  if (!items.length) return list.append(li('<span class="hint">Nenhuma ação aguardando.</span>'));
  for (const action of items) {
    const item = li(
      `<span>${escapeHtml(action.summary)}</span>
       <span class="hint">${escapeHtml(action.tool)} · ${escapeHtml(CHANNELS[action.channel] || action.channel)} · ${formatTime(action.created_at)}</span>
       <div class="actions"><button class="primary" data-act="confirm">Confirmar</button><button class="danger" data-act="cancel">Cancelar</button></div>`,
    );
    item.querySelectorAll("button").forEach((button) =>
      button.addEventListener("click", async () => {
        button.disabled = true;
        await api(`/api/pending/${action.id}/${button.dataset.act}`, { method: "POST" }).catch(alert);
        refresh();
      }),
    );
    list.append(item);
  }
}

function renderReminders(items) {
  const list = $("reminders");
  list.replaceChildren();
  if (!items.length) return list.append(li('<span class="hint">Nenhum lembrete agendado.</span>'));
  const repeatLabel = { daily: "todo dia", weekly: "toda semana", monthly: "todo mês" };
  for (const reminder of items) {
    const extra = [repeatLabel[reminder.repeat], reminder.calendar_event_id ? "na Agenda" : null].filter(Boolean).join(" · ");
    const item = li(
      `<div><div>#${reminder.id} ${escapeHtml(reminder.text)}</div><div class="hint">${escapeHtml(reminder.due_local)}${extra ? " · " + extra : ""}</div></div>
       <button class="danger" aria-label="Cancelar lembrete ${reminder.id}">✕</button>`,
      "row",
    );
    item.querySelector("button").addEventListener("click", async () => {
      await api(`/api/reminders/${reminder.id}`, { method: "DELETE" }).catch(alert);
      refresh();
    });
    list.append(item);
  }
}

function renderMemory(items) {
  const list = $("memory");
  list.replaceChildren();
  if (!items.length) return list.append(li('<span class="hint">Vazia. O NICKEL só guarda com sua confirmação.</span>'));
  for (const entry of items) {
    const item = li(`<span><b>${escapeHtml(entry.key)}</b>: ${escapeHtml(entry.value)}</span><button class="danger" aria-label="Esquecer ${escapeHtml(entry.key)}">✕</button>`, "row");
    item.querySelector("button").addEventListener("click", async () => {
      await api(`/api/memory/${encodeURIComponent(entry.key)}`, { method: "DELETE" }).catch(alert);
      refresh();
    });
    list.append(item);
  }
}

function pill(label, level, title) {
  const item = document.createElement("li");
  item.className = `pill ${level}`;
  item.textContent = label;
  if (title) item.title = title;
  return item;
}

const LEVEL_TEXT = { ok: "funcionando", warn: "falta um passo", bad: "fora do ar" };

// Uma linha por conector/pipeline configurado: ponto colorido + nome + detalhe (+ ação, se houver).
function connectorRow(item) {
  const row = li("", `row conn ${item.level}`);
  const body = document.createElement("div");
  const name = document.createElement("div");
  name.className = "conn-name";
  const dot = document.createElement("span");
  dot.className = `conn-dot ${item.level}`;
  dot.setAttribute("aria-hidden", "true");
  name.append(dot, item.name);
  const detail = document.createElement("div");
  detail.className = "hint";
  detail.textContent = [LEVEL_TEXT[item.level], item.detail].filter(Boolean).join(" · ");
  body.append(name, detail);
  row.append(body);
  if (item.action) {
    const link = document.createElement("a");
    link.href = item.action;
    link.innerHTML = '<button class="primary">Conectar</button>';
    row.append(link);
  }
  return row;
}

function renderState(state) {
  setVoiceOn(Boolean(state.voice && state.voice.tts && state.voice.tts.provider));
  if (thinkChoice() === null && typeof state.think_default === "boolean") $("think").checked = state.think_default;
  const connectors = state.connectors || [];
  const pipelines = state.pipelines || [];
  // Topo: só o que está configurado, com a mesma cor do painel.
  $("status").replaceChildren(
    ...connectors.map((item) => pill(item.name, item.level, [LEVEL_TEXT[item.level], item.detail].filter(Boolean).join(" · "))),
  );
  $("connections").replaceChildren(...connectors.map(connectorRow));
  $("tools-line").textContent = state.tools && state.tools.length ? `Ferramentas ativas (${state.tools.length}): ${state.tools.join(", ")}` : "";
  $("pipelines-panel").hidden = !pipelines.length;
  $("pipelines").replaceChildren(...pipelines.map(connectorRow));
}

function renderAudit(items) {
  const list = $("audit");
  list.replaceChildren(
    ...items.slice(0, 25).map((entry) => li(`${formatTime(entry.at)} ${escapeHtml(entry.kind)}/${escapeHtml(entry.name)} → ${escapeHtml(entry.status)}`)),
  );
}

async function refresh() {
  try {
    const [messages, pending, reminders, memory] = await Promise.all([
      api("/api/messages?limit=120"),
      api("/api/pending"),
      api("/api/reminders"),
      api("/api/memory"),
    ]);
    renderMessages(messages);
    renderPending(pending);
    renderReminders(reminders);
    renderMemory(memory);
    if ($("audit-panel").open) renderAudit(await api("/api/audit?limit=40"));
  } catch (error) {
    console.error(error);
  }
}

async function refreshState() {
  try {
    renderState(await api("/api/state"));
  } catch (error) {
    $("status").replaceChildren(pill("API offline", "bad"));
  }
}

$("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("input");
  const text = input.value.trim();
  if (!text) return;
  const button = $("send");
  button.disabled = true;
  input.value = "";
  try {
    // Só manda a escolha se o usuário mexeu na caixa; senão `null` e vale o padrão do servidor.
    await api("/api/chat", { method: "POST", body: JSON.stringify({ text, think: thinkChoice() }) });
  } catch (error) {
    alert(`Falha ao enviar: ${error.message}`);
    input.value = text;
  } finally {
    button.disabled = false;
    refresh();
  }
});

$("input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("composer").requestSubmit();
  }
});

$("audit-panel").addEventListener("toggle", refresh);

// "Falar respostas" fica no servidor (`ui.speak`): o /api/chat usa a preferência guardada.
api("/api/preferences").then((prefs) => { $("speak").checked = prefs.speak === true; }).catch(() => {});
$("speak").addEventListener("change", async (event) => {
  const speak = event.target.checked;
  try {
    await api("/api/preferences", { method: "POST", body: JSON.stringify({ speak }) });
  } catch (error) {
    event.target.checked = !speak;
    alert(`Falha ao salvar a preferência: ${error.message}`);
  }
});
$("stop-speech").addEventListener("click", () => {
  showStop(false);
  api("/api/tts/stop", { method: "POST" }).catch((error) => alert(`Falha ao parar: ${error.message}`));
});
window.addEventListener("nickel:speech", (event) => showStop(event.detail === "start"));
$("speak").parentElement.dataset.title = $("speak").parentElement.title;

$("think").checked = thinkChoice() === true; // até /api/state trazer think_default
$("think").addEventListener("change", (event) => storageSet(THINK_KEY, event.target.checked ? "1" : "0"));

// Abas "Conversa" e "Monitor": a escolha fica guardada; o monitor escuta "nickel:tab".
function showTab(name, focus = false) {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  if (!tabs.some((tab) => tab.dataset.tab === name)) name = "conversa";
  for (const tab of tabs) {
    const active = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    $(tab.dataset.tab).hidden = !active;
    if (active && focus) tab.focus();
  }
  storageSet("nickel.tab", name);
  window.dispatchEvent(new CustomEvent("nickel:tab", { detail: name }));
}

document.querySelectorAll('[role="tab"]').forEach((tab, index, all) => {
  tab.addEventListener("click", () => showTab(tab.dataset.tab));
  tab.addEventListener("keydown", (event) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    showTab(all[(index + step + all.length) % all.length].dataset.tab, true);
  });
});

showTab(storageGet("nickel.tab") || "conversa");

refresh();
refreshState();
setInterval(refresh, 3000);
setInterval(refreshState, 15000);
