// Formatação de horários para as listas (fuso do navegador; o NICKEL roda na mesma máquina).
const WEEKDAYS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

const pad = (n: number) => String(n).padStart(2, "0");

export const clock = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** "YYYY-MM-DD" no fuso local. */
export const localDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

function dayDiff(due: Date, now: Date): number {
  const a = new Date(due.getFullYear(), due.getMonth(), due.getDate()).getTime();
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  return Math.round((a - b) / 86_400_000);
}

/** "hoje 15:02", "amanhã 08:00", "sex 19:00" (até 6 dias) ou "27/12 19:00". */
export function whenLabel(iso: string, now = new Date()): string {
  const due = new Date(iso);
  const diff = dayDiff(due, now);
  if (diff === 0) return `hoje ${clock(due)}`;
  if (diff === 1) return `amanhã ${clock(due)}`;
  if (diff > 1 && diff < 7) return `${WEEKDAYS[due.getDay()]} ${clock(due)}`;
  return `${pad(due.getDate())}/${pad(due.getMonth() + 1)} ${clock(due)}`;
}

/** "agora", "em 29 min", "em 3 h", "em 2 dias". */
export function relativeLabel(iso: string, now = new Date()): string {
  const minutes = Math.round((new Date(iso).getTime() - now.getTime()) / 60_000);
  if (minutes <= 0) return "agora";
  if (minutes < 60) return `em ${minutes} min`;
  if (minutes < 60 * 24) return `em ${Math.round(minutes / 60)} h`;
  const days = Math.round(minutes / (60 * 24));
  return `em ${days} ${days === 1 ? "dia" : "dias"}`;
}
