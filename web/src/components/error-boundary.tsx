import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** O que mostrar no lugar dos filhos quando algo falha. */
  fallback: ReactNode;
}

/** Captura erros de renderização e de chunks lazy que não carregam (aba antiga depois de uma atualização). */
export class ErrorBoundary extends Component<ErrorBoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("NICKEL: falha ao renderizar", error, info.componentStack);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Tela de falha de uma rota: pede para recarregar (resolve o chunk antigo depois de atualizar o NICKEL). */
export function RouteFallback() {
  return (
    <div role="alert" className="flex min-h-svh flex-col items-center justify-center gap-3 bg-background p-6 text-center">
      <p className="text-sm text-foreground">Esta tela não carregou.</p>
      <p className="max-w-sm text-[13px] text-muted-foreground">
        O NICKEL pode ter sido atualizado. Recarregue a página para continuar.
      </p>
      <Button className="min-h-11" onClick={() => window.location.reload()}>
        Recarregar
      </Button>
    </div>
  );
}
