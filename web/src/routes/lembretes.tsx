import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellIcon, XIcon } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { APP_STATE_KEY } from "@/hooks/use-app-state";
import { REMINDERS_KEY, useReminders } from "@/hooks/use-shell-data";
import { ApiError, cancelReminder, createReminder, type NewReminder, type Reminder } from "@/lib/api";
import { localDate, relativeLabel, whenLabel } from "@/lib/format-when";

type Day = "hoje" | "amanha" | "data";

const FIELD = "flex min-w-0 flex-col gap-1.5";
const LABEL = "text-[13px] text-muted-foreground";
const CONTROL =
  "min-h-11 w-full rounded-md border border-input bg-popover px-3 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 aria-invalid:border-destructive md:min-h-10";

function dayToDate(day: Day, custom: string): string {
  const d = new Date();
  if (day === "amanha") d.setDate(d.getDate() + 1);
  return day === "data" ? custom : localDate(d);
}

function ReminderForm() {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [day, setDay] = useState<Day>("hoje");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: (body: NewReminder) => createReminder(body),
    onSuccess: () => {
      toast.success("Lembrete criado.");
      setText("");
      setTime("");
      setError(null);
      void queryClient.invalidateQueries({ queryKey: REMINDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: APP_STATE_KEY });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 422) setError(err.message);
      else toast.error(`Falha ao criar o lembrete: ${err instanceof Error ? err.message : String(err)}`);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const dateText = dayToDate(day, date);
    if (!text.trim()) return setError("Escreva o que lembrar.");
    if (!dateText || !time) return setError("Informe o dia e a hora.");
    create.mutate({ text: text.trim(), when: `${dateText}T${time}` });
  };

  return (
    <Card className="gap-3 rounded-xl border-border-soft p-4 shadow-none">
      <form
        onSubmit={submit}
        noValidate
        className="grid items-start gap-3 md:grid-cols-[2fr_1fr_1fr_auto]"
        aria-label="Novo lembrete"
      >
        <div className={FIELD}>
          <label htmlFor="rem-text" className={LABEL}>
            O quê
          </label>
          <Input
            id="rem-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Ex.: beber água"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "rem-error" : undefined}
            className="min-h-11 md:min-h-10"
          />
        </div>
        <div className={FIELD}>
          <label htmlFor="rem-day" className={LABEL}>
            Dia
          </label>
          <select id="rem-day" value={day} onChange={(e) => setDay(e.target.value as Day)} className={CONTROL}>
            <option value="hoje">Hoje</option>
            <option value="amanha">Amanhã</option>
            <option value="data">Outra data</option>
          </select>
          {day === "data" && (
            <input
              type="date"
              aria-label="Data"
              value={date}
              min={localDate(new Date())}
              onChange={(e) => setDate(e.target.value)}
              className={CONTROL}
            />
          )}
        </div>
        <div className={FIELD}>
          <label htmlFor="rem-time" className={LABEL}>
            Hora
          </label>
          <input
            id="rem-time"
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            aria-invalid={error ? true : undefined}
            className={`${CONTROL} font-mono`}
          />
        </div>
        <div className="flex flex-col gap-1.5 md:pt-[25px]">
          <Button type="submit" disabled={create.isPending} className="min-h-11 rounded-[10px] px-5 md:min-h-10">
            Criar lembrete
          </Button>
        </div>
        {error && (
          <p id="rem-error" role="alert" className="text-xs text-destructive-foreground md:col-span-4">
            {error}
          </p>
        )}
      </form>
      <p className="text-xs text-subtle-foreground">
        Ou peça no chat: &ldquo;me lembre de … daqui a 30 minutos&rdquo;.
      </p>
    </Card>
  );
}

function ReminderRow({ reminder, onCancel, busy }: { reminder: Reminder; onCancel: () => void; busy: boolean }) {
  return (
    <li className="flex items-center gap-3 border-b border-border-soft px-4 py-2.5 last:border-b-0">
      <span className="w-28 shrink-0 font-mono text-[13px] text-ring">{whenLabel(reminder.due_at)}</span>
      <span className="min-w-0 flex-1 truncate text-sm text-foreground">{reminder.text}</span>
      <span className="hidden shrink-0 text-xs text-subtle-foreground sm:inline">{relativeLabel(reminder.due_at)}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Cancelar lembrete"
        title="Cancelar lembrete"
        disabled={busy}
        onClick={onCancel}
        className="size-11 shrink-0 text-muted-foreground md:size-9"
      >
        <XIcon aria-hidden="true" />
      </Button>
    </li>
  );
}

export default function Lembretes() {
  const queryClient = useQueryClient();
  const { data: reminders, isError } = useReminders();

  const cancel = useMutation({
    mutationFn: (id: number) => cancelReminder(id),
    onSuccess: () => toast.success("Lembrete cancelado."),
    onError: (err) => toast.error(`Falha ao cancelar: ${err instanceof Error ? err.message : String(err)}`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: REMINDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: APP_STATE_KEY });
    },
  });

  return (
    <section className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-xl font-semibold tracking-tight">Lembretes</h1>
        {reminders && (
          <Badge variant="secondary" className="font-mono" aria-label={`${reminders.length} lembretes`}>
            {reminders.length}
          </Badge>
        )}
        <p className="text-xs text-subtle-foreground">o NICKEL avisa no app e no celular</p>
      </header>

      <ReminderForm />

      <Card className="gap-0 overflow-hidden rounded-xl border-border-soft p-0 shadow-none">
        {isError ? (
          <p className="p-4 text-sm text-destructive-foreground">Não foi possível carregar os lembretes.</p>
        ) : reminders && reminders.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-8 text-center text-sm text-muted-foreground">
            <BellIcon className="size-5 text-subtle-foreground" aria-hidden="true" />
            Nenhum lembrete agendado.
          </div>
        ) : (
          <ul aria-label="Lembretes agendados">
            {reminders?.map((r) => (
              <ReminderRow
                key={r.id}
                reminder={r}
                busy={cancel.isPending && cancel.variables === r.id}
                onCancel={() => cancel.mutate(r.id)}
              />
            ))}
          </ul>
        )}
      </Card>
    </section>
  );
}
