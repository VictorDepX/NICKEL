import { render, screen } from "@testing-library/react";
import App from "@/App";

test("mostra o nome NICKEL", () => {
  render(<App />);
  expect(screen.getByText("NICKEL")).toBeInTheDocument();
});
