import { lazy, Suspense, type ReactNode } from "react";
import { HashRouter, Route, Routes } from "react-router";
import { ErrorBoundary, RouteFallback } from "@/components/error-boundary";
import { AppShell } from "@/components/app-shell";
import { Toaster } from "@/components/ui/sonner";
import Inicio from "@/routes/inicio";

// Início vem no pacote principal (é a primeira tela); as outras rotas carregam sob demanda.
const Conversa = lazy(() => import("@/routes/conversa"));
const Lembretes = lazy(() => import("@/routes/lembretes"));
const Memoria = lazy(() => import("@/routes/memoria"));
const Monitor = lazy(() => import("@/routes/monitor"));
const Conectores = lazy(() => import("@/routes/conectores"));

/** Enquanto a rota carrega: só o fundo, sem texto nem salto de layout. */
function Lazy({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary fallback={<RouteFallback />}>
      <Suspense fallback={<div aria-busy="true" className="min-h-svh bg-background" />}>{children}</Suspense>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Inicio />} />
          <Route path="conversa" element={<Lazy><Conversa /></Lazy>} />
          <Route path="lembretes" element={<Lazy><Lembretes /></Lazy>} />
          <Route path="memoria" element={<Lazy><Memoria /></Lazy>} />
          <Route path="monitor" element={<Lazy><Monitor /></Lazy>} />
          <Route path="conectores" element={<Lazy><Conectores /></Lazy>} />
        </Route>
      </Routes>
      <Toaster />
    </HashRouter>
  );
}
