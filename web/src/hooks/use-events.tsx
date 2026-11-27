import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { getEventsCatalog } from "@/lib/api";
import { applyEvent, initialState, type AuditEvent, type Catalog, type MonitorState } from "@/lib/monitor-core";

export interface EventsValue {
  state: MonitorState;
  catalog: Catalog;
  connected: boolean;
}

const EMPTY_CATALOG: Catalog = { kinds: {}, phases: {}, labels: {} };
const CATALOG_RETRY_MS = 3000;
const BACKOFF_START_MS = 500;
const BACKOFF_MAX_MS = 5000;

const EventsContext = createContext<EventsValue | null>(null);

/**
 * Mantém o EventSource em /api/events/stream e aplica cada evento de auditoria ao estado do monitor.
 * Se a conexão cai, reabre com backoff (até 5 s) pedindo `after=<último id>`: o servidor reenvia o que
 * faltou e o estado (fase, raciocínio) se reidrata sozinho, sem ficar preso em "Pensando".
 */
export function EventsProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MonitorState>(initialState);
  const [catalog, setCatalog] = useState<Catalog>(EMPTY_CATALOG);
  const [connected, setConnected] = useState(false);
  const lastIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = BACKOFF_START_MS;
    let loaded: Catalog = EMPTY_CATALOG;

    const onAudit = (message: MessageEvent<string>) => {
      let event: AuditEvent;
      try {
        event = JSON.parse(message.data) as AuditEvent;
      } catch {
        return;
      }
      if (typeof event.id === "number") lastIdRef.current = Math.max(lastIdRef.current, event.id);
      setState((prev) => applyEvent(prev, event, loaded));
    };

    const connect = () => {
      if (cancelled) return;
      const after = lastIdRef.current;
      source = new EventSource(after ? `/api/events/stream?after=${after}` : "/api/events/stream");
      source.addEventListener("open", () => {
        delay = BACKOFF_START_MS;
        setConnected(true);
      });
      source.addEventListener("audit", onAudit as EventListener);
      source.addEventListener("error", () => {
        setConnected(false);
        // Reabrimos nós mesmos (com `after`), em vez de depender da reconexão automática do navegador.
        source?.close();
        source = null;
        timer = setTimeout(connect, delay);
        delay = Math.min(delay * 2, BACKOFF_MAX_MS);
      });
    };

    const start = async () => {
      for (;;) {
        try {
          loaded = await getEventsCatalog();
          break;
        } catch {
          if (cancelled) return;
          await new Promise<void>((resolve) => {
            timer = setTimeout(resolve, CATALOG_RETRY_MS);
          });
        }
      }
      if (cancelled) return;
      setCatalog(loaded);
      connect();
    };
    void start();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      source?.close();
    };
  }, []);

  return <EventsContext.Provider value={{ state, catalog, connected }}>{children}</EventsContext.Provider>;
}

export function useEvents(): EventsValue {
  const value = useContext(EventsContext);
  if (!value) throw new Error("useEvents precisa estar dentro de <EventsProvider>.");
  return value;
}
