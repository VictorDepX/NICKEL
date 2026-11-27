import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { memLevel, MemoryCard } from "@/components/monitor/memory-card";
import { applyEvent, initialState, type AuditEvent, type Catalog, type MonitorState } from "@/lib/monitor-core";
import type { SystemMemorySample } from "@/lib/api";
import { renderWithProviders } from "@/test-utils";
import Monitor from "./monitor";

const CATALOG: Catalog = {
  kinds: {},
  phases: { "turn/start": "routing", "llm/start": "thinking", "tool/start": "tool", "turn/done": "idle", "turn/error": "error" },
  labels: { routing: "Roteando", thinking: "Pensando", tool: "Executando ferramenta", idle: "Ocioso", error: "Erro" },
};

const mocks = vi.hoisted(() => ({
  events: { state: null as unknown as MonitorState, catalog: {} as Catalog, connected: true },
}));

vi.mock("@/hooks/use-events", () => ({ useEvents: () => mocks.events }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ApiError: actual.ApiError,
    runReportUrl: actual.runReportUrl,
    getRuns: vi.fn(),
    getRun: vi.fn(),
    getSystemMemory: vi.fn(),
  };
});

import * as api from "@/lib/api";

const GIB = 1024 ** 3;
let nextId = 1;

function ev(run: string, kind: string, name: string, status: string, detail: Record<string, unknown> = {}): AuditEvent {
  const id = nextId++;
  return { id, at: new Date(Date.UTC(2026, 10, 27, 15, 0, id)).toISOString(), kind, name, status, detail, run_id: run, duration_ms: null };
}

function stateWith(events: AuditEvent[]): MonitorState {
  return events.reduce((s, e) => applyEvent(s, e, CATALOG), initialState());
}

function sample(i: number, availableGb = 6): SystemMemorySample {
  return { t: 1_800_000_000 + i * 5, total: 16 * GIB, used: (16 - availableGb) * GIB, available: availableGb * GIB, llama: 5 * GIB, nickel: 0.3 * GIB };
}

const LIVE = "aaaaaaaa1111";
const OLD = "bbbbbbbb2222";

beforeEach(() => {
  nextId = 1;
  mocks.events.catalog = CATALOG;
  mocks.events.state = stateWith([
    ev(LIVE, "turn", "ui", "start", { channel: "ui" }),
    ev(LIVE, "tool", "reminder_create", "start"),
    ev(LIVE, "tool", "reminder_create", "error", { detail: "horário inválido" }),
    ev(LIVE, "turn", "ui", "done", { steps: 2, reply_chars: 40 }),
  ]);
  vi.mocked(api.getRuns).mockResolvedValue([
    { run_id: LIVE, started_at: "2026-11-27T15:00:01Z", events: 4, errors: 1, duration_ms: 3000 },
    { run_id: OLD, started_at: "2026-11-27T14:00:00Z", events: 2, errors: 0, duration_ms: 2400 },
  ]);
  vi.mocked(api.getRun).mockResolvedValue([
    ev(OLD, "turn", "ui", "start", { channel: "whatsapp" }),
    ev(OLD, "route", "agenda", "resolved", { workspace: "agenda" }),
  ]);
  vi.mocked(api.getSystemMemory).mockResolvedValue({ available: true, samples: [sample(0), sample(1)], interval_s: 5 });
});

const eventRows = () => within(screen.getByRole("list", { name: "Eventos" })).getAllByRole("listitem");

test("'Só erros' esconde os eventos que não são erro", () => {
  renderWithProviders(<Monitor />, "/monitor");
  expect(eventRows()).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Só erros" }));
  const rows = eventRows();
  expect(rows).toHaveLength(1);
  expect(rows[0]).toHaveTextContent("tool/reminder_create");
  expect(rows[0]).toHaveAttribute("data-status", "error");
});

test("filtro por tipo esconde os eventos daquele tipo", () => {
  renderWithProviders(<Monitor />, "/monitor");
  const filters = screen.getByRole("group", { name: "Filtrar por tipo de evento" });
  fireEvent.click(within(filters).getByRole("button", { name: "tool" }));
  expect(eventRows()).toHaveLength(2);
  expect(eventRows().every((row) => row.textContent?.includes("turn/ui"))).toBe(true);
});

test("evento expande para mostrar o JSON de detalhes", () => {
  renderWithProviders(<Monitor />, "/monitor");
  fireEvent.click(within(eventRows()[2]).getByRole("button"));
  expect(within(eventRows()[2]).getByText(/"detail": "horário inválido"/)).toBeInTheDocument();
});

test("selecionar uma execução carrega os eventos dela", async () => {
  renderWithProviders(<Monitor />, "/monitor");
  fireEvent.click(await screen.findByRole("button", { name: "Ver execução bbbbbbbb" }));
  await waitFor(() => expect(api.getRun).toHaveBeenCalledWith(OLD));
  await waitFor(() => expect(eventRows()).toHaveLength(2));
  expect(eventRows()[1]).toHaveTextContent("route/agenda");
  expect(screen.getByText("whatsapp")).toBeInTheDocument(); // resumo do turno da execução escolhida
  // Voltar para a execução atual usa o estado ao vivo, sem novo fetch.
  fireEvent.click(screen.getByRole("button", { name: "Ver execução aaaaaaaa" }));
  expect(eventRows()).toHaveLength(4);
  expect(api.getRun).toHaveBeenCalledTimes(1);
});

test("links de relatório apontam para /api/runs/{id}/report.md", async () => {
  renderWithProviders(<Monitor />, "/monitor");
  const header = screen.getByRole("link", { name: "Baixar relatório" });
  expect(header).toHaveAttribute("href", `/api/runs/${LIVE}/report.md`);
  const perRun = await screen.findByRole("link", { name: "Baixar relatório da execução bbbbbbbb" });
  expect(perRun).toHaveAttribute("href", `/api/runs/${OLD}/report.md`);
  expect(perRun).toHaveAttribute("download");
});

test("resumo do turno mostra estado, passos e erros", () => {
  renderWithProviders(<Monitor />, "/monitor");
  const timeline = screen.getByRole("region", { name: "Linha do tempo" });
  expect(within(timeline).getByText("Concluído")).toBeInTheDocument();
  expect(within(timeline).getByText("40 caracteres")).toBeInTheDocument();
});

test.each([
  [6, "ok", "RAM folgada"],
  [2.5, "ok", "RAM folgada"],
  [2.49, "warn", "RAM apertada"],
  [1, "warn", "RAM apertada"],
  [0.99, "bad", "pouca RAM livre"],
])("nível de RAM com %s GB livres", (free, level, text) => {
  expect(memLevel({ available: free * GIB })).toEqual({ level, text });
});

test("cartão de memória mostra fatos, nível e legenda com as 3 séries", async () => {
  vi.mocked(api.getSystemMemory).mockResolvedValue({ available: true, samples: [sample(0, 2), sample(1, 2)], interval_s: 5 });
  renderWithProviders(<MemoryCard />);
  expect(await screen.findByText("RAM apertada")).toHaveAttribute("data-level", "warn");
  expect(screen.getByText("14 de 16 GB (88%)")).toBeInTheDocument();
  expect(screen.getByText("5 GB")).toBeInTheDocument(); // llama-server
  const legend = screen.getByRole("list", { name: "Legenda" });
  expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
    "RAM usada (total)",
    "llama-server (modelo)",
    "NICKEL",
  ]);
});

test("'Ver tabela' mostra no máximo as 12 últimas leituras", async () => {
  const samples = Array.from({ length: 20 }, (_, i) => sample(i));
  vi.mocked(api.getSystemMemory).mockResolvedValue({ available: true, samples, interval_s: 5 });
  renderWithProviders(<MemoryCard />);
  fireEvent.click(await screen.findByRole("button", { name: "Ver tabela" }));
  const table = screen.getByRole("table");
  const body = within(table).getAllByRole("rowgroup")[1];
  expect(within(body).getAllByRole("row")).toHaveLength(12);
});

test("memória indisponível mostra aviso em vez do gráfico", async () => {
  vi.mocked(api.getSystemMemory).mockResolvedValue({ available: false, samples: [], interval_s: 5 });
  renderWithProviders(<MemoryCard />);
  expect(await screen.findByText("Leitura de memória indisponível neste sistema.")).toBeInTheDocument();
});
