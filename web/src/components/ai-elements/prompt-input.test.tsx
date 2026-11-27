import { createEvent, fireEvent, render } from "@testing-library/react";
import { expect, test } from "vitest";
import { PromptInput } from "./prompt-input";

const drop = (form: HTMLElement, types: string[]) => {
  const event = createEvent.drop(form, { dataTransfer: { types, files: [] } });
  fireEvent(form, event);
  return event.defaultPrevented;
};

test("arquivo solto no formulário é bloqueado; texto solto segue nativo", () => {
  const { container } = render(<PromptInput onSubmit={() => {}}>x</PromptInput>);
  const form = container.querySelector("form") as HTMLElement;
  expect(drop(form, ["Files"])).toBe(true);
  expect(drop(form, ["text/plain"])).toBe(false);
});
