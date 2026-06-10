import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ViewSwitcher } from "./ViewSwitcher";

describe("ViewSwitcher", () => {
  it("switches to a real workbench view state", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<ViewSwitcher activeView="overview" onChange={onChange} />);

    const reports = screen.getByRole("button", { name: /reports/i });
    expect(reports).toHaveAttribute("data-action-kind", "toggle");

    await user.click(reports);

    expect(onChange).toHaveBeenCalledWith("reports");
  });
});
