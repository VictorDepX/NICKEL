import { DownloadIcon } from "lucide-react";
import { runReportUrl, type RunInfoRow } from "@/lib/api";
import { formatDuration, num } from "@/lib/monitor-core";
import { cn } from "@/lib/utils";
import { CARD, CARD_TITLE, HINT, clockTime, short } from "./shared";

interface RunsCardProps {
  runs: RunInfoRow[] | undefined;
  failed: boolean;
  selectedId: string | null;
  liveId: string | null;
  onSelect: (id: string) => void;
  className?: string;
}

/** Execuções recentes: clicar seleciona a execução na linha do tempo; cada uma tem seu relatório. */
export function RunsCard({ runs, failed, selectedId, liveId, onSelect, className }: RunsCardProps) {
  return (
    <section aria-labelledby="runs-title" className={cn(CARD, className)}>
      <h2 id="runs-title" className={CARD_TITLE}>
        Execuções
      </h2>
      {failed && !runs ? (
        <p className={HINT}>Não foi possível carregar as execuções.</p>
      ) : !runs ? (
        <p className={HINT}>Carregando…</p>
      ) : !runs.length ? (
        <p className={HINT}>Nenhuma execução registrada.</p>
      ) : (
        <ul aria-label="Execuções recentes" className="-mx-2 flex flex-col">
          {runs.map((run) => {
            const selected = run.run_id === selectedId;
            return (
              <li key={run.run_id} className="flex items-center gap-1">
                <button
                  type="button"
                  aria-pressed={selected}
                  aria-label={`Ver execução ${short(run.run_id)}`}
                  onClick={() => onSelect(run.run_id)}
                  className={cn(
                    "flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-md whitespace-nowrap px-2 py-1.5 text-left text-[12.5px] hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring",
                    selected && "bg-accent text-accent-foreground hover:bg-accent",
                  )}
                >
                  <span className="font-mono text-foreground">{short(run.run_id)}</span>
                  <span className="hidden font-mono text-[11.5px] text-subtle-foreground sm:inline">{clockTime(run.started_at)}</span>
                  {run.run_id === liveId ? <span className="text-[11.5px] text-ring">ao vivo</span> : null}
                  <span className="ml-auto text-muted-foreground">{num(run.events)} eventos</span>
                  {run.errors ? (
                    <span className="rounded-full border border-destructive/40 bg-destructive/10 px-2 py-px text-[11px] text-destructive-foreground">
                      {num(run.errors)} {run.errors === 1 ? "erro" : "erros"}
                    </span>
                  ) : run.duration_ms != null ? (
                    <span className="font-mono text-[11.5px] text-subtle-foreground">{formatDuration(run.duration_ms)}</span>
                  ) : null}
                </button>
                <a
                  href={runReportUrl(run.run_id)}
                  download=""
                  aria-label={`Baixar relatório da execução ${short(run.run_id)}`}
                  title="Baixar relatório"
                  className="inline-flex size-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring md:size-9"
                >
                  <DownloadIcon aria-hidden="true" className="size-4" />
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
