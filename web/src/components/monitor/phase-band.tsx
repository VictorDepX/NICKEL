import { PHASE_COLORS } from "@/components/orb";
import { formatDuration, type RunPhase } from "@/lib/monitor-core";
import { cn } from "@/lib/utils";
import { HINT, PHASE_SHORT } from "./shared";

/** Turnos longos (várias voltas de ferramenta) mostram só as últimas fases, como na faixa antiga. */
const MAX_SEGMENTS = 8;

interface Segment {
  phase: string;
  ms: number;
  open: boolean;
}

/** Fases com duração; a última, ainda aberta, conta até `now` (ou some, se for o "pronto" final). */
export function bandSegments(phases: RunPhase[], now: number, running: boolean): Segment[] {
  const out: Segment[] = [];
  phases.forEach((p, i) => {
    const last = i === phases.length - 1;
    if (last && !running) return; // fase final (pronto/erro) não tem duração
    const ms = p.ms ?? Math.max(0, now - Date.parse(p.at));
    out.push({ phase: p.phase, ms: Number.isFinite(ms) ? ms : 0, open: last });
  });
  return out.slice(-MAX_SEGMENTS);
}

/** Faixa de fases do turno atual, com segmentos proporcionais à duração. */
export function PhaseBand({ phases, now, running }: { phases: RunPhase[]; now: number; running: boolean }) {
  const segments = bandSegments(phases, now, running);
  if (!segments.length) {
    return (
      <div className="flex h-10 items-center rounded-lg border border-dashed border-border-soft px-3">
        <p className={HINT}>Nenhum turno ainda. As fases aparecem aqui enquanto o NICKEL trabalha.</p>
      </div>
    );
  }
  const total = segments.reduce((sum, s) => sum + s.ms, 0) || 1;
  return (
    <ol aria-label="Fases do turno atual" className="flex h-10 w-full gap-1 overflow-hidden">
      {segments.map((s, i) => {
        const color = PHASE_COLORS[s.phase] ?? PHASE_COLORS.idle;
        const label = PHASE_SHORT[s.phase] ?? s.phase;
        const duration = s.ms >= 1000 ? formatDuration(s.ms) : null;
        return (
          <li
            key={`${s.phase}-${i}`}
            data-phase={s.phase}
            aria-current={s.open ? "step" : undefined}
            title={`${label} · ${formatDuration(s.ms)}`}
            className={cn(
              "flex min-w-[52px] items-center truncate md:min-w-fit rounded-md border px-2 text-xs whitespace-nowrap",
              s.open && "animate-pulse motion-reduce:animate-none",
            )}
            style={{
              flexGrow: s.ms / total,
              flexBasis: 0,
              color,
              background: `color-mix(in srgb, ${color} 14%, transparent)`,
              borderColor: `color-mix(in srgb, ${color} 30%, transparent)`,
            }}
          >
            <span className="truncate">
              {label}
              {duration ? <span className="font-mono text-[11px] opacity-80"> {duration}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
