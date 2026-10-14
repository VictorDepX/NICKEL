// Regras puras de filtragem (testadas em test/filter.test.mjs).

// Caractere invisível que marca as respostas do NICKEL. No modo "self" (número
// pessoal), as respostas caem no mesmo chat das perguntas; o marcador e a lista
// de IDs enviados impedem que o bot responda a si mesmo.
export const MARKER = "⁣";

export const MEDIA_TYPES = new Set(["image", "ptt", "audio"]);

export function digits(jid) {
  return String(jid ?? "").split("@")[0].split(":")[0].replace(/\D/g, "");
}

export function messageId(message) {
  const id = message?.id;
  return String(id?._serialized ?? id ?? "");
}

export function isOutgoing(message) {
  if (message?.fromMe === true || message?.self === "out" || message?.id?.fromMe === true) return true;
  return messageId(message).startsWith("true_");
}

function isGroupOrBroadcast(message) {
  const from = String(message?.from ?? "");
  const to = String(message?.to ?? "");
  return Boolean(
    message?.isGroupMsg ||
      message?.broadcast ||
      from.endsWith("@g.us") ||
      to.endsWith("@g.us") ||
      from.includes("broadcast") ||
      to.includes("broadcast"),
  );
}

/**
 * Decide se a mensagem vai para o NICKEL.
 * - mode "self": só mensagens que você escreveu no chat "você mesmo".
 * - mode "dedicated": só mensagens recebidas do número do dono (WA_OWNER).
 */
export function shouldForward(message, { mode, ownerDigits = "", hostDigits = "", ownIds = new Set(), sentIds = new Set() }) {
  if (!message || isGroupOrBroadcast(message)) return false;
  if (sentIds.has(messageId(message))) return false;
  const body = typeof message.body === "string" ? message.body : "";
  if (body.startsWith(MARKER)) return false;

  if (mode === "self") {
    if (!isOutgoing(message)) return false;
    const to = String(message.to ?? "");
    const from = String(message.from ?? "");
    if (to && to === from) return true;
    if (ownIds.has(to)) return true;
    return Boolean(hostDigits) && to.endsWith("@c.us") && digits(to) === hostDigits;
  }

  if (isOutgoing(message)) return false;
  return Boolean(ownerDigits) && digits(message.from) === ownerDigits;
}

/** Converte "data:<mime>;base64,<dados>" em { mime, base64 }. */
export function parseDataUrl(dataUrl) {
  const match = /^data:([^;,]+)(?:;[^,]*)?,(.*)$/s.exec(String(dataUrl ?? ""));
  return match ? { mime: match[1], base64: match[2] } : null;
}

/** Monta o corpo enviado para POST /channels/whatsapp/inbound. */
export function toInboundPayload(message, media = null) {
  const payload = {
    id: messageId(message),
    type: message.type ?? "chat",
    timestamp: message.t ?? message.timestamp ?? null,
    mimetype: message.mimetype ?? media?.mime ?? null,
  };
  if (payload.type === "chat") payload.body = message.body ?? "";
  if (message.caption) payload.caption = message.caption;
  if (media) payload.media_b64 = media.base64;
  return payload;
}
