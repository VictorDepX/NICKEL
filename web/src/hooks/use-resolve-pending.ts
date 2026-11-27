import { useCallback, useRef, useState } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { APP_STATE_KEY } from "@/hooks/use-app-state";
import { PENDING_KEY } from "@/hooks/use-shell-data";
import { cancelPending, confirmPending, type PendingAction } from "@/lib/api";
import { MESSAGES_KEY } from "@/lib/conversa-prefs";

export type PendingDecision = "confirm" | "cancel";
export type ResolveResult = { ok: true; text: string } | { ok: false; error: unknown };

/**
 * Confirma ou recusa uma ação pendente (Conversa, Início e Memória usam o mesmo caminho).
 * A trava é um ref (e não só estado): um clique duplo chega antes de o React desabilitar os botões.
 * A ação sai da lista na hora e `onResult` roda logo em seguida; estado, mensagens e pendentes são revalidados no fim.
 */
export function useResolvePending(extraInvalidate: QueryKey[] = []) {
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);
  const resolving = useRef(false);
  const extra = useRef(extraInvalidate);
  extra.current = extraInvalidate;

  const resolve = useCallback(
    async (id: string, decision: PendingDecision, onResult?: (result: ResolveResult) => void): Promise<void> => {
      if (resolving.current) return;
      resolving.current = true;
      setBusyId(id);
      try {
        const reply = await (decision === "confirm" ? confirmPending(id) : cancelPending(id));
        queryClient.setQueryData<PendingAction[]>(PENDING_KEY, (items) => items?.filter((a) => a.id !== id));
        onResult?.({ ok: true, text: reply.text ?? "" });
      } catch (error) {
        onResult?.({ ok: false, error });
      } finally {
        void queryClient.invalidateQueries({ queryKey: APP_STATE_KEY });
        void queryClient.invalidateQueries({ queryKey: MESSAGES_KEY });
        for (const queryKey of extra.current) void queryClient.invalidateQueries({ queryKey });
        try {
          await queryClient.invalidateQueries({ queryKey: PENDING_KEY });
        } finally {
          resolving.current = false;
          setBusyId(null);
        }
      }
    },
    [queryClient],
  );

  return { resolve, busyId, busy: busyId !== null };
}
