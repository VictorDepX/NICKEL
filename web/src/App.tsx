import { HashRouter, Route, Routes } from "react-router";
import { AppShell } from "@/components/app-shell";
import { Toaster } from "@/components/ui/sonner";
import Conectores from "@/routes/conectores";
import Conversa from "@/routes/conversa";
import Inicio from "@/routes/inicio";
import Lembretes from "@/routes/lembretes";
import Memoria from "@/routes/memoria";
import Monitor from "@/routes/monitor";

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Inicio />} />
          <Route path="conversa" element={<Conversa />} />
          <Route path="lembretes" element={<Lembretes />} />
          <Route path="memoria" element={<Memoria />} />
          <Route path="monitor" element={<Monitor />} />
          <Route path="conectores" element={<Conectores />} />
        </Route>
      </Routes>
      <Toaster />
    </HashRouter>
  );
}
