import { Card } from "@/components/ui/card";
import { StatusDot } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { useAppState } from "@/hooks/use-app-state";
import type { ConnectorItem, Level } from "@/lib/api";
import { cn } from "@/lib/utils";

const LEVEL_TEXT: Record<Level, string> = { ok: "funcionando", warn: "falta um passo", bad: "fora do ar" };
const LEVEL_COLOR: Record<Level, string> = { ok: "text-success", warn: "text-warning-foreground", bad: "text-destructive-foreground" };

function ConnectorCard({ item }: { item: ConnectorItem }) {
  return (
    <Card className="gap-2 rounded-xl border-border-soft p-4 shadow-none">
      <div className="flex items-center gap-2">
        <StatusDot level={item.level} />
        <h3 className="text-sm font-medium text-foreground">{item.name}</h3>
      </div>
      <p className={cn("text-[13px]", LEVEL_COLOR[item.level])}>
        {LEVEL_TEXT[item.level]}
        {item.detail ? <span className="text-subtle-foreground"> · {item.detail}</span> : null}
      </p>
      {item.action && (
        <Button asChild variant="secondary" size="sm" className="mt-1 min-h-11 w-fit rounded-[10px] md:min-h-8">
          <a href={item.action}>Conectar</a>
        </Button>
      )}
    </Card>
  );
}

export default function Conectores() {
  const { data: state, isError } = useAppState();
  const connectors = state?.connectors ?? [];
  const pipelines = state?.pipelines ?? [];

  return (
    <section className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-xl font-semibold tracking-tight">Conectores</h1>
        <p className="text-xs text-subtle-foreground">só aparecem os configurados</p>
      </header>

      {isError && <p className="text-sm text-destructive-foreground">Não foi possível carregar o estado do NICKEL.</p>}

      {state && connectors.length === 0 ? (
        <Card className="rounded-xl border-border-soft p-8 text-center text-sm text-muted-foreground shadow-none">
          Nenhum conector configurado.
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {connectors.map((item) => (
            <ConnectorCard key={item.id} item={item} />
          ))}
        </div>
      )}

      {pipelines.length > 0 && (
        <>
          <h2 className="mt-2 text-sm font-medium text-muted-foreground">Pipelines</h2>
          <Card className="gap-0 overflow-hidden rounded-xl border-border-soft p-0 shadow-none">
            <ul aria-label="Pipelines">
              {pipelines.map((item) => (
                <li key={item.id} className="flex items-center gap-3 border-b border-border-soft px-4 py-2.5 last:border-b-0">
                  <StatusDot level={item.level} />
                  <span className="text-sm text-foreground">{item.name}</span>
                  <span className="ml-auto text-right text-xs text-subtle-foreground">{item.detail}</span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </section>
  );
}
