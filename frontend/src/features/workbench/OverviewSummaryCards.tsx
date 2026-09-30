import type { CSSProperties } from "react";
import { FileText, Gauge, ShieldCheck } from "lucide-react";

import type {
  BusinessQAEvaluation,
  ClaimValidationReport,
  CompetitorRecord,
  EvidenceGapReport,
  EvidenceRecord,
  ProjectReadinessScore,
  RedTeamReport,
  ReportReleaseGate,
  ReportVersionRecord,
} from "../../api/types";
import { EmptyState, Panel, StatusPill } from "../../components/ui";
import { formatDate, formatPercent, reportStatusTone } from "./format";
import { useTranslation } from "../../stores/i18n";
import { displayLabel } from "../../i18n/display";
import { SystemMessage } from '../../i18n/SystemMessage';


export function RunQualityPanel({
  acceptedRate,
  claimValidation,
  evidence,
  evidenceGaps,
  qaEvaluation,
  readiness,
  redTeam,
  verifiedRate,
}: {
  acceptedRate: number;
  claimValidation: ClaimValidationReport | null;
  evidence: EvidenceRecord[];
  evidenceGaps: EvidenceGapReport | null;
  qaEvaluation: BusinessQAEvaluation | null;
  readiness: ProjectReadinessScore | null;
  redTeam: RedTeamReport | null;
  verifiedRate: number;
}) {
  const { t, locale } = useTranslation();
  const score = readiness?.score ?? Math.round(verifiedRate * 100);
  const blockerCount =
    (qaEvaluation?.blocker_count ?? 0) +
    (claimValidation?.blocker_count ?? 0) +
    (evidenceGaps?.critical_count ?? 0) +
    (redTeam?.high_severity_count ?? 0);
  const qualityRows = [
    { label: t('workbench.sourceQuality'), value: verifiedRate },
    { label: t("summary.coverage"), value: readiness?.coverage_score ?? null },
    { label: t('workbench.schemaFit'), value: readiness?.claim_score ?? null },
    { label: t('workbench.citationRate'), value: acceptedRate },
    { label: t('workbench.consistency'), value: claimValidation?.self_consistency_score ?? null },
  ];

  return (
    <Panel
      className="workbench-card run-quality-panel"
      title={t("workbench.runQuality")}
      icon={<Gauge size={16} aria-hidden />}
      actions={<StatusPill tone={blockerCount > 0 ? "warn" : "good"}>{blockerCount ? `${blockerCount} ${t('workbench.blockers')}` : t("workbench.good")}</StatusPill>}
    >
      <div className="run-quality-body">
        <div
          className="quality-score-ring"
          style={{ "--quality-score-angle": `${Math.max(0, Math.min(100, score)) * 3.6}deg` } as CSSProperties}
        >
          <strong>{score || displayLabel('n/a', locale)}</strong>
          <span>/100</span>
        </div>
        <div className="quality-breakdown">
          {qualityRows.map((row) => (
            <QualityLine key={row.label} label={row.label} value={row.value} />
          ))}
        </div>
      </div>
      <p className="quality-summary">
        {readiness?.summary ? <SystemMessage message={readiness.summary} /> :
          (evidence.length
            ? `${evidence.length} ${t('workbench.evidenceProjected')}`
            : t('workbench.runAnalysisHint'))}
      </p>
    </Panel>
  );
}

export function CoverageHeatmap({
  competitors,
  evidence,
}: {
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
}) {
  const { t, locale } = useTranslation();
  const dimensions = [...new Set(evidence.map((item) => item.dimension).filter(Boolean))].slice(0, 6);
  const visibleCompetitors = competitors.slice(0, 7);
  const coverage = new Map<string, number>();
  for (const item of evidence) {
    const key = `${item.competitor_id}:${item.dimension}`;
    coverage.set(key, (coverage.get(key) ?? 0) + 1);
  }

  return (
    <Panel
      className="workbench-card coverage-heatmap-panel"
      title={t('workbench.coverageHeatmap')}
      icon={<ShieldCheck size={16} aria-hidden />}
      actions={<HeatmapLegend />}
    >
      {dimensions.length > 0 && visibleCompetitors.length > 0 ? (
        <div className="coverage-table" style={{ "--coverage-cols": dimensions.length } as CSSProperties}>
          <span className="coverage-corner">{t('workbench.competitors')}</span>
          {dimensions.map((dimension) => (
            <strong key={dimension} title={dimension}>
              {displayLabel(dimension, locale)}
            </strong>
          ))}
          {visibleCompetitors.map((competitor) => (
            <CoverageRow competitor={competitor} coverage={coverage} dimensions={dimensions} key={competitor.id} />
          ))}
        </div>
      ) : (
        <SummaryEmpty title={t('workbench.noCoverageMatrix')} description={t('workbench.coverageHint')} />
      )}
    </Panel>
  );
}

export function ReportReviewStudioPanel({
  releaseGate,
  selectedVersion,
}: {
  releaseGate: ReportReleaseGate | null;
  selectedVersion: ReportVersionRecord | null;
}) {
  const { t, locale } = useTranslation();
  return (
    <Panel
      className="workbench-card report-review-studio-panel"
      title={t('workbench.reportReviewStudio')}
      icon={<FileText size={16} aria-hidden />}
      actions={
        selectedVersion ? (
          <StatusPill tone={reportStatusTone(selectedVersion.status)}>{displayLabel(selectedVersion.status, locale)}</StatusPill>
        ) : null
      }
    >
      {selectedVersion ? (
        <div className="report-studio-summary">
          <div className="report-cover-preview">
            <span>CompetiScope</span>
            <strong>{t('workbench.competitiveIntelligenceReport')}</strong>
            <em>v{selectedVersion.version_number}</em>
          </div>
          <div className="report-review-facts">
            <strong>{t('workbench.reportVersion')} {selectedVersion.version_number}</strong>
            <span>{t('workbench.generated')} {formatDate(selectedVersion.created_at)}</span>
            <span>{selectedVersion.claim_ids.length} {t('workbench.claims')}</span>
            <span>{selectedVersion.evidence_ids.length} {t('workbench.evidenceLinks')}</span>
            <span>{selectedVersion.report_md.length.toLocaleString(locale)} {t('common.characters')}</span>
            <em className={releaseGate?.allowed ? "ready" : "hold"}>
              {releaseGate ? `${releaseGate.status === 'blocked' ? t('workbench.releaseConditionsBlocked') : displayLabel(releaseGate.status, locale)} / ${releaseGate.blocker_count} ${t('workbench.blockers')}` : t('workbench.releaseGatePending')}
            </em>
          </div>
        </div>
      ) : (
        <EmptyState title={t('workbench.noReportVersion')} />
      )}
    </Panel>
  );
}

function CoverageRow({
  competitor,
  coverage,
  dimensions,
}: {
  competitor: CompetitorRecord;
  coverage: Map<string, number>;
  dimensions: string[];
}) {
  const { t, locale } = useTranslation();
  return (
    <>
      <em title={competitor.name}>{competitor.name}</em>
      {dimensions.map((dimension) => {
        const count = coverage.get(`${competitor.id}:${dimension}`) ?? 0;
        const score = coverageScore(count);
        const level = count >= 5 ? "high" : count >= 2 ? "mid" : count === 1 ? "low" : "empty";
        return (
          <span
            className={`coverage-cell ${level}`}
            key={`${competitor.id}-${dimension}`}
            title={`${competitor.name} / ${displayLabel(dimension, locale)}: ${count} ${t('workbench.source')}`}
          >
            {score ? `${score}%` : "-"}
          </span>
        );
      })}
    </>
  );
}

function HeatmapLegend() {
  const { t } = useTranslation();
  return (
    <span className="heatmap-status-legend">
      <i className="good" />
      {t("workbench.good")}
      <i className="mid" />
      {t('workbench.medium')}
      <i className="low" />
      {t('workbench.low')}
    </span>
  );
}

function QualityLine({ label, value }: { label: string; value: number | null }) {
  const { locale } = useTranslation();
  const normalized = normalizeScore(value);
  return (
    <span className={normalized === null ? "empty" : undefined}>
      <em>{label}</em>
      <b>
        <i style={{ width: `${Math.round((normalized ?? 0) * 100)}%` }} />
      </b>
      <strong>{normalized === null ? displayLabel('n/a', locale) : formatPercent(normalized)}</strong>
    </span>
  );
}

function SummaryEmpty({ description, title }: { description: string; title: string }) {
  return (
    <div className="summary-empty">
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

function coverageScore(count: number) {
  if (count >= 5) return 92;
  if (count >= 3) return 82;
  if (count === 2) return 68;
  if (count === 1) return 46;
  return 0;
}

function normalizeScore(value: number | null) {
  if (value === null || Number.isNaN(value)) return null;
  return Math.max(0, Math.min(1, value > 1 ? value / 100 : value));
}
