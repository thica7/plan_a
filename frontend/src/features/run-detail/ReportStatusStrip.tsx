import { FileText, Gauge, ShieldCheck, Target } from "lucide-react";
import type { ReactNode } from "react";
import type { RunDetail as RunDetailRecord } from "../../api/types";
import { StatusPill } from "../../components/ui";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";

export function ReportStatusStrip({
  detail,
  reportSources,
  wordCount,
}: {
  detail: RunDetailRecord;
  reportSources: ReportSourceBundle;
  wordCount: number;
}) {
  const { t } = useTranslation();
  const qualityScore = Math.round(
    (formatRateValue(detail.metrics.verified_source_rate) +
      formatRateValue(detail.metrics.claim_citation_rate) +
      formatRateValue(detail.metrics.schema_pass_rate)) /
      3,
  );
  const blockerCount = detail.qa_findings.filter((finding) => finding.severity === "blocker").length;

  return (
    <section className="report-review-status-strip" aria-label={t('reportStatus.label')}>
      <ReportStatusMetric
        icon={<Gauge size={16} aria-hidden />}
        label={t('reportStatus.quality')}
        value={`${qualityScore || 0}/100`}
        detail={blockerCount ? `${blockerCount} ${t('report.layers.qaBlockers')}` : t('reportStatus.readyForReview')}
        tone={blockerCount ? "warn" : "good"}
      />
      <ReportStatusMetric
        icon={<ShieldCheck size={16} aria-hidden />}
        label={t('reportStatus.sources')}
        value={String(reportSources.sources.length)}
        detail={`${formatRate(detail.metrics.verified_source_rate)} ${t('summary.verified')}`}
      />
      <ReportStatusMetric
        icon={<Target size={16} aria-hidden />}
        label={t('reportStatus.claims')}
        value={String(detail.enterprise_projection?.report_version.claim_ids.length ?? t('common.unavailable'))}
        detail={`${formatRate(detail.metrics.claim_citation_rate)} ${t('reportStatus.cited')}`}
      />
      <ReportStatusMetric
        icon={<FileText size={16} aria-hidden />}
        label={t('reportStatus.reader')}
        value={`${wordCount.toLocaleString()} ${t('reportStatus.words')}`}
        detail={detail.enterprise_projection ? `v${detail.enterprise_projection.report_version.version_number}` : t('reportStatus.runDraft')}
      />
    </section>
  );
}

function formatRate(rate: number | null | undefined) {
  return `${formatRateValue(rate)}%`;
}

function formatRateValue(rate: number | null | undefined) {
  const value = rate ?? 0;
  return Math.round(value > 1 ? value : value * 100);
}

function ReportStatusMetric({
  detail,
  icon,
  label,
  tone = "neutral",
  value,
}: {
  detail: string;
  icon: ReactNode;
  label: string;
  tone?: "good" | "neutral" | "warn";
  value: string;
}) {
  const { locale } = useTranslation();
  return (
    <article className="report-review-status-metric">
      <span className="metric-icon">{icon}</span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <em>{detail}</em>
      </div>
      {tone !== "neutral" ? <StatusPill tone={tone}>{displayLabel(tone, locale)}</StatusPill> : null}
    </article>
  );
}
