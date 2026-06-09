import { CheckCircle2, Download, FileText, ShieldCheck, XCircle } from "lucide-react";
import type { ArtifactRecord, ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { MetricCard, Panel, StatusPill } from "../../components/ui";
import type { ReportAction, ReportExportFormat } from "./reportOperations";

interface ReportReleasePanelProps {
  isPending: boolean;
  lastExport: ArtifactRecord | null;
  onExport: (format: ReportExportFormat) => void;
  onReportAction: (action: ReportAction) => void;
  releaseGate: ReportReleaseGate | null;
  selectedVersion: ReportVersionRecord | null;
}

export function ReportReleasePanel({
  isPending,
  lastExport,
  onExport,
  onReportAction,
  releaseGate,
  selectedVersion,
}: ReportReleasePanelProps) {
  return (
    <Panel className="report-release-panel" title="Review gate" icon={<ShieldCheck size={16} aria-hidden />}>
      {releaseGate ? (
        <div className="report-gate-summary">
          <StatusPill tone={releaseGate.allowed ? "good" : "bad"}>{releaseGate.status}</StatusPill>
          <strong>{releaseGate.readiness.score} readiness</strong>
          <div className="metric-grid compact">
            <MetricCard label="blockers" value={releaseGate.blocker_count} tone={releaseGate.blocker_count ? "warn" : "good"} />
            <MetricCard label="warnings" value={releaseGate.warn_count} tone={releaseGate.warn_count ? "warn" : "neutral"} />
          </div>
        </div>
      ) : (
        <div className="report-gate-summary">
          <StatusPill tone="neutral">not checked</StatusPill>
          <strong>{selectedVersion ? "Gate result unavailable" : "Select a report version"}</strong>
          <div className="metric-grid compact">
            <MetricCard label="status" value={selectedVersion?.status ?? "n/a"} />
            <MetricCard label="evidence scope" value={selectedVersion?.evidence_ids.length ?? 0} />
          </div>
        </div>
      )}

      <div className="report-action-row" aria-label="Report review actions">
        <button className="icon-text-button" disabled={isPending || !selectedVersion} onClick={() => onReportAction("start_review")} type="button">
          <ShieldCheck size={15} aria-hidden />
          Start review
        </button>
        <button className="icon-text-button" disabled={isPending || selectedVersion?.status !== "in_review"} onClick={() => onReportAction("approve")} type="button">
          <CheckCircle2 size={15} aria-hidden />
          Approve
        </button>
        <button className="icon-text-button" disabled={isPending || selectedVersion?.status !== "in_review"} onClick={() => onReportAction("reject")} type="button">
          <XCircle size={15} aria-hidden />
          Reject
        </button>
        <button className="icon-text-button" disabled={isPending || selectedVersion?.status !== "approved"} onClick={() => onReportAction("publish")} type="button">
          <FileText size={15} aria-hidden />
          Publish
        </button>
      </div>

      <div className="report-export-row" aria-label="Report export actions">
        {(["markdown", "html", "csv"] as const).map((format) => (
          <button className="icon-text-button" disabled={isPending || !selectedVersion} key={format} type="button" onClick={() => onExport(format)}>
            <Download size={15} aria-hidden />
            {format.toUpperCase()}
          </button>
        ))}
      </div>
      {lastExport ? <p className="muted-line">{lastExport.filename} / {lastExport.uri}</p> : null}
    </Panel>
  );
}
