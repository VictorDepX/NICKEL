import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPending, getReminders, getSystemMemory, getWorkspaces, type Reminder, type SystemMemorySample } from "@/lib/api";
import { useEvents } from "./use-events";

export const REMINDERS_KEY = ["reminders"] as const;
export const WORKSPACES_KEY = ["workspaces"] as const;
export const PENDING_KEY = ["pending"] as const;
export const SYSTEM_MEMORY_KEY = ["system-memory"] as const;
export const CONTEXT_WINDOW = 16384;

export function useReminders() {
  return useQuery({ queryKey: REMINDERS_KEY, queryFn: getReminders, refetchInterval: 30_000 });
}

export function useWorkspaces() {
  return useQuery({ queryKey: WORKSPACES_KEY, queryFn: getWorkspaces });
}

export function usePending() {
  return useQuery({ queryKey: PENDING_KEY, queryFn: getPending, refetchInterval: 10_000 });
}

/** Último ponto de /api/system/memory (atualiza a cada 5 s); `null` sem amostra. */
export function useLatestMemory(): SystemMemorySample | null {
  const { data } = useQuery({ queryKey: SYSTEM_MEMORY_KEY, queryFn: getSystemMemory, refetchInterval: 5000 });
  return data?.available && data.samples.length ? data.samples[data.samples.length - 1] : null;
}

/** Lembrete mais próximo (a rota só devolve os agendados). */
export function nextReminder(reminders: Reminder[] | undefined): Reminder | null {
  if (!reminders?.length) return null;
  return reminders.reduce((soonest, r) => (Date.parse(r.due_at) < Date.parse(soonest.due_at) ? r : soonest));
}

export interface LlmUsage {
  tokensPerSecond: number | null;
  promptTokens: number | null;
}

/** Números do último `llm/done` na linha do tempo (o estado `lastLlm` zera a cada turno novo). */
export function useLastLlm(): LlmUsage | null {
  const { state } = useEvents();
  return useMemo(() => {
    for (let i = state.timeline.length - 1; i >= 0; i--) {
      const e = state.timeline[i];
      if (e.kind === "llm" && e.status === "done") {
        return {
          tokensPerSecond: typeof e.detail.tokens_per_second === "number" ? e.detail.tokens_per_second : null,
          promptTokens: typeof e.detail.prompt_tokens === "number" ? e.detail.prompt_tokens : null,
        };
      }
    }
    return null;
  }, [state.timeline]);
}
