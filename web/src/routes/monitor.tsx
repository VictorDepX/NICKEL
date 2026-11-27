import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { DownloadIcon } from "lucide-react";
import { PHASE_COLORS, PHASE_LABELS_PT } from "@/components/orb";
import { MemoryCard } from "@/components/monitor/memory-card";
import { PhaseBand } from "@/components/monitor/phase-band";
import { ReasoningCard } from "@/components/monitor/reasoning-card";
import { RunsCard } from "@/components/monitor/runs-card";
import { SECONDARY_BUTTON } from "@/components/monitor/shared";
import { TimelineCard } from "@/components/monitor/timeline-card";
import { useNow } from "@/components/chat/status-line";
import { Toggle } from "@/components/ui/toggle";
import { useEvents } from "@/hooks/use-events";
import { getRun, getRuns, runReportUrl } from "@/lib/api";
import { clock } from "@/lib/chat-turn";
import { chatStatus, runPhases } from "@/lib/monitor-core";
import { cn } from "@/lib/utils";

export const RUNS_KEY = ["runs"] as const;
export const RUN_KEY = ["run"] as const;

/** Monitor: fase do turno, memória, raciocínio ao vivo, linha do tempo da execução e execuções recentes. */
export default function Monitor() {
  const { state, catalog, connected } = useEvents();
  const queryClient = useQueryClient();

  const running = chatStatus(state, 0).active;
  const now = useNow(running);
  const status = chatStatus(state, now);
  const phaseLabel = state.phase === "idle" ? "Pronto" : (catalog.labels?.[state.phase] ?? PHASE_LABELS_PT[state.phase] ?? state.phase);
  const phaseColor = PHASE_COLORS[state.phase] ?? PHASE_COLORS.idle;

  const currentEvents = useMemo(
    () => (state.runId ? state.timeline.filter((e) => e.run_id === state.runId) : []),
    [state.timeline, state.runId],
  );
  const phases = useMemo(() => runPhases(currentEvents, catalog), [currentEvents, catalog]);

  // Execuções: recarrega quando um turno começa ou termina (com folga para o servidor gravar).
  const runs = useQuery({ queryKey: RUNS_KEY, queryFn: () => getRuns(20), refetchInterval: 30_000 });
  const lastTurnEvent = useMemo(() => {
    for (let i = state.timeline.length - 1; i >= 0; i--) if (state.timeline[i].kind === "turn") return state.timeline[i].id;
    return 0;
  }, [state.timeline]);
  useEffect(() => {
    if (!lastTurnEvent) return;
    const timer = setTimeout(() => void queryClient.invalidateQueries({ queryKey: RUNS_KEY }), 400);
    return () => clearTimeout(timer);
  }, [lastTurnEvent, queryClient]);

  // Seleção: null acompanha o turno atual (ao vivo); um id fixa uma execução antiga.
  const [selected, setSelected] = useState<string | null>(null);
  const activeRun = selected ?? state.runId ?? runs.data?.[0]?.run_id ?? null;
  const live = activeRun != null && activeRun === state.runId;
  const fetched = useQuery({
    queryKey: [...RUN_KEY, activeRun],
    queryFn: () => getRun(activeRun as string),
    enabled: activeRun != null && !live,
  });
  const events = live ? currentEvents : (fetched.data ?? []);

  const [onlyErrors, setOnlyErrors] = useState(false);
  const [hiddenKinds, setHiddenKinds] = useState<ReadonlySet<string>>(() => new Set());
  const toggleKind = (kind: string) =>
    setHiddenKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  return (
    <section aria-label="Monitor" className="mx-auto flex w-full max-w-[1280px] flex-col gap-4 px-4 py-6 md:px-8">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Monitor</h1>
        <span
          role="status"
          aria-live="polite"
          data-phase={state.phase}
          className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-[12.5px] text-foreground"
        >
          <span
            aria-hidden="true"
            className="size-2 rounded-full"
            style={{ background: phaseColor, animation: status.active ? "nk-pulse 1.2s ease-in-out infinite" : undefined }}
          />
          {phaseLabel}
          {status.active && status.elapsedMs != null ? <span className="font-mono text-subtle-foreground">· {clock(status.elapsedMs)}</span> : null}
          {!connected ? <span className="text-subtle-foreground">· reconectando…</span> : null}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Toggle
            pressed={onlyErrors}
            onPressedChange={setOnlyErrors}
            className={cn(
              SECONDARY_BUTTON,
              "h-auto data-[state=on]:border-destructive/40 data-[state=on]:bg-destructive/10 data-[state=on]:text-destructive-foreground",
            )}
          >
            Só erros
          </Toggle>
          {activeRun ? (
            <a href={runReportUrl(activeRun)} download="" className={SECONDARY_BUTTON}>
              <DownloadIcon aria-hidden="true" className="size-4" />
              Baixar relatório
            </a>
          ) : (
            <span aria-disabled="true" className={SECONDARY_BUTTON}>
              <DownloadIcon aria-hidden="true" className="size-4" />
              Baixar relatório
            </span>
          )}
        </div>
      </header>

      <PhaseBand phases={phases} now={now} running={running} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <MemoryCard className="lg:col-span-7" />
        <ReasoningCard key={state.runId ?? "none"} state={state} phases={phases} className="lg:col-span-5" />
        <TimelineCard
          className="lg:col-span-7"
          runId={activeRun}
          events={events}
          catalog={catalog}
          live={live}
          loading={!live && fetched.isPending && activeRun != null}
          failed={!live && fetched.isError}
          onlyErrors={onlyErrors}
          hiddenKinds={hiddenKinds}
          onToggleKind={toggleKind}
        />
        <RunsCard
          className="lg:col-span-5 lg:self-start"
          runs={runs.data}
          failed={runs.isError}
          selectedId={activeRun}
          liveId={state.runId}
          onSelect={(id) => setSelected(id === state.runId ? null : id)}
        />
      </div>
    </section>
  );
}
