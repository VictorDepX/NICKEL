import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const REDUCED = "(prefers-reduced-motion: reduce)";

/** Segue `prefers-reduced-motion: reduce`. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia(REDUCED).matches);
  useEffect(() => {
    const mql = window.matchMedia(REDUCED);
    const onChange = () => setReduced(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

export const PHASE_COLORS: Record<string, string> = {
  idle: "var(--phase-idle)",
  listening: "var(--phase-listening)",
  transcribing: "var(--phase-listening)",
  thinking: "var(--phase-thinking)",
  routing: "var(--phase-thinking)",
  prompting: "var(--phase-thinking)",
  tool: "var(--phase-tool)",
  confirming: "var(--phase-tool)",
  answering: "var(--phase-answering)",
  speaking: "var(--phase-speaking)",
  error: "var(--phase-error)",
};

export const PHASE_LABELS_PT: Record<string, string> = {
  idle: "Ocioso",
  routing: "Roteando",
  prompting: "Montando prompt",
  thinking: "Pensando",
  answering: "Respondendo",
  tool: "Executando ferramenta",
  confirming: "Aguardando confirmação",
  listening: "Ouvindo",
  transcribing: "Transcrevendo",
  speaking: "Falando",
  error: "Erro",
};

interface OrbProps {
  size?: number;
  phase?: string;
  className?: string;
}

/** Esfera do NICKEL: o GIF aprovado com mistura `screen` e, fora do ocioso, um anel girando na cor da fase. */
export function Orb({ size = 120, phase = "idle", className }: OrbProps) {
  const label = PHASE_LABELS_PT[phase] ?? phase;
  const color = PHASE_COLORS[phase] ?? PHASE_COLORS.idle;
  // Um GIF não para por CSS: com movimento reduzido, troca por um disco estático.
  const reduced = usePrefersReducedMotion();
  return (
    <div
      role="img"
      aria-label={`NICKEL: ${label}`}
      className={cn("relative block shrink-0 rounded-full", className)}
      style={{ width: size, height: size }}
    >
      <div className="absolute inset-0 overflow-hidden rounded-full">
        {reduced ? (
          <span
            data-testid="orb-static"
            aria-hidden="true"
            className="absolute inset-0 rounded-full"
            style={{ background: "radial-gradient(circle at 38% 34%, #d9eeff 0%, #7ab8e8 32%, #2b4d6e 68%, #0c1622 100%)" }}
          />
        ) : (
          <img
            src={`${import.meta.env.BASE_URL}esfera.gif`}
            alt=""
            aria-hidden="true"
            draggable={false}
            className="pointer-events-none absolute top-1/2 left-1/2 max-w-none -translate-x-1/2 -translate-y-1/2 mix-blend-screen"
            style={{ width: size * 1.82, height: size * 1.82 }}
          />
        )}
      </div>
      {phase !== "idle" ? (
        <span
          data-testid="orb-ring"
          aria-hidden="true"
          className="pointer-events-none absolute rounded-full border-2 border-transparent"
          style={{
            inset: "-6%",
            borderTopColor: color,
            borderRightColor: color,
            animation: "nk-spin 1.8s linear infinite",
          }}
        />
      ) : null}
    </div>
  );
}
