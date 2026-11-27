import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Orb } from "@/components/orb";

test("o rótulo acompanha a fase", () => {
  const { rerender } = render(<Orb phase="idle" />);
  expect(screen.getByRole("img", { name: "NICKEL: Ocioso" })).toBeInTheDocument();
  expect(screen.queryByTestId("orb-ring")).toBeNull();
  rerender(<Orb phase="thinking" />);
  expect(screen.getByRole("img", { name: "NICKEL: Pensando" })).toBeInTheDocument();
  expect(screen.getByTestId("orb-ring").getAttribute("style")).toContain("var(--phase-thinking)");
});

test("com movimento reduzido a esfera vira um disco estático (sem GIF)", () => {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  try {
    const { container } = render(<Orb phase="thinking" />);
    expect(screen.getByTestId("orb-static")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  } finally {
    window.matchMedia = original;
  }
});

test("sem preferência de movimento reduzido, mostra o GIF", () => {
  const { container } = render(<Orb />);
  expect(container.querySelector("img")).not.toBeNull();
  expect(screen.queryByTestId("orb-static")).toBeNull();
});
