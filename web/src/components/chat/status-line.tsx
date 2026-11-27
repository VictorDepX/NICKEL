import { useEffect, useState } from "react";
import { PHASE_COLORS } from "@/components/orb";
import { clock } from "@/lib/chat-turn";
import { chatStatus, type MonitorState } from "@/lib/monitor-core";
import { cn } from "@/lib/utils";

/** Relógio que só anda (a cada 1 s) enquanto `running`. */
export function useNow(running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return now;
}

interface StatusLineProps {
  state: MonitorState;
  connected: boolean;
  /** Pedido enviado e o servidor ainda não mandou eventos do turno. */
  sending?: boolean;
  className?: string;
}

/** "O que o NICKEL está fazendo": fase, detalhe e cronômetro, a partir de `chatStatus()`. */
export function StatusLine({ state, connected, sending = false, className }: StatusLineProps) {
  const running = chatStatus(state, 0).active || sending;
  const now = useNow(running);
  const status = chatStatus(state, now);
  const active = status.active || sending;

  const phase = status.active ? status.phase : sending ? "prompting" : status.phase;
  const text = status.active ? status.text : sending ? "Enviando" : status.text;
  const label = `${text}${active ? "…" : ""}${status.active && status.detail ? ` · ${status.detail}` : ""}`;
  const idleDetail = !status.active && !sending && status.detail ? status.detail : "";
  const color = PHASE_COLORS[phase] ?? PHASE_COLORS.idle;

  return (
    <div
      role="status"
      aria-live="polite"
      data-phase={phase}
      className={cn("flex min-h-6 items-center gap-2.5 px-1 text-[12.5px] text-[#e4e4e7]", className)}
    >
      <span
        aria-hidden="true"
        className="inline-block size-2 shrink-0 rounded-full"
        style={{ background: color, animation: active ? "nk-pulse 1.2s ease-in-out infinite" : undefined }}
      />
      <span className={cn("min-w-0 truncate", phase === "error" && "text-destructive-foreground")}>{label}</span>
      {idleDetail ? <span className="hidden min-w-0 truncate text-subtle-foreground sm:inline"> · {idleDetail}</span> : null}
      {!connected ? <span className="shrink-0 text-subtle-foreground"> · reconectando…</span> : null}
      {active && status.elapsedMs != null ? (
        <span className="ml-auto shrink-0 font-mono text-[11.5px] text-subtle-foreground" aria-label="Tempo decorrido">
          {clock(status.elapsedMs)}
        </span>
      ) : null}
    </div>
  );
}
