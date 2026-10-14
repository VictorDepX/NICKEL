// Bridge WhatsApp ⇄ NICKEL usando open-wa v5.
//
// Entrada:  mensagens do chat "você mesmo" (WA_MODE=self) ou do dono (WA_MODE=dedicated)
//           → POST {NICKEL_URL}/channels/whatsapp/inbound
// Saída:    POST /send {text} e POST /send-voice {audio_b64} em 127.0.0.1:{BRIDGE_PORT}
import http from "node:http";
import qrcode from "qrcode-terminal";
import { createClient } from "@open-wa/core";
import { Client } from "@open-wa/client";
import { MARKER, MEDIA_TYPES, digits, messageId, parseDataUrl, shouldForward, toInboundPayload } from "./filter.mjs";

const cfg = {
  nickelUrl: (process.env.NICKEL_URL ?? "http://127.0.0.1:8000").replace(/\/$/, ""),
  token: process.env.BRIDGE_TOKEN,
  port: Number(process.env.BRIDGE_PORT ?? 8002),
  mode: process.env.WA_MODE ?? "self",
  ownerDigits: digits(process.env.WA_OWNER ?? ""),
  sessionDir: process.env.WA_SESSION_DIR ?? "./session",
  chromePath: process.env.CHROME_PATH || undefined,
  headless: process.env.WA_HEADLESS !== "false",
};

if (!cfg.token) {
  console.error("BRIDGE_TOKEN ausente. Use o mesmo valor do .env do NICKEL.");
  process.exit(1);
}
if (!["self", "dedicated"].includes(cfg.mode)) {
  console.error(`WA_MODE inválido: ${cfg.mode} (use self ou dedicated).`);
  process.exit(1);
}
if (cfg.mode === "dedicated" && !cfg.ownerDigits) {
  console.error("WA_MODE=dedicated exige WA_OWNER (seu número com DDI e DDD, só dígitos).");
  process.exit(1);
}

const state = { client: null, ready: false, hostDigits: "", ownIds: new Set(), replyChat: null };
const sentIds = new Set();

function rememberSent(result) {
  const id = String(result?._serialized ?? result ?? "");
  if (!id || id === "true" || id === "false") return;
  sentIds.add(id);
  if (sentIds.size > 1000) sentIds.delete(sentIds.values().next().value);
}

function defaultChat() {
  if (state.replyChat) return state.replyChat;
  return cfg.mode === "self" ? `${state.hostDigits}@c.us` : `${cfg.ownerDigits}@c.us`;
}

function collectOwnIds(host) {
  const ids = new Set();
  const visit = (value) => {
    if (typeof value === "string" && /@(c\.us|lid)$/.test(value)) ids.add(value);
    else if (value && typeof value === "object") Object.values(value).forEach((v) => typeof v !== "object" && visit(v));
  };
  visit(host?.me?._serialized ?? host?.me);
  visit(host);
  return ids;
}

async function forward(message) {
  try {
    const options = { mode: cfg.mode, ownerDigits: cfg.ownerDigits, hostDigits: state.hostDigits, ownIds: state.ownIds, sentIds };
    if (!shouldForward(message, options)) return;
    state.replyChat = cfg.mode === "self" ? String(message.to) : String(message.from);
    let media = null;
    if (MEDIA_TYPES.has(message.type)) {
      media = parseDataUrl(await state.client.decryptMedia(message));
      if (!media) console.warn(`Mídia ${messageId(message)} não pôde ser decodificada.`);
    }
    const response = await fetch(`${cfg.nickelUrl}/channels/whatsapp/inbound`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-nickel-token": cfg.token },
      body: JSON.stringify(toInboundPayload(message, media)),
    });
    if (!response.ok) console.error(`NICKEL recusou a mensagem: HTTP ${response.status}`);
  } catch (error) {
    console.error("Falha ao encaminhar mensagem ao NICKEL:", error?.message ?? error);
  }
}

async function startWhatsApp() {
  const { PuppeteerDriver, ensureBrowser } = await import("@open-wa/driver-puppeteer");
  let executablePath = cfg.chromePath;
  if (!executablePath) {
    try {
      executablePath = await ensureBrowser({});
    } catch (error) {
      console.warn("Não achei/baixei um Chrome automaticamente; defina CHROME_PATH.", error?.message ?? error);
    }
  }
  const core = await createClient({
    sessionId: "nickel",
    driver: new PuppeteerDriver(),
    headless: cfg.headless,
    executablePath,
    sessionDataPath: cfg.sessionDir,
  });
  core.events.on("launch.auth.qr.generated", (event) => {
    if (!event?.details?.qr) return;
    console.log("\nNo celular: WhatsApp → Aparelhos conectados → Conectar um aparelho. Escaneie:");
    qrcode.generate(event.details.qr, { small: true });
  });
  core.events.on("launch.auth.linkCode.generated", (event) => {
    if (event?.details?.linkCode) console.log(`Código de pareamento: ${event.details.linkCode}`);
  });

  const client = new Client({ client: core, transport: core.getTransport() });
  await client.start();
  state.client = client;
  state.hostDigits = digits(await client.getHostNumber());
  try {
    state.ownIds = collectOwnIds(await client.getMe());
  } catch {
    state.ownIds = new Set();
  }
  state.ownIds.add(`${state.hostDigits}@c.us`);
  client.onAnyMessage(forward);
  state.ready = true;
  console.log(`WhatsApp conectado (${state.hostDigits}). Modo: ${cfg.mode}.`);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 25 * 1024 * 1024) reject(new Error("payload grande demais"));
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  const reply = (code, body) => {
    res.writeHead(code, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  };
  try {
    if (req.method === "GET" && req.url === "/health") {
      return reply(200, { ready: state.ready, host: state.hostDigits, mode: cfg.mode });
    }
    if (req.headers["x-nickel-token"] !== cfg.token) return reply(401, { error: "token inválido" });
    if (!state.ready) return reply(503, { error: "WhatsApp ainda não conectado" });
    const body = await readJson(req);
    const to = body.to ?? defaultChat();

    if (req.method === "POST" && req.url === "/send") {
      if (!body.text) return reply(400, { error: "text vazio" });
      const id = await state.client.sendText(to, MARKER + String(body.text));
      rememberSent(id);
      return reply(200, { id: String(id?._serialized ?? id) });
    }
    if (req.method === "POST" && req.url === "/send-voice") {
      if (!body.audio_b64) return reply(400, { error: "audio_b64 vazio" });
      const mime = body.mime ?? "audio/ogg; codecs=opus";
      const result = await state.client.sendPtt(to, `data:${mime};base64,${body.audio_b64}`);
      rememberSent(result);
      return reply(200, { ok: Boolean(result) });
    }
    return reply(404, { error: "rota desconhecida" });
  } catch (error) {
    console.error("Erro na bridge:", error?.message ?? error);
    return reply(500, { error: String(error?.message ?? error) });
  }
});

server.listen(cfg.port, "127.0.0.1", () => console.log(`Bridge ouvindo em 127.0.0.1:${cfg.port}`));
startWhatsApp().catch((error) => {
  console.error("Falha ao iniciar o WhatsApp:", error?.message ?? error);
  process.exit(1);
});
