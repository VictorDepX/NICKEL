import type { ReactNode } from "react";

const SIZE = 50;
const RADIUS = 23;
const STROKE = 5;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const TRACK = "#202127";

export type RamLevel = "ok" | "warning" | "destructive";

/** Anel de RAM: ok < 75 %, atenção ≥ 75 %, crítico ≥ 92 %. */
export function ramLevel(percent: number): RamLevel {
  if (percent >= 92) return "destructive";
  if (percent >= 75) return "warning";
  return "ok";
}

export const RAM_COLOR: Record<RamLevel, string> = {
  ok: "var(--success)",
  warning: "var(--warning)",
  destructive: "var(--destructive)",
};

interface FrameProps {
  label: string;
  caption?: string;
  ariaLabel: string;
  children: ReactNode;
  compact?: boolean;
}

function Frame({ label, caption, ariaLabel, children, compact }: FrameProps) {
  return (
    <div className="flex flex-col items-center gap-1 text-[11.5px] text-muted-foreground">
      <div role="img" aria-label={ariaLabel} className={compact ? "relative size-10" : "relative size-[50px]"}>
        <svg width="100%" height="100%" viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90" aria-hidden="true">
          <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke={TRACK} strokeWidth={STROKE} />
          {children}
        </svg>
        <span className="absolute inset-0 grid place-items-center font-mono text-[11px] text-foreground">{label}</span>
      </div>
      {caption ? <span>{caption}</span> : null}
    </div>
  );
}

interface RingGaugeProps {
  /** 0 a 100; `null` mostra o anel vazio e "—". */
  percent: number | null;
  color: string;
  caption?: string;
  ariaLabel: string;
  /** Versão de 40 px para o cabeçalho no celular. */
  compact?: boolean;
}

export function RingGauge({ percent, color, caption, ariaLabel, compact }: RingGaugeProps) {
  const value = percent === null ? 0 : Math.min(100, Math.max(0, percent));
  return (
    <Frame label={percent === null ? "—" : `${Math.round(value)}%`} caption={caption} ariaLabel={ariaLabel} compact={compact}>
      <circle
        data-arc
        cx={SIZE / 2}
        cy={SIZE / 2}
        r={RADIUS}
        fill="none"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinecap="round"
        strokeDasharray={`${(CIRCUMFERENCE * value) / 100} ${CIRCUMFERENCE}`}
      />
    </Frame>
  );
}

interface SplitRingProps {
  ok: number;
  total: number;
  caption?: string;
  ariaLabel: string;
}

/** Anel dividido: verde para o que está ok, vermelho para o resto. */
export function SplitRing({ ok, total, caption, ariaLabel }: SplitRingProps) {
  const okLength = total > 0 ? (CIRCUMFERENCE * ok) / total : 0;
  const gap = ok > 0 && ok < total ? 3 : 0;
  return (
    <Frame label={`${ok}/${total}`} caption={caption} ariaLabel={ariaLabel}>
      {total > 0 && ok < total ? (
        <circle
          data-arc="bad"
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="var(--destructive)"
          strokeWidth={STROKE}
          strokeDasharray={`${CIRCUMFERENCE - okLength - gap} ${CIRCUMFERENCE}`}
          strokeDashoffset={-(okLength + gap)}
        />
      ) : null}
      {ok > 0 ? (
        <circle
          data-arc="ok"
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="var(--success)"
          strokeWidth={STROKE}
          strokeDasharray={`${Math.max(okLength - gap, 0)} ${CIRCUMFERENCE}`}
        />
      ) : null}
    </Frame>
  );
}
