import { Download, Send, ShieldCheck } from "lucide-react";
import { useMemo, useState, type MouseEvent } from "react";
import { useReportAnchorJump } from '../report/reportAnchors';
import { useTranslation } from '../../stores/i18n';
import { exportReportVersion, startReportApprovalWorkflow } from "../../api/client";
import type { RunDetail as RunDetailRecord } from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";
import {
  buildCitationLabels,
  collectSourceTokenGroups,
  selectReportLayerMarkdown,
  type ReportViewLayer,
} from "../report/ReportView";
import { ReportSourceTrace } from "../report/ReportSourceTrace";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { RevisionDiff } from "../revisions/RevisionDiff";
import { ReportOutline } from "./ReportOutline";
import { ReportReaderWorkspace } from "./ReportReaderWorkspace";
import { ReportStatusStrip } from "./ReportStatusStrip";
import { displayLabel } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";

interface RunReportReviewStudioProps {
  detail: RunDetailRecord;
  reportSources: ReportSourceBundle;
}

type ReviewActionState = "idle" | "pending" | "success" | "error";
type ReviewActionFeedback =
  | { type: "approval-pending" }
  | { type: "approval-success"; status: string; workflowId: string }
  | { type: "export-pending"; format: string }
  | { type: "export-success"; filename: string }
  | { type: "approval-error" | "export-error" }
  | { type: "system-error"; message: string };

export function RunReportReviewStudio({ detail, reportSources }: RunReportReviewStudioProps) {
  const { locale, t } = useTranslation();
  const jump = useReportAnchorJump();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const markdown = detail.report_md ?? "";
  const [activeLayer, setActiveLayer] = useState<ReportViewLayer>("report");
  const selectedMarkdown = selectReportLayerMarkdown(detail.report_artifact, markdown, activeLayer, {
    qa: t("report.layers.qa"),
    warnings: t("report.layers.qaWarnings"),
    blockers: t("report.layers.qaBlockers"),
  });
  const wordCount = locale === "zh-CN"
    ? Array.from(selectedMarkdown.replace(/\s/g, "")).length
    : selectedMarkdown.trim() ? selectedMarkdown.trim().split(/\s+/).length : 0;
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const [actionState, setActionState] = useState<ReviewActionState>("idle");
  const [actionFeedback, setActionFeedback] = useState<ReviewActionFeedback | null>(null);
  const reportVersion = detail.enterprise_projection?.report_version ?? null;

  const sourceMap = useMemo(
    () => new Map(reportSources.sources.map((source) => [source.id, source])),
    [reportSources.sources],
  );
  const sourceGroups = useMemo(
    () => collectSourceTokenGroups(selectedMarkdown, sourceMap, reportSources.aliases),
    [selectedMarkdown, reportSources.aliases, sourceMap],
  );
  const citedSourceGroups = sourceGroups.filter((group) => group.source);
  const missingSourceGroups = sourceGroups.filter((group) => !group.source);
  const citedSourceIds = useMemo(
    () => new Set(citedSourceGroups.map((group) => group.sourceId)),
    [citedSourceGroups],
  );
  const citationLabels = useMemo(() => buildCitationLabels(sourceGroups, t('report.missing')), [sourceGroups, locale, t]);
  const totalCitationCount = sourceGroups.reduce((total, group) => total + group.count, 0);

  function handleSourceJump(event: MouseEvent<HTMLAnchorElement>, href: string) {
    const anchorId = href.startsWith("#") ? href.slice(1) : "";
    if (!anchorId) return;
    const sourceId = anchorId.startsWith("source-")
      ? anchorId.slice("source-".length)
      : anchorId.startsWith("missing-source-")
        ? anchorId.slice("missing-source-".length)
        : null;
    jump(event, href, () => handleActiveSourceChange(sourceId));
  }

  function handleActiveSourceChange(sourceId: string | null) {
    setActiveSourceId(sourceId);
    if (sourceId) setDetailsOpen(true);
  }

  async function handleRequestApproval() {
    if (!reportVersion) return;
    setActionState("pending");
    setActionFeedback({ type: "approval-pending" });
    try {
      const response = await startReportApprovalWorkflow({
        report_version_id: reportVersion.id,
        requested_by: "frontend-review-studio",
      });
      setActionState("success");
      setActionFeedback({ type: "approval-success", status: response.status, workflowId: response.workflow_id });
    } catch (err) {
      setActionState("error");
      setActionFeedback(err instanceof Error ? { type: "system-error", message: err.message } : { type: "approval-error" });
    }
  }

  async function handleExport(format: "markdown" | "html" | "csv") {
    if (!reportVersion) return;
    setActionState("pending");
    setActionFeedback({ type: "export-pending", format });
    try {
      const response = await exportReportVersion(reportVersion.id, format);
      setActionState("success");
      setActionFeedback({ type: "export-success", filename: response.artifact.filename });
    } catch (err) {
      setActionState("error");
      setActionFeedback(err instanceof Error ? { type: "system-error", message: err.message } : { type: "export-error" });
    }
  }

  function renderActionFeedback() {
    if (!actionFeedback) return null;
    switch (actionFeedback.type) {
      case "approval-pending":
        return t('reportStudio.startingApproval');
      case "approval-success":
        return `${t('reportStudio.approvalWorkflow')} ${displayLabel(actionFeedback.status, locale)}: ${actionFeedback.workflowId}`;
      case "export-pending":
        return `${t('common.exporting')} ${actionFeedback.format.toUpperCase()}`;
      case "export-success":
        return `${t('reportStudio.exported')} ${actionFeedback.filename}`;
      case "approval-error":
        return t('reportStudio.unableToApprove');
      case "export-error":
        return t('reportStudio.unableToExport');
      case "system-error":
        return <SystemMessage message={actionFeedback.message} />;
    }
  }

  const actionDisabled = !reportVersion || actionState === "pending";

  return (
    <div className="run-report-review-studio">
      <ReportStatusStrip detail={detail} reportSources={reportSources} wordCount={wordCount} />

      <div className={`report-review-workspace${detailsOpen ? ' details-open' : ''}`}>
        <ReportOutline markdown={selectedMarkdown} hidden={!detailsOpen} />

        <ReportReaderWorkspace
          activeSourceId={activeSourceId}
          activeLayer={activeLayer}
          markdown={markdown}
          onActiveLayerChange={setActiveLayer}
          onActiveSourceChange={handleActiveSourceChange}
          detailsOpen={detailsOpen}
          onDetailsToggle={() => setDetailsOpen(open => !open)}
          reportArtifact={detail.report_artifact ?? null}
          reportSources={reportSources}
        />

        <aside className="report-review-inspector">
          <div hidden={!detailsOpen}>
          <Panel
            className="report-review-source-panel"
            title={t('reportStudio.sourceTrace')}
            icon={<ShieldCheck size={16} aria-hidden />}
            actions={
              <StatusPill tone={missingSourceGroups.length ? "warn" : "good"}>
                {missingSourceGroups.length ? `${missingSourceGroups.length} ${t('report.missing')}` : t('report.linked')}
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
          </div>

          <Panel className="report-review-actions-panel" title={t('reportStudio.reviewActions')}>
            <button className="primary-action" disabled={actionDisabled} onClick={handleRequestApproval} type="button">
              <Send size={15} aria-hidden />
              {t('reportStudio.requestApproval')}
            </button>
            <div className="report-review-export-grid" aria-label={t('reportStudio.exportActions')}>
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
            {!reportVersion ? <p className="muted-line">{t('reportStudio.noEnterpriseReport')}</p> : null}
            {actionFeedback ? <p className={`review-action-message ${actionState}`}>{renderActionFeedback()}</p> : null}
          </Panel>
        </aside>
      </div>
    </div>
  );
}
