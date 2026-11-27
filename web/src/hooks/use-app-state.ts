import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getState } from "@/lib/api";
import type { AuditEvent } from "@/lib/monitor-core";
import { useEvents } from "./use-events";

export const APP_STATE_KEY = ["state"] as const;
export const APP_STATE_REFETCH_MS = 10_000;

/** Eventos que mudam o que /api/state mostra (ou o que o Início lista). */
export function invalidatesAppState(event: AuditEvent): boolean {
  if (event.kind === "turn") return event.status === "done" || event.status === "error";
  return event.kind === "confirmation" || event.kind === "reminder";
}

/** Invalida /api/state quando um turno acaba, uma confirmação ou um lembrete muda. Monte uma vez só (AppShell). */
export function useAppStateSync() {
  const queryClient = useQueryClient();
  const { state } = useEvents();
  const seen = useRef<number | null>(null);

  useEffect(() => {
    const previous = seen.current;
    seen.current = state.lastId;
    if (previous === null) return; // primeira passada: só registra o ponto de partida (a consulta já busca ao montar)
    if (state.timeline.some((e) => e.id > previous && invalidatesAppState(e))) {
      void queryClient.invalidateQueries({ queryKey: APP_STATE_KEY });
    }
  }, [state.lastId, state.timeline, queryClient]);
}

/** Estado do NICKEL (/api/state): atualiza a cada 10 s (e, via useAppStateSync, quando algo relevante acontece). */
export function useAppState() {
  return useQuery({ queryKey: APP_STATE_KEY, queryFn: getState, refetchInterval: APP_STATE_REFETCH_MS });
}
