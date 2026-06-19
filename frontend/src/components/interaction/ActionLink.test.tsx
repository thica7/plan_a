import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ActionLink } from "./ActionLink";

describe("ActionLink", () => {
  it("renders a router link for internal routes", () => {
    render(
      <MemoryRouter>
        <ActionLink
          authenticity={{
            actionId: "nav.history",
            kind: "route",
            description: "opens run history",
          }}
          to="/history"
        >
          History
        </ActionLink>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "History" });
    expect(link).toHaveAttribute("href", "/history");
    expect(link).toHaveAttribute("data-action-id", "nav.history");
    expect(link).toHaveAttribute("data-action-kind", "route");
  });

  it("renders an external anchor with safe attributes", () => {
    render(
      <ActionLink
        authenticity={{
          actionId: "source.external.open",
          kind: "external",
          description: "opens source website",
        }}
        external
        href="https://example.com/source"
      >
        Source
      </ActionLink>,
    );

    const link = screen.getByRole("link", { name: "Source" });
    expect(link).toHaveAttribute("href", "https://example.com/source");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("renders disabled navigation as a non-link button with reason", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <MemoryRouter>
        <ActionLink
          authenticity={{
            actionId: "reports.open.disabled",
            kind: "disabled",
            description: "reports route blocked without artifacts",
          }}
          disabled
          disabledReason="Reports are unavailable until a run produces an artifact."
          onClick={handleClick}
          to="/reports"
        >
          Reports
        </ActionLink>
      </MemoryRouter>,
    );

    expect(screen.queryByRole("link", { name: "Reports" })).not.toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Reports" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Reports are unavailable until a run produces an artifact.")).toBeInTheDocument();

    await user.click(button);

    expect(handleClick).not.toHaveBeenCalled();
  });

  it("rejects empty and placeholder destinations", () => {
    expect(() =>
      render(
        <MemoryRouter>
          <ActionLink
            authenticity={{
              actionId: "bad.placeholder.route",
              kind: "route",
              description: "bad placeholder route",
            }}
            to="#"
          >
            Bad
          </ActionLink>
        </MemoryRouter>,
      ),
    ).toThrow("placeholder destination");
  });

  it("allows callback links only when a real click handler exists", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <ActionLink
        authenticity={{
          actionId: "help.open.local",
          kind: "local",
          description: "opens local help drawer",
        }}
        onClick={handleClick}
      >
        Help
      </ActionLink>,
    );

    const button = screen.getByRole("button", { name: "Help" });
    await user.click(button);

    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("requires icon-only links to have an accessible name", () => {
    expect(() =>
      render(
        <ActionLink
          authenticity={{
            actionId: "bad.icon-only.link",
            kind: "local",
            description: "bad icon-only link",
          }}
          onClick={vi.fn()}
        >
          <span aria-hidden="true" />
        </ActionLink>,
      ),
    ).toThrow("accessible name");
  });
});
