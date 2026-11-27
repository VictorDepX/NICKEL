import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { initialState, type MonitorState } from "@/lib/monitor-core";
import { appState, connector, renderWithProviders } from "@/test-utils";
import Inicio from "./inicio";

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
    getReminders: vi.fn(),
    confirmPending: vi.fn(),
    cancelPending: vi.fn(),
    toggleVoice: vi.fn(),
  };
});

import * as api from "@/lib/api";

const pendingAction: api.PendingAction = {
  id: "p1",
  tool: "reminder_create",
  arguments: {},
  summary: "criar lembrete 'água' às 15:00",
  channel: "ui",
  status: "pending",
  created_at: "2026-11-27T15:00:00+00:00",
  result: null,
};

function Destination() {
  const location = useLocation();
  return <div data-testid="destino">{location.pathname + JSON.stringify(location.state)}</div>;
}

const renderInicio = () =>
  renderWithProviders(
    <Routes>
      <Route path="/" element={<Inicio />} />
      <Route path="/conversa" element={<Destination />} />
    </Routes>,
  );

beforeEach(() => {
  localStorage.clear();
  mocks.events.state = initialState();
  vi.mocked(api.getState).mockResolvedValue(appState([connector("llm", "ok"), connector("whatsapp", "bad")]));
  vi.mocked(api.getMessages).mockResolvedValue([]);
  vi.mocked(api.getWorkspaces).mockResolvedValue({ active: "geral", items: [] });
  vi.mocked(api.getPending).mockResolvedValue([]);
  vi.mocked(api.getReminders).mockResolvedValue([]);
  vi.mocked(api.confirmPending).mockResolvedValue({ text: "ok" });
  vi.mocked(api.cancelPending).mockResolvedValue({ text: "ok" });
  vi.mocked(api.toggleVoice).mockResolvedValue(undefined as never);
});

afterEach(() => vi.useRealTimers());

test.each([
  ["2026-11-27T04:59:00", "Boa noite, Victor."],
  ["2026-11-27T05:00:00", "Bom dia, Victor."],
  ["2026-11-27T11:59:00", "Bom dia, Victor."],
  ["2026-11-27T12:00:00", "Boa tarde, Victor."],
  ["2026-11-27T18:00:00", "Boa noite, Victor."],
])("saudação às %s", (at, expected) => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date(at) });
  renderInicio();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(expected);
  expect(screen.getByText("sexta, 27 de novembro")).toBeInTheDocument();
});

test("o campo pílula leva à Conversa com o rascunho", async () => {
  renderInicio();
  fireEvent.change(screen.getByLabelText("Mensagem para o NICKEL"), { target: { value: " que horas são? " } });
  fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
  expect((await screen.findByTestId("destino")).textContent).toBe('/conversa{"draft":"que horas são?"}');
});

test("clicar na esfera abre a Conversa e liga o microfone", async () => {
  renderInicio();
  await waitFor(() => expect(api.getState).toHaveBeenCalled());
  await screen.findByText("whatsapp");
  fireEvent.click(screen.getByRole("button", { name: "Falar com o NICKEL" }));
  await screen.findByTestId("destino");
  expect(api.toggleVoice).toHaveBeenCalledTimes(1);
});

test("cartão pendente: ações que não são memory_save usam Sim/Não e mostram a ferramenta", async () => {
  vi.mocked(api.getPending).mockResolvedValue([{ ...pendingAction, tool: "gmail_send" }]);
  renderInicio();
  expect(await screen.findByRole("button", { name: "Sim" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Não" })).toBeInTheDocument();
  expect(screen.getByText("gmail_send")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Guardar" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Recusar" })).not.toBeInTheDocument();
});

test("a esfera não promete atalho de teclado", async () => {
  renderInicio();
  await screen.findByText(/Pronto/);
  expect(screen.queryByText(/Espaço/)).not.toBeInTheDocument();
});

test("cartão pendente: memory_save usa Guardar/Recusar; Recusar chama cancelPending", async () => {
  vi.mocked(api.getPending).mockResolvedValueOnce([{ ...pendingAction, tool: "memory_save" }]).mockResolvedValue([]);
  renderInicio();
  expect(await screen.findByRole("button", { name: "Guardar" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Recusar" }));
  await waitFor(() => expect(api.cancelPending).toHaveBeenCalledWith("p1"));
});

test("cartão pendente: clique duplo em Guardar chama confirmPending uma vez", async () => {
  vi.mocked(api.getPending).mockResolvedValueOnce([{ ...pendingAction, tool: "memory_save" }]).mockResolvedValue([]);
  renderInicio();
  const guardar = await screen.findByRole("button", { name: "Guardar" });
  fireEvent.click(guardar);
  fireEvent.click(guardar);
  await waitFor(() => expect(screen.queryByRole("button", { name: "Guardar" })).not.toBeInTheDocument());
  expect(api.confirmPending).toHaveBeenCalledTimes(1);
  expect(api.confirmPending).toHaveBeenCalledWith("p1");
  expect(screen.getByText("Nada pendente.")).toBeInTheDocument();
});

test("sem lembretes mostra o estado vazio com link", async () => {
  renderInicio();
  expect(await screen.findByText("Nenhum lembrete agendado.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Criar lembrete" })).toHaveAttribute("href", "/lembretes");
});

test("cartão de conectores lista os que falham", async () => {
  renderInicio();
  const bad = await screen.findByText("whatsapp");
  expect(bad).toHaveClass("text-destructive-foreground");
  expect(screen.getByRole("link", { name: "Resolver conexões" })).toHaveAttribute("href", "/conectores");
});

test("continuar conversa mostra a última mensagem do usuário", async () => {
  vi.mocked(api.getMessages).mockResolvedValue([
    { id: 1, channel: "ui", role: "user", content: "primeira", attachments: [], created_at: "2026-11-27T10:00:00" },
    { id: 2, channel: "ui", role: "assistant", content: "resposta", attachments: [], created_at: "2026-11-27T10:01:00" },
    { id: 3, channel: "ui", role: "user", content: "última pergunta", attachments: [], created_at: "2026-11-27T10:05:00" },
  ]);
  renderInicio();
  expect(await screen.findByText("última pergunta")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Abrir · 10:05/ })).toHaveAttribute("href", "/conversa");
});

test("o histórico é pedido para o workspace ativo", async () => {
  renderInicio();
  await waitFor(() => expect(api.getMessages).toHaveBeenCalledWith(120, "geral"));
});

test("o relógio avança sozinho", () => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"], now: new Date("2026-11-27T14:33:10") });
  renderInicio();
  expect(screen.getByText("14:33")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(60_000));
  expect(screen.getByText("14:34")).toBeInTheDocument();
});
