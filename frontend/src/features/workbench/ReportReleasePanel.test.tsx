import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { ReportReleasePanel } from "./ReportReleasePanel";

const draftVersion = {
  id: "version-1",
  workspace_id: "workspace-1",
  project_id: "project-1",
  run_id: "run-1",
  version_number: 1,
  topic_normalized: "market map",
  competitor_layer: "L1",
  competitor_set_hash: "hash",
  status: "draft",
  report_md: "# Report",
  claim_ids: [],
  evidence_ids: [],
  created_at: "2026-06-09T00:00:00Z",
} satisfies ReportVersionRecord;

const inReviewVersion = {
  ...draftVersion,
  status: "in_review",
} satisfies ReportVersionRecord;

const approvedVersion = {
  ...draftVersion,
  status: "approved",
} satisfies ReportVersionRecord;

const blockedGate = {
  allowed: false,
  status: "blocked",
  readiness: { score: 62 },
  blocker_count: 1,
  warn_count: 0,
} as unknown as ReportReleaseGate;

function renderPanel(
  props: Partial<ComponentProps<typeof ReportReleasePanel>> = {},
) {
  const onExport = vi.fn();
  const onReportAction = vi.fn();

  render(
    <ReportReleasePanel
      isPending={false}
      lastExport={null}
      onExport={onExport}
      onReportAction={onReportAction}
      releaseGate={null}
      selectedVersion={draftVersion}
      {...props}
    />,
  );

  return { onExport, onReportAction };
}

describe("ReportReleasePanel", () => {
  it("starts review through a real report action", async () => {
    const user = userEvent.setup();
    const { onReportAction } = renderPanel();

    await user.click(screen.getByRole("button", { name: /start review/i }));

    expect(onReportAction).toHaveBeenCalledWith("start_review");
  });

  it("explains why approve is blocked before review", () => {
    renderPanel();

    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
    expect(
      screen.getAllByText("Move this report version into review before approving or rejecting it.").length,
    ).toBeGreaterThan(0);
  });

  it("approves and rejects only when the selected version is in review", async () => {
    const user = userEvent.setup();
    const { onReportAction } = renderPanel({ selectedVersion: inReviewVersion });

    await user.click(screen.getByRole("button", { name: /approve/i }));
    await user.click(screen.getByRole("button", { name: /reject/i }));

    expect(onReportAction).toHaveBeenCalledWith("approve");
    expect(onReportAction).toHaveBeenCalledWith("reject");
  });

  it("shows release gate blockers before publish", () => {
    renderPanel({ releaseGate: blockedGate });

    expect(screen.getByRole("button", { name: /publish/i })).toBeDisabled();
    expect(screen.getByText("Publish is blocked by 1 release gate blocker(s).")).toBeInTheDocument();
  });

  it("prevents duplicate report actions while pending", async () => {
    const user = userEvent.setup();
    const { onReportAction } = renderPanel({ isPending: true, selectedVersion: inReviewVersion });

    const approve = screen.getByRole("button", { name: /approve/i });
    expect(approve).toBeDisabled();
    expect(screen.getAllByText("Another report action is already in progress.").length).toBeGreaterThan(0);

    await user.click(approve);

    expect(onReportAction).not.toHaveBeenCalled();
  });

  it("calls export with the selected format when a version exists", async () => {
    const user = userEvent.setup();
    const { onExport } = renderPanel({ selectedVersion: approvedVersion });

    await user.click(screen.getByRole("button", { name: /markdown/i }));

    expect(onExport).toHaveBeenCalledWith("markdown");
  });
});
