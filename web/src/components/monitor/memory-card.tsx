import { useQuery } from "@tanstack/react-query";
import { ChevronDownIcon } from "lucide-react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, XAxis, YAxis, Tooltip } from "recharts";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { SYSTEM_MEMORY_KEY } from "@/hooks/use-shell-data";
import { getSystemMemory, type SystemMemorySample } from "@/lib/api";
import { num } from "@/lib/monitor-core";
import { cn } from "@/lib/utils";
import { CARD, CARD_TITLE, HINT, clockTime } from "./shared";

const GIB = 1024 ** 3;
const WINDOW_S = 30 * 60;
const TABLE_ROWS = 12;

export const MEM_SERIES = [
  { key: "used", label: "RAM usada (total)", color: "var(--chart-1)" },
  { key: "llama", label: "llama-server (modelo)", color: "var(--chart-2)" },
  { key: "nickel", label: "NICKEL", color: "var(--chart-4)" },
] as const;

type SeriesKey = (typeof MEM_SERIES)[number]["key"];

const chartConfig = Object.fromEntries(MEM_SERIES.map((s) => [s.key, { label: s.label, color: s.color }])) as ChartConfig;

export const gb = (bytes: number) => `${num(bytes / GIB, 1)} GB`;

export type MemLevel = { level: "ok" | "warn" | "bad"; text: string };

/** Folga de RAM pela memória livre: < 1 GB é pouca, < 2,5 GB é apertada. */
export function memLevel(sample: Pick<SystemMemorySample, "available">): MemLevel {
  const free = sample.available / GIB;
  if (free < 1) return { level: "bad", text: "pouca RAM livre" };
  if (free < 2.5) return { level: "warn", text: "RAM apertada" };
  return { level: "ok", text: "RAM folgada" };
}

const LEVEL_CLASS: Record<MemLevel["level"], string> = {
  ok: "border-success/30 bg-success/10 text-success",
  warn: "border-warning/30 bg-warning/10 text-warning-foreground",
  bad: "border-destructive/40 bg-destructive/10 text-destructive-foreground",
};

interface Point {
  t: number;
  used: number;
  llama: number;
  nickel: number;
  available: number;
}

const toGb = (s: SystemMemorySample): Point => ({
  t: s.t,
  used: s.used / GIB,
  llama: (s.llama || 0) / GIB,
  nickel: (s.nickel || 0) / GIB,
  available: s.available / GIB,
});

const gbText = (value: number) => `${num(value, 1)} GB`;

function MemTooltip({ active, payload }: { active?: boolean; payload?: ReadonlyArray<{ payload?: Point }> }) {
  const point = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;
  return (
    <div className="grid min-w-44 gap-1 rounded-lg border border-border bg-popover px-2.5 py-2 text-xs shadow-xl">
      <p className="font-mono font-medium text-foreground">{clockTime(point.t * 1000)}</p>
      {MEM_SERIES.map((s) => (
        <p key={s.key} className="flex items-center gap-2 text-muted-foreground">
          <span aria-hidden="true" className="size-2 shrink-0 rounded-[2px]" style={{ background: s.color }} />
          <span className="flex-1">{s.label}</span>
          <span className="font-mono text-foreground">{gbText(point[s.key])}</span>
        </p>
      ))}
      <p className="flex items-center gap-2 text-muted-foreground">
        <span aria-hidden="true" className="size-2 shrink-0" />
        <span className="flex-1">Livre</span>
        <span className="font-mono text-foreground">{gbText(point.available)}</span>
      </p>
    </div>
  );
}

const minutesAgo = (lastT: number) => (t: number) => {
  const minutes = Math.round((lastT - t) / 60);
  return minutes <= 0 ? "agora" : `há ${minutes} min`;
};

function MemChart({ samples }: { samples: SystemMemorySample[] }) {
  const last = samples[samples.length - 1];
  const totalGb = last.total / GIB;
  const data = samples.filter((s) => s.t >= last.t - WINDOW_S).map(toGb);
  const step = totalGb > 24 ? 8 : 4;
  const yTicks: number[] = [];
  for (let g = 0; g <= totalGb + 0.01; g += step) yTicks.push(g);
  const xTicks = [30, 20, 10, 0].map((m) => last.t - m * 60);

  return (
    <ChartContainer
      config={chartConfig}
      role="img"
      aria-label="Uso de memória RAM nos últimos 30 minutos"
      className="aspect-auto h-[190px] w-full"
    >
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.6} />
        <XAxis
          dataKey="t"
          type="number"
          domain={[last.t - WINDOW_S, last.t]}
          ticks={xTicks}
          tickFormatter={minutesAgo(last.t)}
          tickLine={false}
          axisLine={false}
          tickMargin={6}
        />
        <YAxis
          domain={[0, totalGb]}
          ticks={yTicks}
          tickFormatter={(g: number) => `${g} GB`}
          tickLine={false}
          axisLine={false}
          width={44}
        />
        <ReferenceLine y={totalGb} stroke="var(--muted-foreground)" strokeDasharray="4 4" strokeOpacity={0.7} />
        <Tooltip
          content={<MemTooltip />}
          cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
          isAnimationActive={false}
        />
        <Area
          dataKey="used"
          type="monotone"
          stroke="var(--color-used)"
          fill="var(--color-used)"
          fillOpacity={0.16}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
        <Line dataKey="llama" type="monotone" stroke="var(--color-llama)" strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="nickel" type="monotone" stroke="var(--color-nickel)" strokeWidth={2} dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ChartContainer>
  );
}

export function MemoryLegend() {
  return (
    <ul aria-label="Legenda" className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {MEM_SERIES.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2.5 rounded-[3px]" style={{ background: s.color }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

export function MemoryTable({ samples }: { samples: SystemMemorySample[] }) {
  const rows = samples.slice(-TABLE_ROWS).reverse();
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-subtle-foreground">
        <tr>
          <th className="py-1 pr-2 font-medium">Hora</th>
          {MEM_SERIES.map((s) => (
            <th key={s.key} className="py-1 pr-2 font-medium">
              {s.label}
            </th>
          ))}
          <th className="py-1 font-medium">Livre</th>
        </tr>
      </thead>
      <tbody className="font-mono text-muted-foreground">
        {rows.map((p) => (
          <tr key={p.t} className="border-t border-border-soft">
            <td className="py-1 pr-2">{clockTime(p.t * 1000)}</td>
            {MEM_SERIES.map((s) => (
              <td key={s.key} className="py-1 pr-2">
                {gb((p[s.key as SeriesKey] as number) || 0)}
              </td>
            ))}
            <td className="py-1">{gb(p.available)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11.5px] text-subtle-foreground">{term}</dt>
      <dd className="truncate font-mono text-[13px] text-foreground">{value}</dd>
    </div>
  );
}

/** Memória do sistema: fatos da última leitura, nível de folga, gráfico de 30 min, legenda e tabela. */
export function MemoryCard({ className }: { className?: string }) {
  const { data } = useQuery({ queryKey: SYSTEM_MEMORY_KEY, queryFn: getSystemMemory, refetchInterval: 5000 });
  const samples = data?.available ? data.samples : [];
  const last = samples[samples.length - 1];
  const level = last ? memLevel(last) : null;

  return (
    <section aria-labelledby="sysmem-title" className={cn(CARD, className)}>
      <header className="flex items-center justify-between gap-2">
        <h2 id="sysmem-title" className={CARD_TITLE}>
          Memória do sistema
        </h2>
        {level ? (
          <span
            data-level={level.level}
            className={cn("rounded-full border px-2.5 py-0.5 text-xs font-medium", LEVEL_CLASS[level.level])}
          >
            {level.text}
          </span>
        ) : null}
      </header>
      {!last ? (
        <p className={HINT}>{data ? "Leitura de memória indisponível neste sistema." : "Lendo a memória…"}</p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Fact term="Usada" value={`${num(last.used / GIB, 1)} de ${gb(last.total)} (${num((last.used / last.total) * 100)}%)`} />
            <Fact term="Livre" value={gb(last.available)} />
            <Fact term="llama-server" value={last.llama ? gb(last.llama) : "não encontrado"} />
            <Fact term="NICKEL" value={gb(last.nickel)} />
          </dl>
          <MemChart samples={samples} />
          <MemoryLegend />
          <Collapsible>
            <CollapsibleTrigger className="group inline-flex min-h-11 items-center gap-1 rounded-md text-[12.5px] text-ring hover:underline focus-visible:outline-2 focus-visible:outline-ring md:min-h-7">
              Ver tabela
              <ChevronDownIcon aria-hidden="true" className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
              <MemoryTable samples={samples} />
            </CollapsibleContent>
          </Collapsible>
        </>
      )}
    </section>
  );
}
