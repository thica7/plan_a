import { FileText, Gauge, ShieldCheck, Target } from "lucide-react";
import type { ReactNode } from "react";
import type { RunDetail as RunDetailRecord } from "../../api/types";
import { StatusPill } from "../../components/ui";
import type { ReportSourceBundle } from "../report/sourceBundle";

export function ReportStatusStrip({
  detail,
  reportSources,
  wordCount,
}: {
  detail: RunDetailRecord;
  reportSources: ReportSourceBundle;
  wordCount: number;
}) {
  const qualityScore = Math.round(
    (formatRateValue(detail.metrics.verified_source_rate) +
      formatRateValue(detail.metrics.claim_citation_rate) +
      formatRateValue(detail.metrics.schema_pass_rate)) /
      3,
  );
  const blockerCount = detail.qa_findings.filter((finding) => finding.severity === "blocker").length;

  return (
    <section className="report-review-status-strip" aria-label="Report review status">
      <ReportStatusMetric
        icon={<Gauge size={16} aria-hidden />}
        label="Quality"
        value={`${qualityScore || 0}/100`}
        detail={blockerCount ? `${blockerCount} blockers` : "Ready for review"}
        tone={blockerCount ? "warn" : "good"}
      />
      <ReportStatusMetric
        icon={<ShieldCheck size={16} aria-hidden />}
        label="Sources"
        value={String(reportSources.sources.length)}
        detail={`${formatRate(detail.metrics.verified_source_rate)} verified`}
      />
      <ReportStatusMetric
        icon={<Target size={16} aria-hidden />}
        label="Claims"
        value={String(detail.enterprise_projection?.report_version.claim_ids.length ?? "n/a")}
        detail={`${formatRate(detail.metrics.claim_citation_rate)} cited`}
      />
      <ReportStatusMetric
        icon={<FileText size={16} aria-hidden />}
        label="Reader"
        value={`${wordCount.toLocaleString()} words`}
        detail={detail.enterprise_projection ? `v${detail.enterprise_projection.report_version.version_number}` : "run draft"}
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
  return (
    <article className="report-review-status-metric">
      <span className="metric-icon">{icon}</span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <em>{detail}</em>
      </div>
      {tone !== "neutral" ? <StatusPill tone={tone}>{tone}</StatusPill> : null}
    </article>
  );
}
