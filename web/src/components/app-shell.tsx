import { Outlet, useLocation } from "react-router";
import { useState } from "react";
import { SidebarInset, SidebarProvider, useSidebar } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { PanelLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ResourceButton, ResourceCapsule } from "@/components/resource-capsule";
import { useIsMobile } from "@/hooks/use-mobile";

const STORAGE_KEY = "nickel.sidebar.open";
const CAPSULE_ROUTES = new Set(["/", "/conversa"]);

function readOpen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

/** Cabeçalho do celular (< md): botão do menu à esquerda e, em Início e Conversa, o anel de RAM à direita. */
function MobileHeader({ withResources }: { withResources: boolean }) {
  const { setOpenMobile } = useSidebar();
  return (
    <header className="flex shrink-0 items-center justify-between border-b border-border px-2 py-1">
      <Button variant="ghost" size="icon" className="size-11 rounded-lg text-muted-foreground" aria-label="Abrir menu" onClick={() => setOpenMobile(true)}>
        <PanelLeft className="size-[18px]" strokeWidth={1.7} />
      </Button>
      {withResources ? <ResourceButton /> : null}
    </header>
  );
}

/** Menu à esquerda (estado guardado), conteúdo da rota e, em Início e Conversa, a cápsula à direita. */
export function AppShell() {
  const [open, setOpen] = useState(readOpen);
  const { pathname } = useLocation();
  const isMobile = useIsMobile();
  const withCapsule = CAPSULE_ROUTES.has(pathname);

  return (
    <SidebarProvider
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        try {
          localStorage.setItem(STORAGE_KEY, String(value));
        } catch {
          /* sem armazenamento: o estado vale só nesta sessão */
        }
      }}
      style={{ "--sidebar-width": "236px", "--sidebar-width-icon": "68px" } as React.CSSProperties}
    >
      <AppSidebar />
      <SidebarInset className="relative min-w-0">
        {isMobile ? <MobileHeader withResources={withCapsule} /> : null}
        <Outlet />
        {withCapsule && !isMobile ? (
          <div className="absolute top-1/2 right-4 z-10 hidden -translate-y-1/2 md:block">
            <ResourceCapsule />
          </div>
        ) : null}
      </SidebarInset>
    </SidebarProvider>
  );
}
