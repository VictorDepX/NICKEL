"use strict";

const $ = (id) => document.getElementById(id);
const CHANNELS = { whatsapp: "whatsapp", voice: "voz", ui: "ui", lembrete: "lembrete" };
let lastMessageId = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
    list.append(
      li(
        `<div class="bubble">${media.length ? escapeHtml(media.join(" ")) + " " : ""}${linkify(message.content)}</div>
         ${toolLine}
         <div class="meta"><span class="tag">${escapeHtml(CHANNELS[message.channel] || message.channel)}</span><span>${formatTime(message.created_at)}</span></div>`,
        `msg ${role}`,
      ),
    );
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

function renderState(state) {
  const status = $("status");
  const level = (s) => (s === "ready" ? "ok" : s === "needs_connection" ? "warn" : "bad");
  status.replaceChildren(
    pill(`Modelo ${state.llm.model || ""}`.trim(), state.llm.ok && state.llm.model_present ? "ok" : "bad", state.llm.detail || ""),
    pill("WhatsApp", state.whatsapp.ready ? "ok" : "bad", state.whatsapp.detail || state.whatsapp.host || ""),
    pill("Google", level(state.google.status), state.google.message || ""),
    pill("Spotify", level(state.spotify.status), state.spotify.message || ""),
    pill("Obsidian", state.obsidian.available ? "ok" : "bad", state.obsidian.vault),
    pill(`Voz${state.voice.state && state.voice.state !== "idle" ? ": " + state.voice.state : ""}`, state.voice.available ? "ok" : "warn"),
  );

  const list = $("connections");
  list.replaceChildren();
  for (const [name, info, path] of [["Google (Gmail + Agenda)", state.google, "/auth/google/start"], ["Spotify", state.spotify, "/auth/spotify/start"]]) {
    const ready = info.status === "ready";
    const action = info.status === "needs_connection" ? `<a href="${path}"><button class="primary">Conectar</button></a>` : "";
    list.append(li(`<div><div>${name}</div><div class="hint">${ready ? "conectado" : escapeHtml(info.message || info.status)}</div></div>${action}`, "row"));
  }
  list.append(li(`<div><div>Ferramentas ativas</div><div class="hint">${state.tools.length}: ${escapeHtml(state.tools.join(", "))}</div></div>`));
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
    await api("/api/chat", { method: "POST", body: JSON.stringify({ text }) });
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

refresh();
refreshState();
setInterval(refresh, 3000);
setInterval(refreshState, 15000);
