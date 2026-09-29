import { AlertTriangle, CheckCircle2, Download, Loader2 } from "lucide-react";
import type { ArtifactRecord, RunComplianceReport } from "../../api/types";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";
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
  const { locale, t } = useTranslation();

  if (!report) {
    return (
      <aside className="qa-panel run-quality-panel">
        <div className="panel-heading-row">
          <h2>{t('compliance.title')}</h2>
          <Loader2 className="spin" size={16} aria-hidden />
        </div>
        <p className="muted-text">{t('compliance.loading')}</p>
      </aside>
    );
  }

  const topFindings = report.findings.slice(0, 5);
  return (
    <aside className={`qa-panel run-quality-panel ${report.status}`}>
      <div className="panel-heading-row">
        <h2>{t('compliance.title')}</h2>
        <button
          className="icon-text-button"
          disabled={isExporting}
          onClick={onExport}
          type="button"
        >
          <Download size={15} aria-hidden />
          {isExporting ? t('common.exporting') : t('common.export')}
        </button>
      </div>
      <div className="metric-grid compact">
        <MetricValue label={t('compliance.status')} value={displayLabel(report.status, locale)} />
        <MetricValue label={t('compliance.findings')} value={String(report.finding_count)} />
        <MetricValue label={t('report.layers.qaBlockers')} value={String(report.blocker_count)} />
        <MetricValue label={t('compliance.redactions')} value={String(report.redaction_count)} />
      </div>
      <div className="run-quality-signals">
        <span className={report.policy.redaction_enabled ? "on" : "off"}>
          {report.policy.redaction_enabled ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          {t('compliance.redaction')}
        </span>
        <span className={report.policy.require_trace_context ? "on" : "off"}>
          {report.policy.require_trace_context ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          {t('compliance.traceContext')}
        </span>
        <span className={report.policy.require_source_urls ? "on" : "off"}>
          {report.policy.require_source_urls ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          {t('compliance.sourceUrls')}
        </span>
      </div>
      {topFindings.length > 0 ? (
        <div className="reflection-review">
          <h3>{t('compliance.findings')}</h3>
          {topFindings.map((finding) => (
            <article className="issue-row reflection-row" key={finding.id}>
              <strong>{displayLabel(finding.severity, locale)}</strong>
              <span>
                {displayLabel(finding.category, locale)}: <SystemMessage message={finding.message} />
              </span>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-text">{t('compliance.noFindings')}</p>
      )}
      {exportArtifact ? (
        <p className="muted-text">
          {exportArtifact.filename} / {exportArtifact.uri}
        </p>
      ) : null}
    </aside>
  );
}
