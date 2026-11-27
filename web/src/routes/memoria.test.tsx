import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { renderWithProviders } from "@/test-utils";
import Memoria from "./memoria";

vi.mock("@/hooks/use-events", () => ({ useEvents: () => ({ state: { lastId: 0, timeline: [] }, catalog: {}, connected: true }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ApiError: actual.ApiError, getMemory: vi.fn(), forgetMemory: vi.fn(), getPending: vi.fn(),
    confirmPending: vi.fn(), cancelPending: vi.fn(),
  };
});
import * as api from "@/lib/api";

beforeEach(() => {
  vi.mocked(api.getMemory).mockResolvedValue([
    { key: "playlist de foco", value: "Lo-fi BR", created_at: "2026-11-01T10:00:00+00:00" },
    { key: "cor favorita", value: "azul", created_at: "2026-11-02T10:00:00+00:00" },
  ]);
  vi.mocked(api.getPending).mockResolvedValue([]);
  vi.mocked(api.forgetMemory).mockReset().mockResolvedValue({ deleted: true });
  vi.mocked(api.confirmPending).mockReset().mockResolvedValue({ text: "ok" });
});

test("busca filtra por chave ou valor", async () => {
  renderWithProviders(<Memoria />);
  expect(await screen.findByText("playlist de foco")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Buscar" }), { target: { value: "azul" } });
  expect(screen.queryByText("playlist de foco")).not.toBeInTheDocument();
  expect(screen.getByText("cor favorita")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Buscar" }), { target: { value: "lo-fi" } });
  expect(screen.getByText("playlist de foco")).toBeInTheDocument();
});

test("apagar pede confirmação e depois chama forgetMemory", async () => {
  renderWithProviders(<Memoria />);
  fireEvent.click(await screen.findByRole("button", { name: "Apagar cor favorita" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText("Apagar cor favorita?")).toBeInTheDocument();
  expect(api.forgetMemory).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Apagar" }));
  await waitFor(() => expect(api.forgetMemory).toHaveBeenCalledWith("cor favorita"));
});

test("confirmações de memory_save aparecem com Guardar e protegem o clique duplo", async () => {
  const action: api.PendingAction = {
    id: "p1", tool: "memory_save", arguments: {}, summary: "guardar na memória 'x': y", channel: "ui",
    status: "pending", created_at: "", result: null,
  };
  vi.mocked(api.getPending).mockResolvedValue([action, { ...action, id: "p2", tool: "email_send", summary: "enviar e-mail" }]);
  renderWithProviders(<Memoria />);
  expect(await screen.findByText("guardar na memória 'x': y")).toBeInTheDocument();
  expect(screen.queryByText("enviar e-mail")).not.toBeInTheDocument();
  const guardar = screen.getByRole("button", { name: "Guardar" });
  fireEvent.click(guardar);
  fireEvent.click(guardar);
  await waitFor(() => expect(api.confirmPending).toHaveBeenCalledTimes(1));
  expect(api.confirmPending).toHaveBeenCalledWith("p1");
});
