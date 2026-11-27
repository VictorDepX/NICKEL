import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { StatusLine } from "@/components/chat/status-line";
import { applyEvent, initialState, type AuditEvent, type MonitorState } from "@/lib/monitor-core";
import { appState, renderWithProviders } from "@/test-utils";
import Conversa from "./conversa";

const mocks = vi.hoisted(() => ({
  events: { state: null as unknown as MonitorState, catalog: {}, connected: true },
}));

vi.mock("@/hooks/use-events", () => ({ useEvents: () => mocks.events }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ApiError: actual.ApiError,
    getState: vi.fn(),
    getMessages: vi.fn(),
    getWorkspaces: vi.fn(),
    getPending: vi.fn(),
    getPreferences: vi.fn(),
    setPreferences: vi.fn(),
    sendChat: vi.fn(),
    confirmPending: vi.fn(),
    cancelPending: vi.fn(),
    ttsSpeak: vi.fn(),
    ttsStop: vi.fn(),
    toggleVoice: vi.fn(),
  };
});

import * as api from "@/lib/api";

const pendingAction: api.PendingAction = {
  id: "p1",
  tool: "reminder_create",
  arguments: { text: "água" },
  summary: "criar lembrete 'água' às 15:00",
  channel: "ui",
  status: "pending",
  created_at: "2026-11-27T15:00:00+00:00",
  result: null,
};

const withVoice = (over: Partial<api.VoiceState> = {}) =>
  appState([], {
    voice: { available: true, state: "idle", stt: true, tts: { provider: "edge", ok: true, detail: "" }, microphone: true, ...over },
  });

beforeEach(() => {
  localStorage.clear();
  mocks.events.state = initialState();
  mocks.events.connected = true;
  vi.mocked(api.getState).mockResolvedValue(withVoice());
  vi.mocked(api.getMessages).mockResolvedValue([]);
  vi.mocked(api.getWorkspaces).mockResolvedValue({
    active: "geral",
    items: [{ id: "geral", name: "Geral", description: "", aliases: [], backend: null, tools: null, notes_dir: null }],
  });
  vi.mocked(api.getPending).mockResolvedValue([]);
  vi.mocked(api.getPreferences).mockResolvedValue({ speak: false });
  vi.mocked(api.sendChat).mockResolvedValue({ text: "Feito.", pending_action_id: null, links: [] });
  vi.mocked(api.confirmPending).mockResolvedValue({ text: "Lembrete criado para 15:00." });
  vi.mocked(api.cancelPending).mockResolvedValue({ text: "Cancelado: criar lembrete." });
});

const typeAndSend = (text: string) => {
  fireEvent.change(screen.getByLabelText("Mensagem para o NICKEL"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
};

test("envio chama sendChat com o 'Pensar' do toggle e mostra a mensagem na hora", async () => {
  renderWithProviders(<Conversa />, "/conversa");
  await screen.findByText(/Geral/);
  const pensar = screen.getByRole("button", { name: /Pensar/ });
  expect(pensar).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(pensar);
  expect(pensar).toHaveAttribute("aria-pressed", "true");
  await waitFor(() => expect(screen.getByRole("button", { name: /Falar respostas/ })).not.toBeDisabled());

  typeAndSend("lembra de beber água");
  expect(screen.getByText("lembra de beber água")).toBeInTheDocument();
  await waitFor(() =>
    expect(api.sendChat).toHaveBeenCalledWith({ text: "lembra de beber água", think: true, speak: false }),
  );
  expect(await screen.findByText("Feito.")).toBeInTheDocument();
  expect(localStorage.getItem("nickel.think")).toBe("1");
});

test("erro da API no envio aparece na conversa e o texto volta para a caixa", async () => {
  vi.mocked(api.sendChat).mockRejectedValue(new api.ApiError(502, "llama-server fora do ar"));
  renderWithProviders(<Conversa />, "/conversa");
  await screen.findByText(/Geral/);
  typeAndSend("oi");
  const alert = await screen.findByRole("alert");
  expect(within(alert).getByText("llama-server fora do ar")).toBeInTheDocument();
  expect(screen.getByLabelText("Mensagem para o NICKEL")).toHaveValue("oi");
});

test("histórico fora do ar mostra o erro em vez de tela vazia", async () => {
  vi.mocked(api.getMessages).mockRejectedValue(new TypeError("Failed to fetch"));
  renderWithProviders(<Conversa />, "/conversa");
  const alert = await screen.findByRole("alert");
  expect(within(alert).getByText("Failed to fetch")).toBeInTheDocument();
});

test("resposta do assistente em markdown vira lista, sem ** cru", async () => {
  vi.mocked(api.getMessages).mockResolvedValue([
    { id: 1, channel: "ui", role: "assistant", content: "**Hoje:**\n\n- academia\n- mercado", attachments: [], created_at: "2026-11-27T15:00:00+00:00" },
  ]);
  renderWithProviders(<Conversa />, "/conversa");
  expect(await screen.findByText("academia")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByText("Hoje:")).toHaveAttribute("data-streamdown", "strong");
  expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Ouvir" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copiar" })).toBeInTheDocument();
});

test("confirmação pendente: Sim chama confirmPending e a resposta entra na conversa", async () => {
  vi.mocked(api.getPending).mockResolvedValue([pendingAction]);
  renderWithProviders(<Conversa />, "/conversa");
  expect(await screen.findByText("Ação sensível · aguardando você")).toBeInTheDocument();
  vi.mocked(api.getPending).mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "Sim" }));
  await waitFor(() => expect(api.confirmPending).toHaveBeenCalledWith("p1"));
  expect(await screen.findByText("Lembrete criado para 15:00.")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText("Ação sensível · aguardando você")).not.toBeInTheDocument());
});

test("confirmação pendente: Não chama cancelPending", async () => {
  vi.mocked(api.getPending).mockResolvedValue([pendingAction]);
  renderWithProviders(<Conversa />, "/conversa");
  fireEvent.click(await screen.findByRole("button", { name: "Não" }));
  await waitFor(() => expect(api.cancelPending).toHaveBeenCalledWith("p1"));
  expect(api.confirmPending).not.toHaveBeenCalled();
});

test("microfone desabilitado sem voz configurada", async () => {
  vi.mocked(api.getState).mockResolvedValue(
    appState([], { voice: { available: false, state: "off", stt: false, tts: { provider: null, ok: false, detail: "" }, microphone: false } }),
  );
  renderWithProviders(<Conversa />, "/conversa");
  await screen.findByText(/Geral/);
  await waitFor(() => expect(screen.getByRole("button", { name: "Microfone" })).toBeDisabled());
  expect(screen.getByRole("button", { name: /Falar respostas/ })).toBeDisabled();
});

test("fase speaking mostra a barra de voz e Parar chama ttsStop", async () => {
  vi.mocked(api.ttsStop).mockResolvedValue({ stopped: true });
  mocks.events.state = { ...initialState(), phase: "speaking", since: new Date().toISOString() };
  renderWithProviders(<Conversa />, "/conversa");
  fireEvent.click(await screen.findByRole("button", { name: "Parar" }));
  expect(api.ttsStop).toHaveBeenCalled();
});

// ------------------------------------------------------------------ linha de status

const T0 = Date.now() - 3000;
let eid = 0;
const ev = (kind: string, status: string, detail: Record<string, unknown> = {}): AuditEvent => ({
  id: ++eid, kind, name: kind === "llm" ? "gemma" : "ui", status, at: new Date(T0 + eid * 100).toISOString(), run_id: "r1", detail, duration_ms: null,
});
const catalog = { phases: { "turn/start": "routing", "llm/start": "thinking", "reasoning/progress": "thinking" } };

test("linha de status: 'Pensando… · N caracteres de raciocínio' com raciocínio em curso", () => {
  const state = [ev("turn", "start"), ev("llm", "start", { step: 0, think: true }), ev("reasoning", "progress", { step: 0, chars: 1234, tail: "hmm" })].reduce(
    (s, e) => applyEvent(s, e, catalog),
    initialState(),
  );
  renderWithProviders(<StatusLine state={state} connected />);
  expect(screen.getByRole("status")).toHaveTextContent("Pensando… · 1.234 caracteres de raciocínio");
  expect(screen.getByLabelText("Tempo decorrido")).toHaveTextContent(/^00:0\d$/);
});

test("linha de status avisa quando o SSE está reconectando", () => {
  renderWithProviders(<StatusLine state={initialState()} connected={false} />);
  expect(screen.getByRole("status")).toHaveTextContent("Pronto · reconectando…");
});
