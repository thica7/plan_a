import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function SmokeButton() {
  return <button type="button">Ready</button>;
}

describe("DOM test harness", () => {
  it("renders a real button by accessible role", () => {
    render(<SmokeButton />);

    expect(screen.getByRole("button", { name: "Ready" })).toBeInTheDocument();
  });
});
