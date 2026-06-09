import { Database, FileText, GitBranch } from "lucide-react";
import type { RunDetail as RunDetailRecord } from "../../api/types";
import { MetricValue } from "./MetricValue";
import { useTranslation } from '../../stores/i18n';

interface RunSummaryStripProps {
  citedClaimRate: number;
  detail: RunDetailRecord;
  sourceCoverageRate: number;
  verifiedSourceRate: number;
}

export function RunSummaryStrip({
  citedClaimRate,
  detail,
  sourceCoverageRate,
  verifiedSourceRate,
}: RunSummaryStripProps) {
  const { t } = useTranslation();
  return (
    <section className="run-command-grid">
      <article className="panel run-summary-panel">
        <div className="panel-heading-row">
          <h2>{t('summary.runOverview')}</h2>
          <span className="muted-text">{detail.id}</span>
        </div>
        <div className="metric-grid compact">
          <MetricValue label={t('reportStatus.sources')} value={String(detail.raw_sources.length)} />
          <MetricValue label={t('summary.verified')} value={`${verifiedSourceRate}%`} />
          <MetricValue label={t('summary.coverage')} value={`${sourceCoverageRate}%`} />
          <MetricValue label={t('summary.citedClaims')} value={`${citedClaimRate}%`} />
          <MetricValue label={t('summary.qaIssues')} value={String(detail.qa_findings.length)} />
          <MetricValue label="Spans" value={String(detail.metrics.total_spans)} />
        </div>
      </article>
      <article className="panel run-inspector-panel">
        <div className="inspector-row">
          <Database size={17} aria-hidden />
          <div>
            <strong>Evidence scope</strong>
            <span>{detail.raw_sources.length} raw sources / {detail.plan.competitors.length} competitors</span>
          </div>
        </div>
        <div className="inspector-row">
          <GitBranch size={17} aria-hidden />
          <div>
            <strong>Agent graph</strong>
            <span>{detail.plan.task_decomposition.length} adaptive tasks / {detail.revisions.length} redo rounds</span>
          </div>
        </div>
        <div className="inspector-row">
          <FileText size={17} aria-hidden />
          <div>
            <strong>Report</strong>
            <span>{detail.report_md ? `${detail.report_md.length} characters` : "draft pending"}</span>
          </div>
        </div>
      </article>
    </section>
  );
}
