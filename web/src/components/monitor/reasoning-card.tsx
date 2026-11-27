import { useLayoutEffect, useRef, useState } from "react";
import { ChevronDownIcon } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { formatDuration, num, reasoningSteps, reasoningView, type MonitorState, type RunPhase } from "@/lib/monitor-core";
import { cn } from "@/lib/utils";
import { CARD, CARD_TITLE, HINT, PHASE_SHORT } from "./shared";

const EMPTY_TEXT: Record<string, string> = {
  empty: "Nenhum turno ainda.",
  waiting: "Aguardando o modelo…",
  off: "Sem raciocínio expandido (pensar desligado).",
  skipped: "O modelo não raciocinou neste passo (pensar ligado).",
  none: "Sem raciocínio neste turno.",
};

/** Trecho final ao vivo: acompanha o fim só se o usuário já estava perto dele. */
function Tail({ text }: { text: string }) {
  const ref = useRef<HTMLPreElement>(null);
  const nearBottom = useRef(true);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && nearBottom.current) el.scrollTop = el.scrollHeight;
  }, [text]);
  return (
    <pre
      ref={ref}
      tabIndex={0}
      aria-label="Trecho final do raciocínio"
      onScroll={(e) => {
        const el = e.currentTarget;
        nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
      className="max-h-[260px] min-h-[140px] overflow-auto rounded-lg border border-border-soft bg-black p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-[#d4d4d8] focus-visible:outline-2 focus-visible:outline-ring"
    >
      {text}
    </pre>
  );
}

/** Raciocínio ao vivo do turno atual. Remonte com `key={runId}` para voltar ao passo mais recente. */
export function ReasoningCard({ state, phases, className }: { state: MonitorState; phases: RunPhase[]; className?: string }) {
  const [picked, setPicked] = useState<number | null>(null);
  const steps = reasoningSteps(state);
  const view = reasoningView(state);
  const has = view === "reasoning";
  const chosen = steps.find((s) => s.step === picked);
  const r = chosen ?? state.reasoning;
  const shown = chosen ? chosen.step : steps.length ? steps[steps.length - 1].step : null;
  const tail = has ? (r.active ? r.tail : r.tail || (r.final || "").slice(-600)) : "";
  const tps = state.lastLlm?.tokensPerSecond;
  const stats = [
    `${num(r.chars)} caracteres`,
    `~${num(r.tokens)} tokens`,
    tps != null ? `${num(tps, 1)} tok/s` : null,
  ].filter(Boolean).join(" · ");

  return (
    <section aria-labelledby="reasoning-title" data-view={view} className={cn(CARD, className)}>
      <header className="flex items-center justify-between gap-2">
        <h2 id="reasoning-title" className={CARD_TITLE}>
          Raciocínio ao vivo
        </h2>
        {has ? (
          <span className={cn("text-xs", r.active ? "text-phase-thinking" : "text-subtle-foreground")}>
            {r.active ? "pensando…" : "concluído"}
          </span>
        ) : null}
      </header>

      {steps.length > 1 ? (
        <div role="group" aria-label="Passos com raciocínio" className="flex flex-wrap gap-1.5">
          {steps.map((s) => (
            <button
              key={s.step}
              type="button"
              aria-pressed={s.step === shown}
              onClick={() => setPicked(s.step === steps[steps.length - 1].step ? null : s.step)}
              className="min-h-8 rounded-full border border-input px-2.5 text-xs text-muted-foreground hover:bg-muted aria-pressed:border-[#2e3a47] aria-pressed:bg-accent aria-pressed:text-accent-foreground"
            >
              passo {s.step}
            </button>
          ))}
        </div>
      ) : null}

      {has ? (
        <>
          {r.headline ? <p className="text-[13px] text-foreground">{r.headline}</p> : null}
          <Tail text={tail} />
          <p className="font-mono text-[11.5px] text-subtle-foreground">{stats}</p>
          {!r.active && r.final ? (
            <Collapsible>
              <CollapsibleTrigger className="group inline-flex min-h-11 items-center gap-1 rounded-md text-[12.5px] text-ring hover:underline focus-visible:outline-2 focus-visible:outline-ring md:min-h-7">
                Ver completo
                <ChevronDownIcon aria-hidden="true" className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent className="pt-2">
                <pre className="max-h-[420px] overflow-auto rounded-lg bg-black p-3 font-mono text-[12px] whitespace-pre-wrap text-[#d4d4d8]">
                  {r.final}
                </pre>
              </CollapsibleContent>
            </Collapsible>
          ) : null}
        </>
      ) : (
        <div className="flex min-h-[140px] flex-col gap-2 rounded-lg border border-border-soft bg-black p-3">
          <p className={HINT}>{EMPTY_TEXT[view] ?? ""}</p>
          {phases.length ? (
            <ol aria-label="Fases do turno" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
              {phases.map((p, i) => (
                <li key={`${p.phase}-${i}`}>
                  {PHASE_SHORT[p.phase] ?? p.phase}
                  {p.ms != null ? <span className="font-mono text-subtle-foreground"> {formatDuration(p.ms)}</span> : null}
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      )}
    </section>
  );
}
