import { lazy, Suspense } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ErrorBoundary, RouteFallback } from "@/components/error-boundary";

afterEach(() => vi.restoreAllMocks());

test("rota lazy que falha mostra a mensagem e o botão Recarregar", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const Broken = lazy(() => Promise.reject(new Error("Failed to fetch dynamically imported module")));
  render(
    <ErrorBoundary fallback={<RouteFallback />}>
      <Suspense fallback={null}>
        <Broken />
      </Suspense>
    </ErrorBoundary>,
  );
  expect(await screen.findByRole("button", { name: "Recarregar" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Esta tela não carregou.");
});

test("markdown cujo chunk falha cai para o texto puro", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.resetModules();
  vi.doMock("./markdown", () => {
    throw new Error("chunk");
  });
  const { MessageResponse: Fresh } = await import("@/components/ai-elements/message");
  render(<Fresh>texto **puro**</Fresh>);
  await waitFor(() => expect(screen.getByText("texto **puro**")).toBeInTheDocument());
  vi.doUnmock("./markdown");
});
