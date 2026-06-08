import {
  approveReportWorkflow,
  exportReportVersion,
  publishReportVersion,
  rejectReportWorkflow,
  startReportApprovalWorkflow,
} from "../../api/client";
import type { ArtifactRecord } from "../../api/types";

export type ReportAction = "start_review" | "approve" | "reject" | "publish";
export type ReportExportFormat = "markdown" | "html" | "csv";

export async function performReportAction(reportVersionId: string, action: ReportAction) {
  if (action === "start_review") {
    await startReportApprovalWorkflow({
      approver_ids: ["ui-reviewer"],
      report_version_id: reportVersionId,
      requested_by: "ui-reviewer",
      timeout_seconds: 3600,
    });
    return;
  }

  if (action === "approve") {
    await approveReportWorkflow(reportVersionId, {
      approver_id: "ui-reviewer",
      note: "Approved in report studio",
    });
    return;
  }

  if (action === "reject") {
    await rejectReportWorkflow(reportVersionId, {
      approver_id: "ui-reviewer",
      note: "Rejected in report studio",
    });
    return;
  }

  await publishReportVersion(reportVersionId);
}

export async function exportReportArtifact(reportVersionId: string, format: ReportExportFormat): Promise<ArtifactRecord> {
  const result = await exportReportVersion(reportVersionId, format);
  return result.artifact;
}
