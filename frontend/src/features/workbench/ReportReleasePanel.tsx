import { CheckCircle2, Download, FileText, ShieldCheck, XCircle } from "lucide-react";
import type { ArtifactRecord, ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { ActionButton } from "../../components/interaction/ActionButton";
import { MetricCard, Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
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
  const { t } = useTranslation();
  const pendingReason = "Another report action is already in progress.";
  const noVersionReason = "Select a report version before using report release actions.";
  const inReviewReason = "Move this report version into review before approving or rejecting it.";
  const approvedReason = releaseGate?.blocker_count
    ? `Publish is blocked by ${releaseGate.blocker_count} release gate blocker(s).`
    : "Approve this report version before publishing it.";
  const exportReason = !selectedVersion
    ? "Select a report version before exporting."
    : isPending
      ? pendingReason
      : undefined;

  const actionDisabledReason = (action: ReportAction): string | undefined => {
    if (!selectedVersion) {
      return noVersionReason;
    }
    if (isPending) {
      return pendingReason;
    }
    if ((action === "approve" || action === "reject") && selectedVersion.status !== "in_review") {
      return inReviewReason;
    }
    if (action === "publish") {
      if (selectedVersion.status !== "approved") return approvedReason;
      if (releaseGate && !releaseGate.allowed) return approvedReason;
    }
    return undefined;
  };

  const isActionDisabled = (action: ReportAction) => Boolean(actionDisabledReason(action));

  return (
    <Panel className="report-release-panel" title={t('workbench.reviewGate')} icon={<ShieldCheck size={16} aria-hidden />}>
      {releaseGate ? (
        <div className="report-gate-summary">
          <StatusPill tone={releaseGate.allowed ? "good" : "bad"}>{releaseGate.status}</StatusPill>
          <strong>{releaseGate.readiness.score} {t('workbench.readiness')}</strong>
          <div className="metric-grid compact">
            <MetricCard label={t('workbench.blockers')} value={releaseGate.blocker_count} tone={releaseGate.blocker_count ? "warn" : "good"} />
            <MetricCard label={t('workbench.warnings')} value={releaseGate.warn_count} tone={releaseGate.warn_count ? "warn" : "neutral"} />
          </div>
        </div>
      ) : (
        <div className="report-gate-summary">
          <StatusPill tone="neutral">{t('workbench.notChecked')}</StatusPill>
          <strong>{selectedVersion ? t('workbench.gateResultUnavailable') : t('workbench.selectReportVersion')}</strong>
          <div className="metric-grid compact">
            <MetricCard label={t('compliance.status')} value={selectedVersion?.status ?? "n/a"} />
            <MetricCard label={t('summary.evidenceScope')} value={selectedVersion?.evidence_ids.length ?? 0} />
          </div>
        </div>
      )}

      <div className="report-action-row" aria-label={t('reportStudio.reviewActions')}>
        <ActionButton
          className="icon-text-button"
          authenticity={{
            actionId: "report.release.start-review",
            kind: "mutation",
            description: "starts report approval workflow",
          }}
          disabled={isActionDisabled("start_review")}
          disabledReason={actionDisabledReason("start_review")}
          onClick={() => onReportAction("start_review")}
        >
          <ShieldCheck size={15} aria-hidden />
          {t('workbench.startReview')}
        </ActionButton>
        <ActionButton
          className="icon-text-button"
          authenticity={{
            actionId: "report.release.approve",
            kind: "mutation",
            description: "approves the selected report version",
          }}
          disabled={isActionDisabled("approve")}
          disabledReason={actionDisabledReason("approve")}
          onClick={() => onReportAction("approve")}
        >
          <CheckCircle2 size={15} aria-hidden />
          {t('workbench.approve')}
        </ActionButton>
        <ActionButton
          className="icon-text-button"
          authenticity={{
            actionId: "report.release.reject",
            kind: "mutation",
            description: "rejects the selected report version",
          }}
          disabled={isActionDisabled("reject")}
          disabledReason={actionDisabledReason("reject")}
          onClick={() => onReportAction("reject")}
        >
          <XCircle size={15} aria-hidden />
          {t('workbench.reject')}
        </ActionButton>
        <ActionButton
          className="icon-text-button"
          authenticity={{
            actionId: "report.release.publish",
            kind: "mutation",
            description: "publishes the selected report version",
          }}
          disabled={isActionDisabled("publish")}
          disabledReason={actionDisabledReason("publish")}
          onClick={() => onReportAction("publish")}
        >
          <FileText size={15} aria-hidden />
          {t('workbench.publish')}
        </ActionButton>
      </div>

      <div className="report-export-row" aria-label={t('common.export')}>
        {(["markdown", "html", "csv"] as const).map((format) => (
          <ActionButton
            className="icon-text-button"
            authenticity={{
              actionId: `report.export.${format}`,
              kind: "download",
              description: `exports the selected report as ${format}`,
            }}
            disabled={Boolean(exportReason)}
            disabledReason={exportReason}
            key={format}
            onClick={() => onExport(format)}
          >
            <Download size={15} aria-hidden />
            {format.toUpperCase()}
          </ActionButton>
        ))}
      </div>
      {lastExport ? <p className="muted-line">{lastExport.filename} / {lastExport.uri}</p> : null}
    </Panel>
  );
}
