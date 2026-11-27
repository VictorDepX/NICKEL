import { Link, useLocation } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, Brain, Home, Activity, MessageSquare, PanelLeft, Plug, type LucideIcon } from "lucide-react";
import { activateWorkspace } from "@/lib/api";
import { useAppState } from "@/hooks/use-app-state";
import { useReminders, useWorkspaces, WORKSPACES_KEY, REMINDERS_KEY } from "@/hooks/use-shell-data";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/status-dot";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

interface NavEntry {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavEntry[] = [
  { to: "/", label: "Início", icon: Home },
  { to: "/conversa", label: "Conversa", icon: MessageSquare },
  { to: "/lembretes", label: "Lembretes", icon: Bell },
  { to: "/memoria", label: "Memória", icon: Brain },
  { to: "/monitor", label: "Monitor", icon: Activity },
  { to: "/conectores", label: "Conectores", icon: Plug },
];

const FIXED_SWATCHES: Record<string, string> = {
  geral: "var(--ice)",
  "rpg-coc": "var(--phase-tool)",
  codigo: "var(--phase-thinking)",
};
const CYCLE = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

export function swatchColor(id: string, index: number): string {
  return FIXED_SWATCHES[id] ?? CYCLE[index % CYCLE.length];
}

const itemClass =
  "h-auto min-h-10 gap-[11px] rounded-[10px] px-3 py-0 text-muted-foreground hover:bg-muted hover:text-foreground " +
  "data-[active=true]:bg-sidebar-accent data-[active=true]:font-normal data-[active=true]:text-foreground " +
  "data-[active=true]:shadow-[inset_0_0_0_1px_#26282f] [&>svg]:size-[18px] " +
  "group-data-[collapsible=icon]:size-11! group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:rounded-lg group-data-[collapsible=icon]:p-0!";

function isActive(pathname: string, to: string): boolean {
  return to === "/" ? pathname === "/" : pathname === to || pathname.startsWith(`${to}/`);
}

export function AppSidebar() {
  const { pathname } = useLocation();
  const { toggleSidebar, setOpenMobile } = useSidebar();
  const queryClient = useQueryClient();
  const { data: appState } = useAppState();
  const { data: reminders } = useReminders();
  const { data: workspaces } = useWorkspaces();

  const activate = useMutation({
    mutationFn: activateWorkspace,
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: WORKSPACES_KEY });
      void queryClient.invalidateQueries({ queryKey: ["state"] });
      void queryClient.invalidateQueries({ queryKey: REMINDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: ["messages"] });
    },
  });

  const badConnectors = appState?.connectors.filter((c) => c.level === "bad").length ?? 0;
  const reminderCount = reminders?.length ?? 0;
  const llmOk = appState?.llm.ok ?? false;
  const model = appState?.llm.model || "Modelo local";

  return (
    <Sidebar collapsible="icon" aria-label="Menu principal">
      <SidebarHeader className="px-3 pt-5 pb-3">
        <div className="flex items-center justify-between group-data-[collapsible=icon]:justify-center">
          <span className="pl-3 text-[13.5px] font-bold tracking-[0.16em] group-data-[collapsible=icon]:hidden">NICKEL</span>
          <Button
            variant="ghost"
            size="icon"
            className="size-11 rounded-lg text-muted-foreground"
            aria-label="Recolher ou expandir menu"
            onClick={toggleSidebar}
          >
            <PanelLeft className="size-[18px]" strokeWidth={1.7} />
          </Button>
        </div>
      </SidebarHeader>

      <SidebarContent className="gap-0 px-3">
        <SidebarMenu className="gap-1" aria-label="Seções">
          {NAV.map(({ to, label, icon: Icon }) => {
            const active = isActive(pathname, to);
            return (
              <SidebarMenuItem key={to}>
                <SidebarMenuButton asChild isActive={active} tooltip={label} className={itemClass}>
                  <Link to={to} aria-current={active ? "page" : undefined} onClick={() => setOpenMobile(false)}>
                    <Icon strokeWidth={1.7} />
                    <span className="flex-1">{label}</span>
                    {to === "/lembretes" && reminderCount > 0 ? (
                      <span
                        className="rounded-full bg-secondary px-2 text-[11px] leading-5 text-foreground group-data-[collapsible=icon]:hidden"
                        aria-label={`${reminderCount} lembretes`}
                      >
                        {reminderCount}
                      </span>
                    ) : null}
                    {to === "/conectores" && badConnectors > 0 ? (
                      <span className="text-[11.5px] text-destructive-foreground group-data-[collapsible=icon]:hidden">
                        {badConnectors} fora
                      </span>
                    ) : null}
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            );
          })}
        </SidebarMenu>

        <SidebarGroup className="mt-5 p-0">
          <SidebarGroupLabel className="h-auto px-3 pb-2 text-[11px] font-normal tracking-[0.12em] text-subtle-foreground uppercase">
            Workspaces
          </SidebarGroupLabel>
          <SidebarMenu className="gap-1" aria-label="Workspaces">
            {workspaces?.items.map((ws, index) => {
              const active = ws.id === workspaces.active;
              return (
                <SidebarMenuItem key={ws.id}>
                  <SidebarMenuButton
                    isActive={active}
                    tooltip={ws.name}
                    className={itemClass}
                    aria-pressed={active}
                    disabled={activate.isPending}
                    onClick={() => {
                      if (!active) activate.mutate(ws.id);
                      setOpenMobile(false);
                    }}
                  >
                    <span
                      className="size-2 shrink-0 rounded-[3px]"
                      style={{ background: swatchColor(ws.id, index), marginInline: "5px" }}
                      aria-hidden="true"
                    />
                    <span className="flex-1">{ws.name}</span>
                    {active ? (
                      <span className="text-[11.5px] text-subtle-foreground group-data-[collapsible=icon]:hidden">ativo</span>
                    ) : null}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="p-3 pb-4">
        <div
          className={cn(
            "flex items-center gap-3 rounded-xl border border-sidebar-border bg-card px-3 py-2.5",
            "group-data-[collapsible=icon]:size-11 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:p-0",
          )}
        >
          <StatusDot level={llmOk ? "ok" : "bad"} />
          <div className="min-w-0 group-data-[collapsible=icon]:hidden">
            <p className="truncate text-[13px] text-foreground">{model}</p>
            <p className="font-mono text-[11px] text-subtle-foreground">llama.cpp · local</p>
          </div>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
