import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { SidebarProvider } from "@/components/ui/sidebar";
import type { AppState, ConnectorItem } from "@/lib/api";

export function connector(id: string, level: ConnectorItem["level"]): ConnectorItem {
  return { id, name: id, level, detail: "" };
}

export function appState(connectors: ConnectorItem[], over: Partial<AppState> = {}): AppState {
  return {
    llm: { ok: true, model: "gemma-4" },
    whatsapp: { ready: true },
    google: { status: "ok" },
    spotify: { status: "ok" },
    obsidian: { available: true, notes_dir: "", vault: "" },
    voice: { available: true, state: "idle", stt: true, tts: { provider: null, ok: true, detail: "" }, microphone: true },
    connectors,
    pipelines: [],
    music: false,
    tools: [],
    workspace: "geral",
    think_default: false,
    ...over,
  };
}

export function renderWithProviders(ui: ReactElement, route = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <SidebarProvider>{ui}</SidebarProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
