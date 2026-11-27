import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { renderWithProviders } from "@/test-utils";
import Lembretes from "./lembretes";

vi.mock("@/hooks/use-events", () => ({ useEvents: () => ({ state: { lastId: 0, timeline: [] }, catalog: {}, connected: true }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ApiError: actual.ApiError, getReminders: vi.fn(), createReminder: vi.fn(), cancelReminder: vi.fn() };
});
import * as api from "@/lib/api";

const soon = new Date(Date.now() + 29 * 60_000 + 20_000).toISOString();
const reminder: api.Reminder = {
  id: 7, text: "beber água", due_at: soon, due_local: "", repeat: "none", status: "scheduled",
  calendar_event_id: null, created_at: soon, delivered_at: null,
};

beforeEach(() => {
  vi.mocked(api.getReminders).mockResolvedValue([reminder]);
  vi.mocked(api.createReminder).mockReset();
  vi.mocked(api.cancelReminder).mockReset().mockResolvedValue({ cancelled: 7 });
});

test("lista com horário relativo e cancela pelo botão", async () => {
  renderWithProviders(<Lembretes />);
  expect(await screen.findByText("beber água")).toBeInTheDocument();
  expect(screen.getByText("em 29 min")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancelar lembrete" }));
  await waitFor(() => expect(api.cancelReminder).toHaveBeenCalledWith(7));
});

test("cria o lembrete enviando texto e when", async () => {
  vi.mocked(api.createReminder).mockResolvedValue(reminder);
  renderWithProviders(<Lembretes />);
  fireEvent.change(screen.getByLabelText("O quê"), { target: { value: "alongar" } });
  fireEvent.change(screen.getByLabelText("Dia"), { target: { value: "amanha" } });
  fireEvent.change(screen.getByLabelText("Hora"), { target: { value: "15:02" } });
  fireEvent.click(screen.getByRole("button", { name: "Criar lembrete" }));
  await waitFor(() => expect(api.createReminder).toHaveBeenCalledTimes(1));
  const { text, when } = vi.mocked(api.createReminder).mock.calls[0][0];
  expect(text).toBe("alongar");
  expect(when).toMatch(/^\d{4}-\d{2}-\d{2}T15:02$/);
  const d = new Date();
  d.setDate(d.getDate() + 1);
  expect(when.slice(8, 10)).toBe(String(d.getDate()).padStart(2, "0"));
});

test("mostra o detalhe do 422 embaixo do formulário", async () => {
  vi.mocked(api.createReminder).mockRejectedValue(new api.ApiError(422, "Horário inválido: use HH:MM."));
  renderWithProviders(<Lembretes />);
  fireEvent.change(screen.getByLabelText("O quê"), { target: { value: "x" } });
  fireEvent.change(screen.getByLabelText("Hora"), { target: { value: "10:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Criar lembrete" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Horário inválido: use HH:MM.");
});
