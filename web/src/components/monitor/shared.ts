// Peças comuns dos cartões do Monitor.

export const CARD = "flex min-w-0 flex-col gap-3 rounded-xl border border-border-soft bg-card p-4";
export const CARD_TITLE = "text-sm font-semibold tracking-tight text-foreground";
export const HINT = "text-[12.5px] text-subtle-foreground";

/** Botão/link secundário com alvo de 44 px no toque e 36 px com mouse. */
export const SECONDARY_BUTTON =
  "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-[10px] border border-input px-3.5 text-[13px] text-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring aria-disabled:pointer-events-none aria-disabled:opacity-50 md:min-h-9";

export const short = (id: string | null | undefined) => (id ? String(id).slice(0, 8) : "—");

export function clip(text: unknown, max = 120): string {
  const s = String(text ?? "").replace(/\s+/g, " ").trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

export function clockTime(value: string | number | Date): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Rótulos curtos da faixa de fases. */
export const PHASE_SHORT: Record<string, string> = {
  idle: "pronto",
  routing: "rota",
  prompting: "lendo",
  thinking: "pensando",
  tool: "ferramenta",
  confirming: "confirmação",
  answering: "escrevendo",
  listening: "ouvindo",
  transcribing: "transcrevendo",
  speaking: "falando",
  error: "erro",
};
