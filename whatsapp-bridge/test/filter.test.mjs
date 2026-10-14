import assert from "node:assert/strict";
import { test } from "node:test";
import { MARKER, digits, parseDataUrl, shouldForward, toInboundPayload } from "../src/filter.mjs";

const self = { mode: "self", hostDigits: "5563999990000", ownIds: new Set(["5563999990000@c.us", "123456@lid"]) };

test("digits normaliza JIDs", () => {
  assert.equal(digits("5563999990000@c.us"), "5563999990000");
  assert.equal(digits("5563999990000:12@s.whatsapp.net"), "5563999990000");
  assert.equal(digits("+55 (63) 99999-0000"), "5563999990000");
});

test("modo self aceita só o chat 'você mesmo'", () => {
  const mine = { id: "true_x_1", fromMe: true, from: "5563999990000@c.us", to: "5563999990000@c.us", body: "oi", type: "chat" };
  assert.equal(shouldForward(mine, self), true);
  assert.equal(shouldForward({ ...mine, from: "123456@lid", to: "123456@lid" }, self), true);
  assert.equal(shouldForward({ ...mine, from: "x@c.us", to: "123456@lid" }, self), true);
  // mensagem que eu mandei para outra pessoa
  assert.equal(shouldForward({ ...mine, to: "5511988887777@c.us" }, self), false);
  // mensagem recebida de outra pessoa
  assert.equal(shouldForward({ ...mine, fromMe: false, id: "false_x_2", from: "5511988887777@c.us" }, self), false);
});

test("modo self ignora as próprias respostas do NICKEL", () => {
  const base = { id: "true_x_9", fromMe: true, from: "5563999990000@c.us", to: "5563999990000@c.us", type: "chat" };
  assert.equal(shouldForward({ ...base, body: `${MARKER}Feito.` }, self), false);
  assert.equal(shouldForward({ ...base, body: "Feito." }, { ...self, sentIds: new Set(["true_x_9"]) }), false);
});

test("modo dedicated aceita só o dono", () => {
  const options = { mode: "dedicated", ownerDigits: "5563999990000" };
  const msg = { id: "false_a_1", fromMe: false, from: "5563999990000@c.us", to: "5511900000000@c.us", type: "chat", body: "oi" };
  assert.equal(shouldForward(msg, options), true);
  assert.equal(shouldForward({ ...msg, from: "5511977776666@c.us" }, options), false);
  assert.equal(shouldForward({ ...msg, fromMe: true, id: "true_a_2" }, options), false);
});

test("grupos e status são ignorados", () => {
  const msg = { id: "true_g_1", fromMe: true, from: "5563999990000@c.us", to: "1203630@g.us", type: "chat" };
  assert.equal(shouldForward(msg, self), false);
  assert.equal(shouldForward({ ...msg, to: "status@broadcast" }, self), false);
});

test("payload de entrada", () => {
  assert.deepEqual(parseDataUrl("data:audio/ogg; codecs=opus;base64,T2dn"), { mime: "audio/ogg", base64: "T2dn" });
  assert.equal(parseDataUrl("lixo"), null);
  const audio = toInboundPayload({ id: "true_1", type: "ptt", body: "/9j/thumb", t: 1 }, { mime: "audio/ogg", base64: "T2dn" });
  assert.deepEqual(audio, { id: "true_1", type: "ptt", timestamp: 1, mimetype: "audio/ogg", media_b64: "T2dn" });
  const text = toInboundPayload({ id: { _serialized: "true_2" }, type: "chat", body: "oi" });
  assert.equal(text.id, "true_2");
  assert.equal(text.body, "oi");
});
