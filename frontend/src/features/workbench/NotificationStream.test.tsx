import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { NotificationRecord, ProjectRecord } from "../../api/types";
import { NotificationStream, summarizeNotification } from "./NotificationStream";

const project = {
  id: "project-1",
  workspace_id: "workspace-1",
  name: "AI coding assistants",
} as ProjectRecord;

const releaseGateNotification = {
  id: "notification-release-gate",
  workspace_id: "workspace-1",
  project_id: "project-1",
  notification_type: "release_gate_blocked",
  channel: "in_app",
  severity: "critical",
  status: "queued",
  title: "Report blocked by release gate",
  body: "Claim validation conflict; stale KB evidence",
  resource_type: "report_version",
  resource_id: "report-version-1",
  created_at: "2026-06-20T00:00:00.000Z",
  metadata: {
    readiness_score: 42,
    blocker_count: 1,
    warn_count: 2,
    report_version_id: "report-version-1",
    issues: [
      {
        id: "issue-claim-conflict",
        rule_id: "claim_self_consistency_required",
        rule_name: "Claim self-consistency",
        metadata: {
          evidence_audit_trail: [
            {
              kb_document_id: "kb-doc-pricing-v3",
            },
          ],
        },
      },
    ],
  },
} as NotificationRecord;

describe("NotificationStream", () => {
  it("summarizes release gate metadata into review chips", () => {
    const details = summarizeNotification(releaseGateNotification);

    expect(details.summary).toBe("Claim validation conflict");
    expect(details.chips).toContain("stale KB evidence");
    expect(details.chips).toContain("score 42");
    expect(details.chips).toContain("1 blockers");
    expect(details.chips).toContain("2 warnings");
    expect(details.chips).toContain("report report-version-1");
    expect(details.chips).toContain("issue claim self consistency required");
    expect(details.chips).toContain("KB kb-doc-pricing-v3");
  });

  it("renders release gate metadata chips in the notification stream", () => {
    render(<NotificationStream notifications={[releaseGateNotification]} project={project} />);

    expect(screen.getByText("Report blocked by release gate")).toBeInTheDocument();
    expect(screen.getByText("score 42")).toBeInTheDocument();
    expect(screen.getByText("1 blockers")).toBeInTheDocument();
    expect(screen.getByText("KB kb-doc-pricing-v3")).toBeInTheDocument();
  });
});
