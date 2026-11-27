import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useAppState } from "@/hooks/use-app-state";
import {
  CONTEXT_WINDOW,
  nextReminder,
  useLastLlm,
  useLatestMemory,
  usePending,
  useReminders,
} from "@/hooks/use-shell-data";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { RAM_COLOR, RingGauge, SplitRing, ramLevel } from "@/components/ring-gauge";
import { StatusDot } from "@/components/status-dot";
import { cn } from "@/lib/utils";

const GB = 1024 ** 3;
const gb = (bytes: number) => (bytes / GB).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

const panel = "rounded-[24px] border border-sidebar-border bg-popover shadow-lg";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-[14px] border border-sidebar-border bg-card p-3">
      <h3 className="mb-2 text-[11px] tracking-[0.12em] text-subtle-foreground uppercase">{title}</h3>
      {children}
    </section>
  );
}

/** Cápsula de recursos: anéis de RAM, contexto e conexões; expande para um painel de 300 px. */
export function ResourceCapsule({ className, inSheet = false }: { className?: string; inSheet?: boolean }) {
  const [open, setOpen] = useState(false);
  const { data: appState } = useAppState();
  const { data: reminders } = useReminders();
  const { data: pending } = usePending();
  const memory = useLatestMemory();
  const llm = useLastLlm();

  const connectors = appState?.connectors ?? [];
  const okCount = connectors.filter((c) => c.level === "ok").length;
  const ramPercent = memory && memory.total > 0 ? (memory.used / memory.total) * 100 : null;
  const ramLvl = ramPercent === null ? "ok" : ramLevel(ramPercent);
  const contextPercent =
    llm?.promptTokens != null ? Math.min(100, (llm.promptTokens / CONTEXT_WINDOW) * 100) : null;
  const next = nextReminder(reminders);

  if (!open && !inSheet) {
    return (
      <aside aria-label="Recursos" className={cn("flex w-[84px] flex-col items-center gap-4 rounded-[42px] border border-sidebar-border bg-popover pt-4 pb-3 shadow-lg", className)}>
        <RingGauge
          percent={ramPercent}
          color={RAM_COLOR[ramLvl]}
          caption="RAM"
          ariaLabel={ramPercent === null ? "Memória RAM: sem dados" : `Memória RAM: ${Math.round(ramPercent)}%`}
        />
        <RingGauge
          percent={contextPercent}
          color="var(--ice)"
          caption="Contexto"
          ariaLabel={contextPercent === null ? "Contexto: sem dados" : `Contexto: ${Math.round(contextPercent)}%`}
        />
        <SplitRing
          ok={okCount}
          total={connectors.length}
          caption="Conexões"
          ariaLabel={`Conexões: ${okCount} de ${connectors.length} ok`}
        />
        <div
          className="grid h-11 w-14 place-items-center rounded-[14px] bg-accent font-mono text-[11.5px] text-accent-foreground"
          title={next ? next.text : "Sem lembretes"}
          aria-label={next ? `Próximo lembrete: ${next.text}, às ${hhmm(next.due_at)}` : "Sem lembretes agendados"}
        >
          {next ? hhmm(next.due_at) : "--:--"}
        </div>
        <Button variant="ghost" size="icon" className="size-11 rounded-full text-muted-foreground" aria-label="Expandir painel" onClick={() => setOpen(true)}>
          <ChevronLeft className="size-[18px]" strokeWidth={1.7} />
        </Button>
      </aside>
    );
  }

  const llama = memory?.llama ?? 0;
  const others = memory ? Math.max(memory.used - llama, 0) : 0;
  const pct = (part: number) => (memory && memory.total > 0 ? `${(part / memory.total) * 100}%` : "0%");

  return (
    <aside aria-label="Recursos" className={cn("flex flex-col gap-3 p-4", inSheet ? "w-full" : cn("w-[300px]", panel), className)}>
      {inSheet ? null : (
        <div className="flex items-center justify-between">
          <h2 className="pl-1 text-[13px] font-medium">Recursos</h2>
          <Button variant="ghost" size="icon" className="size-11 rounded-full text-muted-foreground" aria-label="Recolher painel" onClick={() => setOpen(false)}>
            <ChevronRight className="size-[18px]" strokeWidth={1.7} />
          </Button>
        </div>
      )}

      <Section title="Memória RAM">
        {memory ? (
          <>
            <p className="font-mono text-[13px]">
              {gb(memory.used)} de {gb(memory.total)} GB
              {ramLvl !== "ok" ? (
                <span className={cn("ml-2 font-sans text-[11.5px]", ramLvl === "warning" ? "text-warning-foreground" : "text-destructive-foreground")}>
                  {ramLvl === "warning" ? "apertada" : "crítica"}
                </span>
              ) : null}
            </p>
            <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-[#202127]" role="img" aria-label={`llama-server ${gb(llama)} GB, outros ${gb(others)} GB`}>
              <span className="h-full bg-ice" style={{ width: pct(llama) }} />
              <span className="h-full bg-chart-4" style={{ width: pct(others) }} />
            </div>
            <p className="mt-2 flex gap-3 text-[11.5px] text-muted-foreground">
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-[3px] bg-ice" />llama-server</span>
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-[3px] bg-chart-4" />outros</span>
            </p>
          </>
        ) : (
          <p className="text-[13px] text-muted-foreground">Sem leitura de memória.</p>
        )}
      </Section>

      <Section title="Modelo">
        <dl className="space-y-1 text-[13px]">
          <div className="flex justify-between"><dt className="text-muted-foreground">Velocidade</dt><dd className="font-mono">{llm?.tokensPerSecond != null ? `${llm.tokensPerSecond.toFixed(1)} tok/s` : "—"}</dd></div>
          <div className="flex justify-between"><dt className="text-muted-foreground">Contexto</dt><dd className="font-mono">{llm?.promptTokens != null ? `${llm.promptTokens}/${CONTEXT_WINDOW}` : `—/${CONTEXT_WINDOW}`}</dd></div>
        </dl>
      </Section>

      <Section title="Hoje">
        <p className="text-[13px]">
          {next ? <><span className="font-mono text-accent-foreground">{hhmm(next.due_at)}</span> {next.text}</> : <span className="text-muted-foreground">Sem lembretes agendados.</span>}
        </p>
        <p className="mt-1 text-[12.5px] text-muted-foreground">
          {pending?.length ? `${pending.length} ${pending.length === 1 ? "confirmação pendente" : "confirmações pendentes"}` : "Nenhuma confirmação pendente."}
        </p>
      </Section>

      <Section title="Conectores">
        <ul className="space-y-1.5 text-[13px]">
          {connectors.map((c) => (
            <li key={c.id} className="flex items-center gap-2">
              <StatusDot level={c.level} />
              <span className="truncate">{c.name}</span>
            </li>
          ))}
          {connectors.length === 0 ? <li className="text-muted-foreground">Sem conectores.</li> : null}
        </ul>
      </Section>
    </aside>
  );
}

/** No celular: botão no cabeçalho com o anel de RAM; abre o painel de recursos numa gaveta à direita. */
export function ResourceButton() {
  const memory = useLatestMemory();
  const ramPercent = memory && memory.total > 0 ? (memory.used / memory.total) * 100 : null;
  const lvl = ramPercent === null ? "ok" : ramLevel(ramPercent);
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="ghost" className="size-11 rounded-full p-0" aria-label="Recursos do sistema">
          <RingGauge
            compact
            percent={ramPercent}
            color={RAM_COLOR[lvl]}
            ariaLabel={ramPercent === null ? "Memória RAM: sem dados" : `Memória RAM: ${Math.round(ramPercent)}%`}
          />
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-[340px] max-w-[92vw] overflow-y-auto bg-popover">
        <SheetHeader className="pb-0">
          <SheetTitle>Recursos</SheetTitle>
          <SheetDescription className="sr-only">Memória, modelo, lembretes e conectores.</SheetDescription>
        </SheetHeader>
        <ResourceCapsule inSheet />
      </SheetContent>
    </Sheet>
  );
}
