import { cn } from "@/lib/utils";
import type { Level } from "@/lib/api";

const COLORS: Record<Level, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  bad: "bg-destructive",
};

const LABELS: Record<Level, string> = { ok: "ok", warn: "atenção", bad: "fora" };

/** Ponto de status. O nível também vai em texto oculto, para não depender só da cor. */
export function StatusDot({ level, className }: { level: Level; className?: string }) {
  return (
    <span className={cn("inline-block size-2 shrink-0 rounded-full", COLORS[level], className)}>
      <span className="sr-only">{LABELS[level]}</span>
    </span>
  );
}
