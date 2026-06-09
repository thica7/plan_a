import { Download, Send, ShieldCheck } from "lucide-react";
import { useMemo, useState, type MouseEvent } from "react";
import { exportReportVersion, startReportApprovalWorkflow } from "../../api/client";
import type { RunDetail as RunDetailRecord } from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";
import {
  buildCitationLabels,
  collectSourceTokenGroups,
} from "../report/ReportView";
import { ReportSourceTrace } from "../report/ReportSourceTrace";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { RevisionDiff } from "../revisions/RevisionDiff";
import { ReportOutline } from "./ReportOutline";
import { ReportReaderWorkspace } from "./ReportReaderWorkspace";
import { ReportStatusStrip } from "./ReportStatusStrip";

interface RunReportReviewStudioProps {
  detail: RunDetailRecord;
  reportSources: ReportSourceBundle;
}

type ReviewActionState = "idle" | "pending" | "success" | "error";

export function RunReportReviewStudio({ detail, reportSources }: RunReportReviewStudioProps) {
  const markdown = detail.report_md ?? "";
  const wordCount = markdown.trim() ? markdown.trim().split(/\s+/).length : 0;
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const [actionState, setActionState] = useState<ReviewActionState>("idle");
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const reportVersion = detail.enterprise_projection?.report_version ?? null;

  const sourceMap = useMemo(
    () => new Map(reportSources.sources.map((source) => [source.id, source])),
    [reportSources.sources],
  );
  const sourceGroups = useMemo(
    () => collectSourceTokenGroups(markdown, sourceMap, reportSources.aliases),
    [markdown, reportSources.aliases, sourceMap],
  );
  const citedSourceGroups = sourceGroups.filter((group) => group.source);
  const missingSourceGroups = sourceGroups.filter((group) => !group.source);
  const citedSourceIds = useMemo(
    () => new Set(citedSourceGroups.map((group) => group.sourceId)),
    [citedSourceGroups],
  );
  const citationLabels = useMemo(() => buildCitationLabels(sourceGroups), [sourceGroups]);
  const totalCitationCount = sourceGroups.reduce((total, group) => total + group.count, 0);

  function handleSourceJump(event: MouseEvent<HTMLAnchorElement>, href: string) {
    const anchorId = href.startsWith("#") ? href.slice(1) : "";
    if (!anchorId) return;
    const sourceId = anchorId.startsWith("source-")
      ? anchorId.slice("source-".length)
      : anchorId.startsWith("missing-source-")
        ? anchorId.slice("missing-source-".length)
        : null;
    setActiveSourceId(sourceId);
    const target = document.getElementById(anchorId);
    if (!target) return;
    event.preventDefault();
    window.history.replaceState(null, "", `#${anchorId}`);
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function handleRequestApproval() {
    if (!reportVersion) return;
    setActionState("pending");
    setActionMessage("Starting approval workflow...");
    try {
      const response = await startReportApprovalWorkflow({
        report_version_id: reportVersion.id,
        requested_by: "frontend-review-studio",
      });
      setActionState("success");
      setActionMessage(`Approval workflow ${response.status}: ${response.workflow_id}`);
    } catch (err) {
      setActionState("error");
      setActionMessage(err instanceof Error ? err.message : "Unable to request approval");
    }
  }

  async function handleExport(format: "markdown" | "html" | "csv") {
    if (!reportVersion) return;
    setActionState("pending");
    setActionMessage(`Exporting ${format}...`);
    try {
      const response = await exportReportVersion(reportVersion.id, format);
      setActionState("success");
      setActionMessage(`Exported ${response.artifact.filename}`);
    } catch (err) {
      setActionState("error");
      setActionMessage(err instanceof Error ? err.message : "Unable to export report");
    }
  }

  const actionDisabled = !reportVersion || actionState === "pending";

  return (
    <div className="run-report-review-studio">
      <ReportStatusStrip detail={detail} reportSources={reportSources} wordCount={wordCount} />

      <div className="report-review-workspace">
        <ReportOutline markdown={markdown} />

        <ReportReaderWorkspace
          activeSourceId={activeSourceId}
          markdown={markdown}
          onActiveSourceChange={setActiveSourceId}
          reportSources={reportSources}
        />

        <aside className="report-review-inspector">
          <Panel
            className="report-review-source-panel"
            title="Source trace"
            icon={<ShieldCheck size={16} aria-hidden />}
            actions={
              <StatusPill tone={missingSourceGroups.length ? "warn" : "good"}>
                {missingSourceGroups.length ? `${missingSourceGroups.length} missing` : "linked"}
              </StatusPill>
            }
          >
            <ReportSourceTrace
              activeSourceId={activeSourceId}
              citationLabels={citationLabels}
              citedSourceGroups={citedSourceGroups}
              citedSourceIds={citedSourceIds}
              missingSourceGroups={missingSourceGroups}
              onSourceJump={handleSourceJump}
              sources={reportSources.sources}
              totalCitationCount={totalCitationCount}
            />
          </Panel>

          <RevisionDiff compact revisions={detail.revisions} />

          <Panel className="report-review-actions-panel" title="Review actions">
            <button className="primary-action" disabled={actionDisabled} onClick={handleRequestApproval} type="button">
              <Send size={15} aria-hidden />
              Request approval
            </button>
            <div className="report-review-export-grid" aria-label="Report export actions">
              {(["markdown", "html", "csv"] as const).map((format) => (
                <button
                  className="icon-text-button"
                  disabled={actionDisabled}
                  key={format}
                  onClick={() => handleExport(format)}
                  type="button"
                >
                  <Download size={14} aria-hidden />
                  {format.toUpperCase()}
                </button>
              ))}
            </div>
            {!reportVersion ? <p className="muted-line">No enterprise report version is linked to this run.</p> : null}
            {actionMessage ? <p className={`review-action-message ${actionState}`}>{actionMessage}</p> : null}
          </Panel>
        </aside>
      </div>
    </div>
  );
}
