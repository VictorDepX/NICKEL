import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainIcon, SendHorizontalIcon } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Orb } from "@/components/orb";
import { Toggle } from "@/components/ui/toggle";
import { APP_STATE_KEY, useAppState } from "@/hooks/use-app-state";
import { useEvents } from "@/hooks/use-events";
import { PENDING_KEY, nextReminder, usePending, useReminders, useWorkspaces } from "@/hooks/use-shell-data";
import { cancelPending, confirmPending, getMessages, toggleVoice, type PendingAction } from "@/lib/api";
import { chatStatus } from "@/lib/monitor-core";
import { MESSAGES_KEY, readThink, writeThink } from "@/lib/conversa-prefs";
import { cn } from "@/lib/utils";

/** Nome usado na saudação. */
export const USER_NAME = "Victor";

export function greeting(date: Date): string {
  const hour = date.getHours();
  const period = hour >= 5 && hour < 12 ? "Bom dia" : hour >= 12 && hour < 18 ? "Boa tarde" : "Boa noite";
  return `${period}, ${USER_NAME}.`;
}

/** "sexta, 27 de novembro". */
export function longDate(date: Date): string {
  const weekday = date.toLocaleDateString("pt-BR", { weekday: "long" }).replace("-feira", "");
  const rest = date.toLocaleDateString("pt-BR", { day: "numeric", month: "long" });
  return `${weekday}, ${rest}`.toLowerCase();
}

const hhmm = (value: Date | string) =>
  new Date(value).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

/** Relógio que se atualiza sozinho (a cada 15 s; o minuto vira com atraso curto). */
function useClock(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 15_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

function untilText(dueAt: string, now: Date): string | null {
  const minutes = Math.round((Date.parse(dueAt) - now.getTime()) / 60_000);
  if (Number.isNaN(minutes) || minutes < 0) return null;
  if (minutes < 60) return `em ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `em ${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
}

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));

const CARD = "flex min-h-[132px] flex-col gap-2 rounded-xl border border-border-soft bg-card p-4";
const CARD_TITLE = "text-xs font-medium text-muted-foreground";
const CARD_LINK =
  "inline-flex min-h-11 items-center rounded-md text-[12.5px] text-ring underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring md:min-h-6";

function ReminderCard({ now }: { now: Date }) {
  const { data } = useReminders();
  const next = nextReminder(data);
  const until = next ? untilText(next.due_at, now) : null;
  return (
    <section className={CARD} aria-label="Próximo lembrete">
      <h2 className={CARD_TITLE}>Próximo lembrete</h2>
      {next ? (
        <>
          <p className="font-mono text-[28px] leading-none font-semibold tracking-tight">{hhmm(next.due_at)}</p>
          <p className="line-clamp-2 text-sm text-foreground">
            {next.text}
            {until ? <span className="text-subtle-foreground"> · {until}</span> : null}
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">Nenhum lembrete agendado.</p>
          <Link to="/lembretes" className={cn(CARD_LINK, "mt-auto")}>
            Criar lembrete
          </Link>
        </>
      )}
    </section>
  );
}

function PendingCard({ action }: { action: PendingAction | undefined }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  // Ref (e não só estado): um clique duplo chega antes de o React desabilitar os botões.
  const resolving = useRef(false);

  if (!action) {
    return (
      <section className={CARD} aria-label="Aguardando você">
        <h2 className={CARD_TITLE}>Aguardando você</h2>
        <p className="text-sm text-muted-foreground">Nada pendente.</p>
      </section>
    );
  }

  const resolve = async (decision: "confirm" | "cancel") => {
    if (resolving.current) return;
    resolving.current = true;
    setBusy(true);
    try {
      await (decision === "confirm" ? confirmPending(action.id) : cancelPending(action.id));
      queryClient.setQueryData<PendingAction[]>(PENDING_KEY, (items) => items?.filter((a) => a.id !== action.id));
    } catch (err) {
      toast.error(`${decision === "confirm" ? "Falha ao guardar" : "Falha ao recusar"}: ${errorText(err)}`);
    } finally {
      void queryClient.invalidateQueries({ queryKey: APP_STATE_KEY });
      void queryClient.invalidateQueries({ queryKey: MESSAGES_KEY });
      try {
        await queryClient.invalidateQueries({ queryKey: PENDING_KEY });
      } finally {
        resolving.current = false;
        setBusy(false);
      }
    }
  };

  return (
    <section
      className={cn(CARD, "border-[rgba(251,191,36,.28)] bg-[linear-gradient(180deg,rgba(251,191,36,.08),rgba(251,191,36,.02))]")}
      aria-label="Aguardando você"
    >
      <h2 className={cn(CARD_TITLE, "text-warning-foreground")}>Aguardando você</h2>
      <p className="line-clamp-2 text-sm text-foreground">{action.summary}</p>
      <div className="mt-auto flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void resolve("confirm")}
          className="min-h-11 rounded-[10px] bg-warning px-4 text-[13px] font-semibold text-[#1a1204] hover:bg-warning/90 disabled:opacity-50 md:min-h-9"
        >
          Guardar
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void resolve("cancel")}
          className="min-h-11 rounded-[10px] border border-input px-4 text-[13px] text-foreground hover:bg-muted disabled:opacity-50 md:min-h-9"
        >
          Recusar
        </button>
      </div>
    </section>
  );
}

function ConnectorsCard() {
  const { data } = useAppState();
  const items = data?.connectors ?? [];
  const names = (level: string) => items.filter((c) => c.level === level).map((c) => c.name);
  const ok = names("ok");
  const warn = names("warn");
  const bad = names("bad");
  const problems = bad.length + warn.length > 0;
  return (
    <section className={CARD} aria-label="Conectores">
      <h2 className={CARD_TITLE}>Conectores</h2>
      <div className="space-y-1 text-[13px]">
        {ok.length ? <p className="text-muted-foreground">{ok.join(", ")}</p> : null}
        {warn.length ? <p className="text-warning-foreground">{warn.join(", ")}</p> : null}
        {bad.length ? <p className="text-destructive-foreground">{bad.join(", ")}</p> : null}
        {!items.length ? <p className="text-muted-foreground">Sem dados ainda.</p> : null}
      </div>
      <Link to="/conectores" className={cn(CARD_LINK, "mt-auto")}>
        {problems ? "Resolver conexões" : "Ver conectores"}
      </Link>
    </section>
  );
}

function ContinueCard() {
  const { data: appState } = useAppState();
  const { data: workspaces } = useWorkspaces();
  const workspaceId = appState?.workspace ?? workspaces?.active ?? "";
  const { data } = useQuery({
    queryKey: [...MESSAGES_KEY, workspaceId],
    queryFn: () => getMessages(120),
    refetchInterval: 15_000,
  });
  const last = [...(data ?? [])].reverse().find((m) => m.role === "user");
  return (
    <section className={CARD} aria-label="Continuar conversa">
      <h2 className={CARD_TITLE}>Continuar conversa</h2>
      {last ? (
        <>
          <p className="line-clamp-2 text-sm text-foreground">{last.content}</p>
          <Link to="/conversa" className={cn(CARD_LINK, "mt-auto")}>
            Abrir · {hhmm(last.created_at)}
          </Link>
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">Nenhuma conversa ainda.</p>
          <Link to="/conversa" className={cn(CARD_LINK, "mt-auto")}>
            Abrir
          </Link>
        </>
      )}
    </section>
  );
}

export default function Inicio() {
  const navigate = useNavigate();
  const now = useClock();
  const { state } = useEvents();
  const { data: appState } = useAppState();
  const { data: pending } = usePending();
  const status = chatStatus(state, 0);
  const idle = status.phase === "idle";

  const [text, setText] = useState("");
  const [thinkChoice, setThinkChoice] = useState<boolean | null>(readThink);
  const think = thinkChoice ?? appState?.think_default ?? false;

  const talk = () => {
    navigate("/conversa");
    if (appState?.voice?.available) {
      toggleVoice().catch((err) => toast.error(`Falha no microfone: ${errorText(err)}`));
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const draft = text.trim();
    if (!draft) return;
    navigate("/conversa", { state: { draft } });
  };

  return (
    <section
      aria-label="Início"
      className="min-h-svh bg-[radial-gradient(ellipse_50%_42%_at_56%_30%,#141a22_0%,transparent_70%)]"
    >
      <div className="mx-auto flex min-h-svh w-full max-w-[980px] flex-col gap-5 pt-[30px] pr-4 pb-7 pl-4 md:pr-32 md:pl-11">
        <div className="flex items-center justify-between text-[12.5px] text-subtle-foreground">
          <span>{longDate(now)}</span>
          <span className="font-mono">{hhmm(now)}</span>
        </div>

        <div className="flex flex-col items-center gap-4 pt-2 text-center">
          <button
            type="button"
            aria-label="Falar com o NICKEL"
            onClick={talk}
            className="rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
          >
            <Orb size={250} phase={status.phase} />
          </button>
          <h1 className="text-[38px] leading-tight font-semibold tracking-[-0.025em]">{greeting(now)}</h1>
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            {idle ? (
              <>
                <span aria-hidden="true" className="size-2 rounded-full bg-success" />
                <span>
                  Pronto · toque na esfera ou segure{" "}
                  <kbd className="rounded border border-border bg-muted px-1.5 font-mono text-xs">Espaço</kbd> para falar
                </span>
              </>
            ) : (
              <span>{status.text}</span>
            )}
          </p>

          <form
            onSubmit={submit}
            className="flex w-full max-w-[660px] items-center gap-2 rounded-full border border-border bg-card py-[7px] pr-[7px] pl-5 shadow-md"
          >
            <label htmlFor="inicio-prompt" className="sr-only">
              Mensagem para o NICKEL
            </label>
            <input
              id="inicio-prompt"
              value={text}
              onChange={(e) => setText(e.currentTarget.value)}
              placeholder="Ou escreva aqui…"
              autoComplete="off"
              className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-subtle-foreground"
            />
            <Toggle
              pressed={think}
              onPressedChange={(value) => {
                setThinkChoice(value);
                writeThink(value);
              }}
              aria-label="Pensar"
              title="Pensar antes de responder"
              className="h-auto min-h-11 gap-1.5 rounded-full border border-input px-3.5 text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground data-[state=on]:border-[#2e3a47] data-[state=on]:bg-accent data-[state=on]:text-accent-foreground"
            >
              <BrainIcon aria-hidden="true" />
              <span className="hidden sm:inline">Pensar</span>
            </Toggle>
            <button
              type="submit"
              aria-label="Enviar"
              disabled={!text.trim()}
              className="inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
            >
              <SendHorizontalIcon className="size-5" aria-hidden="true" />
            </button>
          </form>
        </div>

        <div className="mt-auto grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <ReminderCard now={now} />
          <PendingCard action={pending?.[0]} />
          <ConnectorsCard />
          <ContinueCard />
        </div>
      </div>
    </section>
  );
}
