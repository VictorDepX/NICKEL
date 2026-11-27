import { ShieldAlertIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { PendingAction } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ConfirmationCardProps {
  action: PendingAction;
  busy?: boolean;
  onConfirm: (id: string) => void;
  onCancel: (id: string) => void;
  className?: string;
}

/** Ação sensível esperando o usuário (`/api/pending`): cartão âmbar com Sim / Não. */
export function ConfirmationCard({ action, busy = false, onConfirm, onCancel, className }: ConfirmationCardProps) {
  return (
    <Card
      role="group"
      aria-label="Ação sensível aguardando confirmação"
      className={cn(
        "gap-3 rounded-[18px] border-warning/30 bg-[linear-gradient(180deg,rgba(251,191,36,.08),rgba(251,191,36,.02))] p-4 shadow-none",
        className,
      )}
    >
      <div className="flex items-center gap-2 text-xs font-medium text-warning-foreground">
        <ShieldAlertIcon className="size-4" aria-hidden="true" />
        Ação sensível · aguardando você
      </div>
      <p className="text-sm text-foreground">{action.summary}</p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-subtle-foreground">{action.tool}</span>
        <div className="ml-auto flex gap-2">
          <Button
            variant="outline"
            className="min-h-11 rounded-[10px] px-4 sm:min-h-9"
            disabled={busy}
            onClick={() => onCancel(action.id)}
          >
            Não
          </Button>
          <Button
            className="min-h-11 rounded-[10px] bg-warning px-4 font-semibold text-[#1a1204] hover:bg-warning/90 sm:min-h-9"
            disabled={busy}
            onClick={() => onConfirm(action.id)}
          >
            Sim
          </Button>
        </div>
      </div>
    </Card>
  );
}
