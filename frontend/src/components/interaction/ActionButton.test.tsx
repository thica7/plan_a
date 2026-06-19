import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ActionButton } from "./ActionButton";

const metadata = {
  actionId: "topbar.notifications.open",
  kind: "local" as const,
  description: "opens notifications panel",
};

describe("ActionButton", () => {
  it("defaults to type button and calls the ready handler", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <ActionButton authenticity={metadata} onClick={handleClick}>
        Notifications
      </ActionButton>,
    );

    const button = screen.getByRole("button", { name: "Notifications" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("data-action-id", metadata.actionId);
    expect(button).toHaveAttribute("data-action-kind", "local");

    await user.click(button);

    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("preserves submit semantics", () => {
    render(
      <ActionButton
        authenticity={{
          actionId: "new-run.submit",
          kind: "submit",
          description: "submits the new run form",
        }}
        type="submit"
      >
        Start Run
      </ActionButton>,
    );

    expect(screen.getByRole("button", { name: "Start Run" })).toHaveAttribute("type", "submit");
  });

  it("suppresses disabled clicks and exposes the disabled reason", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <ActionButton
        authenticity={{
          actionId: "report.publish",
          kind: "mutation",
          description: "publishes an approved report",
        }}
        disabled
        disabledReason="Publish is blocked until the release gate passes."
        onClick={handleClick}
      >
        Publish
      </ActionButton>,
    );

    const button = screen.getByRole("button", { name: "Publish" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("data-action-state", "disabled");
    expect(screen.getByText("Publish is blocked until the release gate passes.")).toBeInTheDocument();

    await user.click(button);

    expect(handleClick).not.toHaveBeenCalled();
  });

  it("suppresses loading clicks and shows the loading label", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <ActionButton
        authenticity={{
          actionId: "report.approve",
          kind: "mutation",
          description: "approves a report version",
        }}
        isLoading
        loadingLabel="Approving report..."
        onClick={handleClick}
      >
        Approve
      </ActionButton>,
    );

    const button = screen.getByRole("button", { name: "Approving report..." });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("data-action-state", "loading");

    await user.click(button);

    expect(handleClick).not.toHaveBeenCalled();
  });

  it("requires enabled non-submit buttons to have handlers", () => {
    expect(() =>
      render(
        <ActionButton
          authenticity={{
            actionId: "bad.enabled.no-handler",
            kind: "local",
            description: "bad enabled control",
          }}
        >
          Bad
        </ActionButton>,
      ),
    ).toThrow("requires onClick");
  });

  it("requires disabled buttons to explain why they are unavailable", () => {
    expect(() =>
      render(
        <ActionButton
          authenticity={{
            actionId: "bad.disabled.no-reason",
            kind: "disabled",
            description: "bad disabled control",
          }}
          disabled
        >
          Bad
        </ActionButton>,
      ),
    ).toThrow("disabledReason");
  });

  it("requires icon-only buttons to have an accessible name", () => {
    expect(() =>
      render(
        <ActionButton
          authenticity={{
            actionId: "bad.icon-only",
            kind: "local",
            description: "bad icon-only control",
          }}
          onClick={vi.fn()}
        >
          <span aria-hidden="true" />
        </ActionButton>,
      ),
    ).toThrow("accessible name");
  });
});
