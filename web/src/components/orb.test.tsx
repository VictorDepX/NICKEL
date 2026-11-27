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
