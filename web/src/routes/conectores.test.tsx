import { screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { appState, renderWithProviders } from "@/test-utils";
import Conectores from "./conectores";

vi.mock("@/hooks/use-events", () => ({ useEvents: () => ({ state: { lastId: 0, timeline: [] }, catalog: {}, connected: true }) }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ApiError: actual.ApiError, getState: vi.fn() };
});
import * as api from "@/lib/api";

beforeEach(() => {
  vi.mocked(api.getState).mockResolvedValue(
    appState(
      [
        { id: "llm", name: "Modelo", level: "ok", detail: "gemma-4" },
        { id: "google", name: "Google", level: "warn", detail: "falta autorizar", action: "/auth/google/start" },
        { id: "whatsapp", name: "WhatsApp", level: "bad", detail: "sem sessão" },
      ],
      { pipelines: [{ id: "tts", name: "Voz", level: "ok", detail: "Edge TTS" }] },
    ),
  );
});

test("cartões mostram o nível em texto, o detalhe e a ação", async () => {
  renderWithProviders(<Conectores />);
  expect(await screen.findByText("funcionando")).toBeInTheDocument();
  expect(screen.getByText("falta um passo")).toBeInTheDocument();
  expect(screen.getByText("fora do ar")).toBeInTheDocument();
  expect(screen.getByText(/gemma-4/)).toBeInTheDocument();
  const link = screen.getByRole("link", { name: "Conectar" });
  expect(link).toHaveAttribute("href", "/auth/google/start");
  expect(screen.getAllByRole("link", { name: "Conectar" })).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "Pipelines" })).toBeInTheDocument();
  expect(screen.getByText("Edge TTS")).toBeInTheDocument();
});
