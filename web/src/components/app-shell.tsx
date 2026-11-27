import { Outlet, useLocation } from "react-router";
import { useState } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { ResourceCapsule } from "@/components/resource-capsule";

const STORAGE_KEY = "nickel.sidebar.open";
const CAPSULE_ROUTES = new Set(["/", "/conversa"]);

function readOpen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

/** Menu à esquerda (estado guardado), conteúdo da rota e, em Início e Conversa, a cápsula à direita. */
export function AppShell() {
  const [open, setOpen] = useState(readOpen);
  const { pathname } = useLocation();

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
        <Outlet />
        {CAPSULE_ROUTES.has(pathname) ? (
          <div className="absolute top-1/2 right-4 z-10 hidden -translate-y-1/2 md:block">
            <ResourceCapsule />
          </div>
        ) : null}
      </SidebarInset>
    </SidebarProvider>
  );
}
