import { useState } from "react";
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Toggle } from "@/components/ui/toggle";
import {
  eventHint,
  fakeActionLabel,
  filterTimeline,
  formatDuration,
  num,
  runSummary,
  type AuditEvent,
  type Catalog,
} from "@/lib/monitor-core";
import { cn } from "@/lib/utils";
import { CARD, CARD_TITLE, HINT, clip, clockTime, short } from "./shared";

export const EVENTS_SHOWN = 200;

const STATUS_LABEL: Record<string, string> = { running: "Em andamento", done: "Concluído", error: "Erro" };

const STATUS_CLASS: Record<string, string> = {
  error: "border-destructive/40 bg-destructive/10 text-destructive-foreground",
  ok: "border-success/30 bg-success/10 text-success",
  done: "border-success/30 bg-success/10 text-success",
  skipped: "border-warning/30 bg-warning/10 text-warning-foreground",
  cancelled: "border-warning/30 bg-warning/10 text-warning-foreground",
  pending: "border-warning/30 bg-warning/10 text-warning-foreground",
};
const STATUS_NEUTRAL = "border-border bg-muted text-muted-foreground";

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn("shrink-0 rounded-full border px-2 py-px font-mono text-[11px]", STATUS_CLASS[status] ?? STATUS_NEUTRAL)}>
      {status}
    </span>
  );
}

function detailJson(e: AuditEvent): string {
  try {
    return JSON.stringify(e.detail ?? {}, null, 2);
  } catch {
    return String(e.detail);
  }
}

/** Linha de evento; o estado aberto/fechado é do próprio item e sobrevive aos eventos ao vivo. */
function EventRow({ event }: { event: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const hint = clip(eventHint(event));
  return (
    <li data-event-id={event.id} data-status={event.status}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="grid min-h-11 w-full grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-x-3 rounded-md px-2 py-1.5 text-left text-[12.5px] hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring md:min-h-9">
          <span className="flex items-center gap-1 font-mono text-[11.5px] text-subtle-foreground">
            <ChevronRightIcon aria-hidden="true" className={cn("size-3 transition-transform", open && "rotate-90")} />
            <time dateTime={event.at}>{clockTime(event.at)}</time>
          </span>
          <span className="font-mono text-foreground">
            {event.kind}/{event.name}
          </span>
          <span className="truncate text-muted-foreground">
            {hint}
            {event.duration_ms != null ? <span className="font-mono text-subtle-foreground"> · {formatDuration(event.duration_ms)}</span> : null}
          </span>
          <StatusBadge status={event.status} />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="mx-2 mb-2 max-h-[320px] overflow-auto rounded-lg bg-black p-3 font-mono text-[11.5px] whitespace-pre-wrap text-[#d4d4d8]">
            {detailJson(event)}
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}

type Pair = [string, string | null | undefined];

function Facts({ pairs, className }: { pairs: Pair[]; className?: string }) {
  const shown = pairs.filter(([, v]) => v != null && v !== "");
  if (!shown.length) return null;
  return (
    <dl className={cn("grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4", className)}>
      {shown.map(([term, value]) => (
        <div key={term} className="min-w-0">
          <dt className="text-[11.5px] text-subtle-foreground">{term}</dt>
          <dd className="truncate text-[13px] text-foreground" title={String(value)}>
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Resumo do turno (fatos básicos à vista; detalhes técnicos e ferramentas num recolhível). */
function TurnSummary({ events, runId }: { events: AuditEvent[]; runId: string | null }) {
  const s = runSummary(events);
  if (s.status === "empty") return null;
  const backend = s.requestedBackend && s.requestedBackend !== s.backend ? `${s.backend} (pedido: ${s.requestedBackend})` : s.backend;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border-soft bg-background/40 p-3">
      <Facts
        pairs={[
          ["Estado", STATUS_LABEL[s.status]],
          ["Canal", s.channel],
          ["Área", s.workspace],
          ["Duração", s.status === "running" ? "em andamento" : formatDuration(s.durationMs)],
          ["Passos", s.steps != null ? num(s.steps) : null],
          ["Ferramentas", num(s.toolCalls.length)],
          ["Resposta", s.replyChars != null ? `${num(s.replyChars)} caracteres` : null],
          ["Erros", num(s.errors)],
        ]}
      />
      {fakeActionLabel(s) ? <p className="text-[12.5px] text-warning-foreground">Aviso: {fakeActionLabel(s)}</p> : null}
      {s.error ? <p className="text-[12.5px] text-destructive-foreground">Motivo do erro: {clip(s.error, 300)}</p> : null}
      <Collapsible>
        <CollapsibleTrigger className="group inline-flex min-h-11 items-center gap-1 rounded-md text-[12.5px] text-ring hover:underline focus-visible:outline-2 focus-visible:outline-ring md:min-h-7">
          Detalhes técnicos
          <ChevronDownIcon aria-hidden="true" className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        <CollapsibleContent className="flex flex-col gap-3 pt-2">
          <Facts
            pairs={[
              ["Execução", runId],
              ["Comando", s.command],
              ["Modelo", s.model],
              ["Backend", backend],
              ["Chamadas ao modelo", num(s.llmCalls)],
              ["Mensagens no prompt", s.messages != null ? num(s.messages) : null],
              ["Histórico", s.history != null ? num(s.history) : null],
              ["Ferramentas disponíveis", s.tools != null ? num(s.tools) : null],
              ["Prompt do sistema", s.systemChars != null ? `${num(s.systemChars)} caracteres` : null],
              ["Tokens estimados do prompt", s.estTokens != null ? num(s.estTokens) : null],
              ["Tokens do prompt", s.promptTokens != null ? num(s.promptTokens) : null],
              ["Tokens gerados", s.completionTokens != null ? num(s.completionTokens) : null],
              ["Tokens/s", s.tokensPerSecond != null ? num(s.tokensPerSecond, 1) : null],
              ["Entrada", s.inputChars != null ? `${num(s.inputChars)} caracteres` : null],
            ]}
          />
          {s.toolCalls.length ? (
            <ul aria-label="Ferramentas usadas" className="flex flex-col gap-1 text-[12.5px]">
              {s.toolCalls.map((t, i) => (
                <li key={`${t.name}-${i}`} className="flex flex-wrap items-baseline gap-x-2">
                  <span className={cn("font-mono", t.ok ? "text-success" : "text-destructive-foreground")}>
                    {t.ok ? "ok" : "erro"} {t.name}
                  </span>
                  {t.durationMs != null ? <span className="font-mono text-subtle-foreground">{formatDuration(t.durationMs)}</span> : null}
                  {t.summary ? <span className="text-muted-foreground">{clip(t.summary)}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

interface TimelineCardProps {
  runId: string | null;
  events: AuditEvent[];
  catalog: Catalog;
  live: boolean;
  loading: boolean;
  failed: boolean;
  onlyErrors: boolean;
  hiddenKinds: ReadonlySet<string>;
  onToggleKind: (kind: string) => void;
  className?: string;
}

/** Linha do tempo da execução selecionada, com resumo do turno e filtros por tipo. */
export function TimelineCard({
  runId,
  events,
  catalog,
  live,
  loading,
  failed,
  onlyErrors,
  hiddenKinds,
  onToggleKind,
  className,
}: TimelineCardProps) {
  const ordered = [...events].sort((a, b) => a.id - b.id);
  const kinds = [...new Set([...Object.keys(catalog.kinds ?? {}), ...ordered.map((e) => e.kind)])].sort();
  const visibleKinds = hiddenKinds.size ? new Set(kinds.filter((k) => !hiddenKinds.has(k))) : null;
  const filtered = filterTimeline(ordered, { kinds: visibleKinds, onlyErrors });
  const shown = filtered.slice(-EVENTS_SHOWN);

  let empty: string | null = null;
  if (!runId) empty = "Nenhuma execução ainda. Envie uma mensagem para acompanhar aqui.";
  else if (failed) empty = "Não foi possível carregar os eventos desta execução.";
  else if (loading) empty = "Carregando eventos…";
  else if (!ordered.length) empty = "Nenhum evento nesta execução.";
  else if (!filtered.length) empty = "Nada com esses filtros.";

  return (
    <section aria-labelledby="timeline-title" className={cn(CARD, className)}>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="timeline-title" className={CARD_TITLE}>
          Linha do tempo
        </h2>
        {runId ? (
          <span className={HINT}>
            execução <span className="font-mono">{short(runId)}</span>
            {live ? " · ao vivo" : ""}
          </span>
        ) : null}
      </header>

      {!loading ? <TurnSummary events={ordered} runId={runId} /> : null}

      {kinds.length ? (
        <div role="group" aria-label="Filtrar por tipo de evento" className="flex flex-wrap gap-1.5">
          {kinds.map((kind) => (
            <Toggle
              key={kind}
              size="sm"
              pressed={!hiddenKinds.has(kind)}
              onPressedChange={() => onToggleKind(kind)}
              title={catalog.kinds?.[kind]?.description}
              className="h-auto min-h-8 rounded-full border border-input px-2.5 font-mono text-[11.5px] text-subtle-foreground line-through hover:bg-muted data-[state=on]:border-[#2e3a47] data-[state=on]:bg-accent data-[state=on]:text-accent-foreground data-[state=on]:no-underline"
            >
              {kind}
            </Toggle>
          ))}
        </div>
      ) : null}

      {empty ? (
        <p className={HINT}>{empty}</p>
      ) : (
        <>
          {filtered.length > shown.length ? (
            <p className={HINT}>
              Mostrando os últimos {shown.length} de {filtered.length}.
            </p>
          ) : null}
          <ol aria-label="Eventos" className="-mx-2 flex flex-col">
            {shown.map((e) => (
              <EventRow key={e.id} event={e} />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
