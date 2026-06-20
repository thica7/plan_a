import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReportReleaseGate } from "../../api/types";
import { useI18n } from "../../stores/i18n";
import { ReportReviewDesk, buildReleaseIssueAuditRows, buildReleaseIssueRollbackTarget } from "./ReportReviewDesk";

const claimConflictGate = {
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

describe("ReportReviewDesk release gate audit metadata", () => {
  it("renders KB audit trail rows for claim validation issues", () => {
    useI18n.getState().setLocale("en-US");

    render(
      <ReportReviewDesk
        diff={null}
        evidenceById={new Map()}
        isDiffLoading={false}
        onEvidenceQuality={() => undefined}
        onSelectClaim={() => undefined}
        onSelectEvidence={() => undefined}
        previousVersion={null}
        releaseGate={claimConflictGate}
        scopedClaims={[]}
        selectedVersion={null}
      />,
    );

    expect(screen.getByText("Claim issue")).toBeInTheDocument();
    expect(screen.getByText("conflicting_evidence")).toBeInTheDocument();
    expect(screen.getByText("KB document")).toBeInTheDocument();
    expect(screen.getByText("kb-doc-pricing-v3 / v3 / active")).toBeInTheDocument();
    expect(screen.getByText("KB raw source")).toBeInTheDocument();
    expect(screen.getByText("collector-raw-pricing-001")).toBeInTheDocument();
    expect(screen.getByText("Collector run")).toBeInTheDocument();
    expect(screen.getByText("collector-run-1")).toBeInTheDocument();
  });

  it("fires rollback with the KB document selector from release gate metadata", () => {
    const onRollbackKbIssue = vi.fn();

    render(
      <ReportReviewDesk
        diff={null}
        evidenceById={new Map()}
        isDiffLoading={false}
        onEvidenceQuality={() => undefined}
        onRollbackKbIssue={onRollbackKbIssue}
        onSelectClaim={() => undefined}
        onSelectEvidence={() => undefined}
        previousVersion={null}
        releaseGate={claimConflictGate}
        scopedClaims={[]}
        selectedVersion={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Rollback KB evidence/i }));

    expect(onRollbackKbIssue).toHaveBeenCalledWith("issue-claim-conflict", {
      document_ids: ["kb-doc-pricing-v3"],
      restore_previous: true,
    });
  });
  it("builds compact audit rows from release gate metadata", () => {
    const rows = buildReleaseIssueAuditRows(claimConflictGate.issues[0]);

    expect(rows).toContainEqual({ label: "Claim issue", value: "conflicting_evidence" });
    expect(rows).toContainEqual({
      label: "KB document",
      value: "kb-doc-pricing-v3 / v3 / active",
    });
    expect(rows).toContainEqual({ label: "Freshness", value: "86%" });
  });

  it("builds a rollback target from KB audit metadata", () => {
    const target = buildReleaseIssueRollbackTarget(claimConflictGate.issues[0]);

    expect(target).toEqual({
      issueId: "issue-claim-conflict",
      request: { document_ids: ["kb-doc-pricing-v3"], restore_previous: true },
      selectorSummary: "kb-doc-pricing-v3",
    });
  });
});
