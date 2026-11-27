import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError, cancelReminder, createReminder, getState, sendChat } from "./api";

const fetchMock = vi.fn();

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

beforeEach(() => vi.stubGlobal("fetch", fetchMock));
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

test("sendChat faz POST /api/chat com JSON e think nulo por padrão", async () => {
  fetchMock.mockResolvedValue(reply({ text: "oi", pending_action_id: null, links: [] }));
  const out = await sendChat({ text: "olá" });
  expect(out.text).toBe("oi");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/chat");
  expect(init.method).toBe("POST");
  expect(init.headers).toEqual({ "content-type": "application/json" });
  expect(JSON.parse(init.body)).toEqual({ text: "olá", think: null });
});

test("sendChat envia think e speak quando informados", async () => {
  fetchMock.mockResolvedValue(reply({ text: "", pending_action_id: null, links: [] }));
  await sendChat({ text: "x", think: true, speak: false });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ text: "x", think: true, speak: false });
});

test("createReminder faz POST /api/reminders com texto e quando", async () => {
  fetchMock.mockResolvedValue(reply({ id: 1 }));
  await createReminder({ text: "beber água", when: "amanhã 9h" });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/reminders");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({ text: "beber água", when: "amanhã 9h" });
});

test("cancelReminder usa DELETE sem corpo", async () => {
  fetchMock.mockResolvedValue(reply({ cancelled: 4 }));
  await cancelReminder(4);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/reminders/4");
  expect(init.method).toBe("DELETE");
  expect(init.body).toBeUndefined();
});

test("resposta de erro vira ApiError com o detail do servidor", async () => {
  fetchMock.mockResolvedValue(reply({ detail: "Mensagem vazia." }, 400));
  const error = await getState().catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).status).toBe(400);
  expect((error as ApiError).message).toBe("Mensagem vazia.");
});
