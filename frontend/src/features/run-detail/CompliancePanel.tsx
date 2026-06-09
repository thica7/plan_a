import { AlertTriangle, CheckCircle2, Download, Loader2 } from "lucide-react";
import type { ArtifactRecord, RunComplianceReport } from "../../api/types";
import { MetricValue } from "./MetricValue";

interface CompliancePanelProps {
  exportArtifact: ArtifactRecord | null;
  isExporting: boolean;
  onExport: () => void;
  report: RunComplianceReport | null;
}

export function CompliancePanel({
  exportArtifact,
  isExporting,
  onExport,
  report,
}: CompliancePanelProps) {
  if (!report) {
    return (
      <aside className="qa-panel run-quality-panel">
        <div className="panel-heading-row">
          <h2>Compliance</h2>
          <Loader2 className="spin" size={16} aria-hidden />
        </div>
        <p className="muted-text">Loading compliance report.</p>
      </aside>
    );
  }

  const topFindings = report.findings.slice(0, 5);
  return (
    <aside className={`qa-panel run-quality-panel ${report.status}`}>
      <div className="panel-heading-row">
        <h2>Compliance</h2>
        <button
          className="icon-text-button"
          disabled={isExporting}
          onClick={onExport}
          type="button"
        >
          <Download size={15} aria-hidden />
          {isExporting ? "Exporting" : "Export"}
        </button>
      </div>
      <div className="metric-grid compact">
        <MetricValue label="Status" value={report.status} />
        <MetricValue label="Findings" value={String(report.finding_count)} />
        <MetricValue label="Blockers" value={String(report.blocker_count)} />
        <MetricValue label="Redactions" value={String(report.redaction_count)} />
      </div>
      <div className="run-quality-signals">
        <span className={report.policy.redaction_enabled ? "on" : "off"}>
          {report.policy.redaction_enabled ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          Redaction
        </span>
        <span className={report.policy.require_trace_context ? "on" : "off"}>
          {report.policy.require_trace_context ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          Trace context
        </span>
        <span className={report.policy.require_source_urls ? "on" : "off"}>
          {report.policy.require_source_urls ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          Source URLs
        </span>
      </div>
      {topFindings.length > 0 ? (
        <div className="reflection-review">
          <h3>Findings</h3>
          {topFindings.map((finding) => (
            <article className="issue-row reflection-row" key={finding.id}>
              <strong>{finding.severity}</strong>
              <span>
                {finding.category}: {finding.message}
              </span>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-text">No compliance findings.</p>
      )}
      {exportArtifact ? (
        <p className="muted-text">
          {exportArtifact.filename} / {exportArtifact.uri}
        </p>
      ) : null}
    </aside>
  );
}
