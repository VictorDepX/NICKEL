import { screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ResourceCapsule } from "@/components/resource-capsule";
import { appState, connector, renderWithProviders } from "@/test-utils";

vi.mock("@/lib/api", () => ({
  getState: vi.fn(),
  getReminders: vi.fn(),
  getPending: vi.fn(),
  getSystemMemory: vi.fn(),
}));
vi.mock("@/hooks/use-events", () => ({
  useEvents: () => ({
    state: {
      lastId: 1,
      timeline: [{ id: 1, at: "", kind: "llm", name: "llm", status: "done", detail: { tokens_per_second: 20, prompt_tokens: 4096 }, run_id: null, duration_ms: null }],
    },
    catalog: {},
    connected: true,
  }),
}));

import * as api from "@/lib/api";

const GB = 1024 ** 3;
const memory = (usedPct: number) => ({
  available: true,
  interval_s: 5,
  samples: [{ t: 1, total: 100 * GB, used: usedPct * GB, available: (100 - usedPct) * GB, llama: 10 * GB, nickel: 1 * GB }],
});

beforeEach(() => {
  vi.mocked(api.getState).mockResolvedValue(
    appState([connector("a", "ok"), connector("b", "ok"), connector("c", "bad"), connector("d", "warn")]),
  );
  vi.mocked(api.getReminders).mockResolvedValue([]);
  vi.mocked(api.getPending).mockResolvedValue([]);
  vi.mocked(api.getSystemMemory).mockResolvedValue(memory(50));
});

test("mostra 2/4 com dois conectores ok de quatro", async () => {
  renderWithProviders(<ResourceCapsule />);
  expect(await screen.findByText("2/4")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Conexões: 2 de 4 ok" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("img", { name: "Contexto: 25%" })).toBeInTheDocument());
});

test.each([
  [50, "var(--success)"],
  [75, "var(--warning)"],
  [91, "var(--warning)"],
  [92, "var(--destructive)"],
])("anel de RAM em %s%% usa %s", async (pct, color) => {
  vi.mocked(api.getSystemMemory).mockResolvedValue(memory(pct));
  const { container } = renderWithProviders(<ResourceCapsule />);
  await screen.findByRole("img", { name: `Memória RAM: ${pct}%` });
  expect(container.querySelector("[data-arc]")).toHaveAttribute("stroke", color);
});
