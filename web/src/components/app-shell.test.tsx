import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { AppShell } from "@/components/app-shell";
import { appState, connector } from "@/test-utils";

vi.mock("@/lib/api", () => ({
  getState: vi.fn(),
  getReminders: vi.fn(),
  getPending: vi.fn(),
  getWorkspaces: vi.fn(),
  activateWorkspace: vi.fn(),
  getSystemMemory: vi.fn(),
}));
vi.mock("@/hooks/use-events", () => ({
  useEvents: () => ({ state: { lastId: 0, timeline: [] }, catalog: {}, connected: true }),
}));

import * as api from "@/lib/api";

const GB = 1024 ** 3;
const originalWidth = window.innerWidth;

function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  window.matchMedia = ((query: string) => ({
    matches: query.includes("max-width") ? width < 768 : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

function renderShell(route = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="*" element={<p>conteúdo</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.getState).mockResolvedValue(appState([connector("llm", "ok")]));
  vi.mocked(api.getReminders).mockResolvedValue([]);
  vi.mocked(api.getPending).mockResolvedValue([]);
  vi.mocked(api.getWorkspaces).mockResolvedValue({ active: "geral", items: [] });
  vi.mocked(api.getSystemMemory).mockResolvedValue({
    available: true,
    interval_s: 5,
    samples: [{ t: 1, total: 100 * GB, used: 60 * GB, available: 40 * GB, llama: 10 * GB, nickel: GB }],
  });
});

afterEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
});

test("390 px: menu em gaveta e recursos num botão do cabeçalho com anel de RAM", async () => {
  setViewport(390);
  renderShell("/");

  // Sem cápsula fixa nem menu aberto.
  expect(screen.queryByRole("complementary", { name: "Recursos" })).toBeNull();
  expect(screen.queryByRole("link", { name: /Conversa/ })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
  const menu = await screen.findByRole("dialog", { name: "Menu principal" });
  expect(within(menu).getByRole("link", { name: /Conversa/ })).toBeInTheDocument();
  fireEvent.click(within(menu).getByRole("link", { name: /Conversa/ }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Menu principal" })).toBeNull());

  const resources = screen.getByRole("button", { name: "Recursos do sistema" });
  await waitFor(() => expect(within(resources).getByRole("img", { name: "Memória RAM: 60%" })).toBeInTheDocument());
  fireEvent.click(resources);
  const sheet = await screen.findByRole("dialog", { name: "Recursos" });
  expect(await within(sheet).findByText("Memória RAM")).toBeInTheDocument();
  expect(within(sheet).getByText("Conectores")).toBeInTheDocument();
});

test("390 px: telas sem cápsula só mostram o botão do menu", () => {
  setViewport(390);
  renderShell("/lembretes");
  expect(screen.getByRole("button", { name: "Abrir menu" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Recursos do sistema" })).toBeNull();
});

test("desktop: sem cabeçalho móvel; a cápsula fica fixa", async () => {
  setViewport(1280);
  renderShell("/");
  expect(screen.queryByRole("button", { name: "Abrir menu" })).toBeNull();
  expect(await screen.findByRole("complementary", { name: "Recursos" })).toBeInTheDocument();
});
