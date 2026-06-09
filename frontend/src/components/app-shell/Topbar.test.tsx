import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { RuntimeConfig } from "../../api/types";
import { Topbar } from "./Topbar";

const runtime = {
  temporal_cutover_ready: true,
  has_web_search_key: true,
  web_search_provider: "Search",
  compliance_redaction_enabled: true,
} as RuntimeConfig;

function renderTopbar(onMenuClick = vi.fn()) {
  render(
    <MemoryRouter>
      <Topbar onMenuClick={onMenuClick} routeLabel="Run setup" runtime={runtime} />
    </MemoryRouter>,
  );
  return { onMenuClick };
}

describe("Topbar", () => {
  it("opens mobile navigation through a real local action", async () => {
    const user = userEvent.setup();
    const { onMenuClick } = renderTopbar();

    await user.click(screen.getByRole("button", { name: "Menu" }));

    expect(onMenuClick).toHaveBeenCalledTimes(1);
  });

  it("keeps unavailable shell controls disabled with reasons", () => {
    renderTopbar();

    expect(screen.getByRole("button", { name: /notifications/i })).toBeDisabled();
    expect(screen.getByText("Notifications panel is not included in this demo build")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /help/i })).toBeDisabled();
    expect(screen.getByText("Help panel is not included in this demo build")).toBeInTheDocument();
  });

  it("keeps the research entry as a real route link", () => {
    renderTopbar();

    expect(screen.getByRole("link", { name: /ai research/i })).toHaveAttribute("href", "/");
  });
});
