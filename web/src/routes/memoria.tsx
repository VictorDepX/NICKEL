import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SearchIcon, ShieldAlertIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { APP_STATE_KEY } from "@/hooks/use-app-state";
import { useResolvePending } from "@/hooks/use-resolve-pending";
import { usePending } from "@/hooks/use-shell-data";
import {
  forgetMemory,
  getMemory,
  type MemoryEntry,
  type PendingAction,
} from "@/lib/api";

export const MEMORY_KEY = ["memory"] as const;

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));

function savedDate(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function PendingMemoryRow({ action }: { action: PendingAction }) {
  const { resolve, busy } = useResolvePending([MEMORY_KEY]);

  const decide = (decision: "confirm" | "cancel") =>
    resolve(action.id, decision, (result) => {
      if (result.ok) toast.success(decision === "confirm" ? "Guardado na memória." : "Recusado.");
      else toast.error(`${decision === "confirm" ? "Falha ao guardar" : "Falha ao recusar"}: ${errorText(result.error)}`);
    });

  return (
    <Card
      role="group"
      aria-label="Memória aguardando confirmação"
      className="gap-3 rounded-xl border-warning/30 bg-[linear-gradient(180deg,rgba(251,191,36,.08),rgba(251,191,36,.02))] p-4 shadow-none"
    >
      <div className="flex items-center gap-2 text-xs font-medium text-warning-foreground">
        <ShieldAlertIcon className="size-4" aria-hidden="true" />
        Guardar na memória? · aguardando você
      </div>
      <p className="text-sm text-foreground">{action.summary}</p>
      <div className="flex gap-2">
        <Button
          type="button"
          disabled={busy}
          onClick={() => void decide("confirm")}
          className="min-h-11 rounded-[10px] bg-warning px-4 font-semibold text-[#1a1204] hover:bg-warning/90 md:min-h-9"
        >
          Guardar
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => void decide("cancel")}
          className="min-h-11 rounded-[10px] px-4 md:min-h-9"
        >
          Recusar
        </Button>
      </div>
    </Card>
  );
}

function ConfirmDelete({
  trigger,
  title,
  description,
  action,
  onConfirm,
}: {
  trigger: React.ReactNode;
  title: string;
  description: string;
  action: string;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancelar</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={onConfirm}>
            {action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default function Memoria() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const { data: entries, isError } = useQuery({ queryKey: MEMORY_KEY, queryFn: getMemory });
  const { data: pending } = usePending();
  const memoryPending = useMemo(() => (pending ?? []).filter((a) => a.tool === "memory_save"), [pending]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entries ?? [];
    return (entries ?? []).filter((e) => e.key.toLowerCase().includes(q) || e.value.toLowerCase().includes(q));
  }, [entries, search]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: MEMORY_KEY });
    void queryClient.invalidateQueries({ queryKey: APP_STATE_KEY });
  };

  const forget = useMutation({
    mutationFn: (key: string) => forgetMemory(key),
    onSuccess: (_r, key) => toast.success(`Apagado: ${key}.`),
    onError: (err) => toast.error(`Falha ao apagar: ${errorText(err)}`),
    onSettled: refresh,
  });

  const forgetAll = useMutation({
    mutationFn: async () => {
      for (const entry of entries ?? []) await forgetMemory(entry.key);
    },
    onSuccess: () => toast.success("Memória apagada."),
    onError: (err) => toast.error(`Falha ao apagar tudo: ${errorText(err)}`),
    onSettled: refresh,
  });

  return (
    <section className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold tracking-tight">Memória</h1>
        {entries && (
          <Badge variant="secondary" className="font-mono" aria-label={`${entries.length} itens`}>
            {entries.length}
          </Badge>
        )}
        <p className="text-xs text-subtle-foreground">o NICKEL só guarda depois da sua confirmação</p>
        <ConfirmDelete
          trigger={
            <Button
              type="button"
              variant="destructive"
              disabled={!entries?.length || forgetAll.isPending}
              className="ml-auto min-h-11 rounded-[10px] md:min-h-9"
            >
              Apagar tudo
            </Button>
          }
          title="Apagar toda a memória?"
          description="O NICKEL esquece todos os itens guardados. Não dá para desfazer."
          action="Apagar tudo"
          onConfirm={() => forgetAll.mutate()}
        />
      </header>

      {memoryPending.map((action) => (
        <PendingMemoryRow key={action.id} action={action} />
      ))}

      <div className="relative">
        <SearchIcon
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle-foreground"
          aria-hidden="true"
        />
        <input
          type="search"
          aria-label="Buscar"
          placeholder="Buscar"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="min-h-11 w-full rounded-md border border-input bg-popover pr-3 pl-9 text-sm text-foreground outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 md:min-h-10"
        />
      </div>

      <Card className="gap-0 overflow-hidden rounded-xl border-border-soft p-0 shadow-none">
        {isError ? (
          <p className="p-4 text-sm text-destructive-foreground">Não foi possível carregar a memória.</p>
        ) : entries && filtered.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">
            {entries.length === 0 ? "Nada guardado ainda." : "Nada encontrado para essa busca."}
          </p>
        ) : (
          <ul aria-label="Memória guardada">
            {filtered.map((entry: MemoryEntry) => (
              <li key={entry.key} className="flex items-start gap-3 border-b border-border-soft px-4 py-2.5 last:border-b-0">
                <span className="w-32 shrink-0 truncate pt-0.5 font-mono text-[13px] text-muted-foreground sm:w-44" title={entry.key}>
                  {entry.key}
                </span>
                <span className="min-w-0 flex-1 text-sm break-words text-foreground">{entry.value}</span>
                {entry.created_at && (
                  <span className="hidden shrink-0 pt-0.5 text-xs text-subtle-foreground sm:inline">{savedDate(entry.created_at)}</span>
                )}
                <ConfirmDelete
                  trigger={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Apagar ${entry.key}`}
                      title="Apagar"
                      className="size-11 shrink-0 text-muted-foreground md:size-9"
                    >
                      <Trash2Icon aria-hidden="true" />
                    </Button>
                  }
                  title={`Apagar ${entry.key}?`}
                  description="O NICKEL esquece este item. Não dá para desfazer."
                  action="Apagar"
                  onConfirm={() => forget.mutate(entry.key)}
                />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </section>
  );
}
