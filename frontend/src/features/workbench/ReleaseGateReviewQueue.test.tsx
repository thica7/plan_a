import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { ReleaseGateReviewQueue } from "./ReleaseGateReviewQueue";
import { buildReleaseGateReviewTasks } from "./releaseGateReview";

const gateWithKbBlocker = {
  allowed: false,
  status: "blocked",
  readiness: { score: 42 },
  issue_count: 1,
  blocker_count: 1,
  warn_count: 0,
  issues: [
    {
      id: "issue-claim-conflict",
      rule_id: "claim_self_consistency_required",
      rule_name: "Claim self-consistency",
      severity: "blocker",
      message: "Claim claim-pricing validation is unsupported.",
      evidence_ids: ["evidence-pricing-conflict"],
      claim_ids: ["claim-pricing-conflict"],
      recommendation: "Resolve the listed claim-validation issue types.",
      metadata: {
        claim_validation_issue_types: ["conflicting_evidence"],
        conflicting_evidence_ids: ["evidence-pricing-conflict"],
        evidence_audit_trail: [
          {
            evidence_id: "evidence-pricing-conflict",
            raw_source_id: "evidence-kb-pricing-001",
            kb_document_id: "kb-doc-pricing-v3",
            kb_document_version: 3,
            kb_document_status: "active",
            kb_raw_source_id: "collector-raw-pricing-001",
            kb_collector_run_id: "collector-run-1",
            kb_freshness_score: 0.86,
          },
        ],
      },
    },
  ],
} as unknown as ReportReleaseGate;

const selectedVersion = {
  id: "report-version-1",
  run_id: "run-1",
  version_number: 1,
  status: "draft",
  report_md: "",
  claim_ids: ["claim-pricing-conflict"],
  evidence_ids: ["evidence-pricing-conflict"],
} as unknown as ReportVersionRecord;

describe("ReleaseGateReviewQueue", () => {
  it("builds reviewer tasks with KB rollback context", () => {
    const [task] = buildReleaseGateReviewTasks(gateWithKbBlocker);

    expect(task.phase).toBe("kb_cleanup");
    expect(task.claimCount).toBe(1);
    expect(task.evidenceCount).toBe(1);
    expect(task.rollbackTarget).toEqual({
      issueId: "issue-claim-conflict",
      request: { document_ids: ["kb-doc-pricing-v3"], restore_previous: true },
      selectorSummary: "kb-doc-pricing-v3",
    });
  });

  it("renders queue actions for rollback and scoped redo", () => {
    const onRollbackKbIssue = vi.fn();
    const onRedoGateIssue = vi.fn();

    render(
      <ReleaseGateReviewQueue
        onRedoGateIssue={onRedoGateIssue}
        onRollbackKbIssue={onRollbackKbIssue}
        releaseGate={gateWithKbBlocker}
        selectedVersion={selectedVersion}
      />,
    );

    expect(screen.getByText("Release gate review queue")).toBeInTheDocument();
    expect(screen.getByText("KB cleanup")).toBeInTheDocument();
    expect(screen.getByText("kb-doc-pricing-v3 / v3 / active")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Rollback KB/i }));
    fireEvent.click(screen.getByRole("button", { name: /Scoped redo/i }));

    expect(onRollbackKbIssue).toHaveBeenCalledWith("issue-claim-conflict", {
      document_ids: ["kb-doc-pricing-v3"],
      restore_previous: true,
    });
    expect(onRedoGateIssue).toHaveBeenCalledWith("issue-claim-conflict");
  });

  it("hides scoped redo when the report version has no run id", () => {
    render(
      <ReleaseGateReviewQueue
        onRedoGateIssue={() => undefined}
        onRollbackKbIssue={() => undefined}
        releaseGate={gateWithKbBlocker}
        selectedVersion={{ ...selectedVersion, run_id: null }}
      />,
    );

    expect(screen.queryByRole("button", { name: /Scoped redo/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rollback KB/i })).toBeInTheDocument();
  });
});
