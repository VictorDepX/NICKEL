"use client";

// AI Elements `tool`, adaptado ao NICKEL: estado do evento de auditoria (tool/start → ok | erro),
// rótulos em português e JSON em <pre> simples (sem o code-block/shiki do registro).
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { CheckCircleIcon, ChevronDownIcon, ClockIcon, WrenchIcon, XCircleIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

export type ToolState = "running" | "ok" | "error";

export type ToolProps = ComponentProps<typeof Collapsible>;

export const Tool = ({ className, ...props }: ToolProps) => (
  <Collapsible
    className={cn("group not-prose w-full overflow-hidden rounded-lg border border-[#2a2418] bg-[#121009]", className)}
    {...props}
  />
);

const LABELS: Record<ToolState, string> = { running: "executando", ok: "ok", error: "erro" };

const ICONS: Record<ToolState, ReactNode> = {
  running: <ClockIcon className="size-3 animate-pulse" />,
  ok: <CheckCircleIcon className="size-3" />,
  error: <XCircleIcon className="size-3" />,
};

const BADGE_CLASSES: Record<ToolState, string> = {
  running: "bg-phase-tool/12 text-phase-tool",
  ok: "bg-success/12 text-[#86efac]",
  error: "bg-destructive/12 text-destructive-foreground",
};

export const ToolStatusBadge = ({ state }: { state: ToolState }) => (
  <Badge className={cn("h-[22px] gap-1.5 rounded-md px-2 font-mono text-xs", BADGE_CLASSES[state])} variant="secondary">
    {ICONS[state]}
    {LABELS[state]}
  </Badge>
);

export type ToolHeaderProps = ComponentProps<typeof CollapsibleTrigger> & {
  name: string;
  state: ToolState;
  /** Duração ou outro detalhe curto, à direita do nome. */
  hint?: string;
};

export const ToolHeader = ({ className, name, state, hint, ...props }: ToolHeaderProps) => (
  <CollapsibleTrigger
    className={cn("flex min-h-11 w-full items-center gap-2 px-3 py-2 text-left text-[12.5px]", className)}
    {...props}
  >
    <WrenchIcon className="size-4 shrink-0 text-phase-tool" aria-hidden="true" />
    <span className="min-w-0 truncate font-mono text-foreground">{name}</span>
    <ToolStatusBadge state={state} />
    {hint ? <span className="ml-auto shrink-0 font-mono text-[11.5px] text-subtle-foreground">{hint}</span> : null}
    <ChevronDownIcon
      aria-hidden="true"
      className={cn(
        "size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180",
        hint ? "" : "ml-auto",
      )}
    />
  </CollapsibleTrigger>
);

export type ToolContentProps = ComponentProps<typeof CollapsibleContent>;

export const ToolContent = ({ className, ...props }: ToolContentProps) => (
  <CollapsibleContent
    className={cn(
      "grid gap-2 px-3 pb-3 outline-none sm:grid-cols-2",
      "data-[state=closed]:fade-out-0 data-[state=closed]:animate-out data-[state=open]:animate-in",
      className,
    )}
    {...props}
  />
);

const asText = (value: unknown) => (typeof value === "string" ? value : JSON.stringify(value, null, 2));

const Pre = ({ children, className }: { children: string; className?: string }) => (
  <pre
    className={cn(
      "m-0 max-h-64 overflow-auto rounded-md bg-black p-2.5 font-mono text-xs leading-normal break-words whitespace-pre-wrap text-[#d4d4d8]",
      className,
    )}
  >
    {children}
  </pre>
);

export type ToolInputProps = ComponentProps<"div"> & { input: unknown };

export const ToolInput = ({ className, input, ...props }: ToolInputProps) => (
  <div className={cn("min-w-0 space-y-1", className)} {...props}>
    <h4 className="text-[11px] tracking-[.12em] text-subtle-foreground uppercase">Argumentos</h4>
    <Pre>{input === undefined ? "—" : asText(input)}</Pre>
  </div>
);

export type ToolOutputProps = ComponentProps<"div"> & { output?: unknown; errorText?: string | null };

export const ToolOutput = ({ className, output, errorText, ...props }: ToolOutputProps) => {
  if (output == null && !errorText) return null;
  return (
    <div className={cn("min-w-0 space-y-1", className)} {...props}>
      <h4 className="text-[11px] tracking-[.12em] text-subtle-foreground uppercase">{errorText ? "Erro" : "Resultado"}</h4>
      <Pre className={errorText ? "text-destructive-foreground" : undefined}>{errorText || asText(output)}</Pre>
    </div>
  );
};
