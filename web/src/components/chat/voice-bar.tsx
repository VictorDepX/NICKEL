import { SquareIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const BARS = [0, 0.15, 0.3, 0.45, 0.6];

/** Barra da fala (fase `speaking`): pulso laranja, ondas e "Parar". */
export function VoiceBar({ onStop, className }: { onStop: () => void; className?: string }) {
  return (
    <div
      role="status"
      aria-label="Falando a resposta"
      className={cn(
        "flex items-center gap-3 rounded-full border border-phase-speaking/30 bg-phase-speaking/8 py-1.5 pr-1.5 pl-4 text-[12.5px]",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="inline-block size-2 shrink-0 rounded-full bg-phase-speaking"
        style={{ animation: "nk-pulse 1.2s ease-in-out infinite" }}
      />
      <span className="text-[#fed7aa]">Falando a resposta</span>
      <span aria-hidden="true" className="flex h-4 items-center gap-[3px]">
        {BARS.map((delay) => (
          <span
            key={delay}
            className="inline-block h-full w-[3px] origin-center rounded-full bg-phase-speaking"
            style={{ animation: `nk-bars 0.9s ease-in-out ${delay}s infinite` }}
          />
        ))}
      </span>
      <Button
        variant="outline"
        size="sm"
        className="ml-auto min-h-11 rounded-full md:min-h-9 border-phase-speaking/40 bg-transparent text-[#fed7aa] hover:bg-phase-speaking/15"
        onClick={onStop}
      >
        <SquareIcon className="size-3 fill-current" aria-hidden="true" />
        Parar
      </Button>
    </div>
  );
}
