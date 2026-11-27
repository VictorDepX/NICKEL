import { screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { AppSidebar } from "@/components/app-sidebar";
import { appState, connector, renderWithProviders } from "@/test-utils";

vi.mock("@/lib/api", () => ({
  getState: vi.fn(),
  getReminders: vi.fn(),
  getWorkspaces: vi.fn(),
  activateWorkspace: vi.fn(),
}));
vi.mock("@/hooks/use-events", () => ({
  useEvents: () => ({ state: { lastId: 0, timeline: [] }, catalog: {}, connected: true }),
}));

import * as api from "@/lib/api";

beforeEach(() => {
  vi.mocked(api.getState).mockResolvedValue(appState([connector("llm", "ok"), connector("wa", "bad")]));
  vi.mocked(api.getReminders).mockResolvedValue([]);
  vi.mocked(api.getWorkspaces).mockResolvedValue({
    active: "geral",
    items: [
      { id: "geral", name: "Geral", description: "", aliases: [], backend: null, tools: null, notes_dir: null },
      { id: "codigo", name: "Código", description: "", aliases: [], backend: null, tools: null, notes_dir: null },
    ],
  });
});

test("marca a rota ativa com aria-current=page", async () => {
  renderWithProviders(<AppSidebar />, "/memoria");
  const active = await screen.findByRole("link", { name: /Memória/ });
  expect(active).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: /Início/ })).not.toHaveAttribute("aria-current");
});

test("mostra conectores fora, workspace ativo e o modelo", async () => {
  renderWithProviders(<AppSidebar />, "/");
  expect(await screen.findByText("1 fora")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("ativo")).toBeInTheDocument());
  expect(screen.getByText("gemma-4")).toBeInTheDocument();
  expect(screen.getByText("llama.cpp · local")).toBeInTheDocument();
});
