import { AlertTriangle, CalendarClock, Layers } from "lucide-react";
import type { CSSProperties } from "react";

import type {
  AuditLogRecord,
  BusinessQAEvaluation,
  ClaimValidationReport,
  CompetitorRecord,
  CompetitorScoreReport,
  DecisionReplayReport,
  EvidenceGapReport,
  EvidenceRecord,
  EvalOpsReport,
  QualityAgentMatrix,
  RedTeamReport,
  ReportVersionRecord,
  TraceSpan,
} from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";
import { formatDate } from "./format";
import { useTranslation, type Locale } from "../../stores/i18n";
import { displayLabel, displayScope } from '../../i18n/display';
import { SystemMessage } from '../../i18n/SystemMessage';

export function QaBlockersPanel({
  claimValidation,
  evidenceGaps,
  matrix,
  qaEvaluation,
  redTeam,
}: {
  claimValidation: ClaimValidationReport | null;
  evidenceGaps: EvidenceGapReport | null;
  matrix: QualityAgentMatrix | null;
  qaEvaluation: BusinessQAEvaluation | null;
  redTeam: RedTeamReport | null;
}) {
  const { t, locale } = useTranslation();
  const rows = [
    ...(qaEvaluation?.findings ?? []).map((finding) => ({
      id: finding.id,
      severity: finding.severity,
      type: finding.rule_name,
      description: finding.message,
      scope: `${finding.competitor_name ?? t('workbench.projects')}${finding.dimension ? ` / ${displayLabel(finding.dimension, locale)}` : ""}`,
    })),
    ...(evidenceGaps?.gaps ?? []).slice(0, 4).map((gap) => ({
      id: gap.id,
      severity: gap.severity,
      type: gap.gap_type,
      description: gap.message,
      scope: `${gap.competitor_name ?? t('workbench.projects')}${gap.dimension ? ` / ${displayLabel(gap.dimension, locale)}` : ""}`,
    })),
  ].slice(0, 7);
  return (
    <Panel
      className="qa-blocker-panel"
      title={t("workbench.qaBlockers")}
      icon={<AlertTriangle size={16} aria-hidden />}
      actions={<StatusPill tone={rows.length ? "warn" : "good"}>{rows.length}</StatusPill>}
    >
      <div className="qa-blocker-table">
        <div className="qa-blocker-head">
          <span>{t("workbench.severity")}</span>
          <span>{t('workbench.type')}</span>
          <span>{t("workbench.description")}</span>
          <span>{t("workbench.scope")}</span>
        </div>
        {rows.map((row) => (
          <article className="qa-blocker-row" key={row.id}>
            <StatusPill tone={row.severity === "blocker" || row.severity === "critical" || row.severity === "high" ? "bad" : "warn"}>
              {displayLabel(row.severity, locale)}
            </StatusPill>
            <SystemMessage message={row.type} />
            <strong><SystemMessage message={row.description} /></strong>
            <em>{row.scope}</em>
          </article>
        ))}
      </div>
      {rows.length === 0 ? <p className="muted-line">{t("workbench.noActiveBlockers")}</p> : null}
      <div className="auto-redo-strip">
        <span>{t('workbench.autoRedoSuggestions')}</span>
        <strong>{matrix?.entries.reduce((total, entry) => total + entry.suggested_redos.length, 0) ?? 0}</strong>
        <span>{t('workbench.redTeam')} {redTeam?.finding_count ?? 0}</span>
        <span>{t('workbench.claimIssues')} {claimValidation?.issue_count ?? 0}</span>
      </div>
    </Panel>
  );
}

export function TraceTimelinePanel({
  auditLogs,
  decisionReplay,
  evalOps,
  selectedVersion,
  traceSpans,
}: {
  auditLogs: AuditLogRecord[];
  decisionReplay: DecisionReplayReport | null;
  evalOps: EvalOpsReport | null;
  selectedVersion: ReportVersionRecord | null;
  traceSpans: TraceSpan[];
}) {
  const { t, locale } = useTranslation();
  const rows = buildTimelineRows({ auditLogs, decisionReplay, evalOps, selectedVersion, traceSpans }, locale, t);
  const kbWarmStart = buildKbWarmStartSummary(traceSpans);
  const stages = [
    t('workbench.planning'),
    t('workbench.discovery'),
    t('workbench.capture'),
    t('workbench.extraction'),
    t('workbench.analysis'),
    t('workbench.qualityGate'),
    t('workbench.reportTab'),
    t('workbench.review'),
  ];
  const completedStages = selectedVersion ? 7 : Math.min(6, Math.max(1, Math.ceil(rows.length / 2)));
  return (
    <Panel
      className="workbench-card trace-timeline-panel"
      title={t("workbench.traceTimeline")}
      icon={<CalendarClock size={16} aria-hidden />}
      actions={<StatusPill tone={decisionReplay?.blocker_count ? "warn" : "good"}>{rows.length}</StatusPill>}
    >
      <div className="trace-stepper" style={{ "--completed-stages": completedStages } as CSSProperties}>
        {stages.map((stage, index) => (
          <span className={index < completedStages ? "complete" : undefined} key={stage}>
            <i aria-hidden>{index < completedStages ? "" : index + 1}</i>
            <strong>{stage}</strong>
          </span>
        ))}
      </div>
      <div className="trace-metric-row">
        <span>
          {t('workbench.events')} <strong>{decisionReplay?.events.length ?? rows.length}</strong>
        </span>
        <span>
          {t('workbench.spans')} <strong>{traceSpans.length}</strong>
        </span>
        <span>
          {t('workbench.cost')} <strong>{evalOps ? `$${evalOps.cost_per_report_usd.toFixed(2)}` : displayLabel('n/a', locale)}</strong>
        </span>
        <span>
          {t('runQuality.gate')} <strong>{displayLabel(evalOps?.regression_gate_status ?? "n/a", locale)}</strong>
        </span>
      </div>
      {kbWarmStart.spanCount > 0 ? (
        <div className="kb-warm-start-strip" aria-label={t('workbench.kbDiagnostics')}>
          <div className="kb-warm-start-metrics">
            <span>
              {t('workbench.kbHits')} <strong>{kbWarmStart.hitCount}</strong>
            </span>
            <span>
              {t('workbench.acceptedCol')} <strong>{kbWarmStart.acceptedCount}</strong>
            </span>
            <span>
              {t('workbench.rejected')} <strong>{kbWarmStart.rejectedCount}</strong>
            </span>
            <span>
              {t('workbench.spans')} <strong>{kbWarmStart.spanCount}</strong>
            </span>
          </div>
          {kbWarmStart.topRejections.length > 0 ? (
            <div className="kb-warm-start-rejections">
              {kbWarmStart.topRejections.map((item) => (
                <span key={item.reason} title={`${item.reason}: ${item.examples.join(", ")}`}>
                  <strong>{displayLabel(item.reason, locale)}</strong>
                  <em>{item.count}</em>
                  {item.examples[0] ? <code>{item.examples[0]}</code> : null}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="trace-event-list">
        {rows.slice(0, 4).map((row) => (
          <article key={row.id}>
            <div>
              <strong>{row.title}</strong>
              <span>{row.meta}{row.message ? <> / <SystemMessage message={row.message} /></> : null}</span>
            </div>
            <time dateTime={row.time}>{formatDate(row.time)}</time>
          </article>
        ))}
      </div>
    </Panel>
  );
}

export interface KbWarmStartSummary {
  acceptedCount: number;
  hitCount: number;
  rejectedCount: number;
  spanCount: number;
  topRejections: Array<{ count: number; examples: string[]; reason: string }>;
}

export function buildKbWarmStartSummary(traceSpans: TraceSpan[]): KbWarmStartSummary {
  const summary: KbWarmStartSummary = {
    acceptedCount: 0,
    hitCount: 0,
    rejectedCount: 0,
    spanCount: 0,
    topRejections: [],
  };
  const rejectionStats = new Map<string, { count: number; examples: string[] }>();

  for (const span of traceSpans) {
    if (span.name !== "rag_kb_warm_start") continue;
    summary.spanCount += 1;
    summary.hitCount += metadataNumber(span, "hit_count") ?? 0;
    summary.acceptedCount += metadataNumber(span, "source_count") ?? 0;
    const rejected = metadataNumber(span, "rejection_count") ?? 0;
    summary.rejectedCount += rejected;

    const output = parseTraceOutput(span);
    const rejections = Array.isArray(output?.rejections) ? output.rejections : [];
    for (const rejection of rejections) {
      if (!isRecord(rejection)) continue;
      addRejectionStat(
        rejectionStats,
        metadataText(rejection, "reason") ?? "rejected",
        rejectionLocator(rejection),
        1,
      );
    }
    if (rejections.length === 0 && rejected > 0) {
      addRejectionStat(
        rejectionStats,
        metadataText(span.metadata, "top_rejection_reason") ?? "rejected",
        "",
        rejected,
      );
    }
  }

  summary.topRejections = [...rejectionStats.entries()]
    .map(([reason, stats]) => ({ reason, ...stats }))
    .sort((left, right) => right.count - left.count || left.reason.localeCompare(right.reason))
    .slice(0, 3);
  return summary;
}

interface TimelineRow {
  id: string;
  title: string;
  meta: string;
  time: string;
  message?: string;
}

function buildTimelineRows({
  auditLogs,
  decisionReplay,
  evalOps,
  selectedVersion,
  traceSpans,
}: {
  auditLogs: AuditLogRecord[];
  decisionReplay: DecisionReplayReport | null;
  evalOps: EvalOpsReport | null;
  selectedVersion: ReportVersionRecord | null;
  traceSpans: TraceSpan[];
}, locale: Locale, t: (key: string) => string): TimelineRow[] {
  if (decisionReplay?.events.length) {
    return decisionReplay.events.slice(-7).reverse().map((event) => ({
      id: event.id,
      title: displayLabel(event.event_type, locale),
      meta: `${displayLabel(event.agent ?? "system", locale)}${event.subagent ? `/${displayScope(event.subagent, locale)}` : ""}`,
      message: event.message,
      time: event.created_at,
    }));
  }

  if (traceSpans.length) {
    return traceSpans.slice(-7).reverse().map((span) => ({
      id: span.id,
      title: `${displayLabel(span.kind, locale)} / ${displayLabel(span.name, locale)}`,
      meta: `${displayLabel(span.agent, locale)}${span.subagent ? `/${displayScope(span.subagent, locale)}` : ""} / ${displayLabel(span.status, locale)} / ${span.duration_ms} ${t('common.milliseconds')}`,
      time: span.created_at,
    }));
  }

  return [
    selectedVersion
      ? {
          id: `report-${selectedVersion.id}`,
          title: `${t('workbench.reportVersion')} ${selectedVersion.version_number} ${displayLabel(selectedVersion.status, locale)}`,
          meta: `${selectedVersion.claim_ids.length} ${t('workbench.claims')} / ${selectedVersion.evidence_ids.length} ${t('workbench.evidence')}`,
          time: selectedVersion.created_at,
        }
      : null,
    evalOps
      ? {
          id: "evalops",
          title: `${t('workbench.benchmark')} ${displayLabel(evalOps.regression_gate_status, locale)}`,
          meta: `${evalOps.run_count} ${t('workbench.runUsage')} / ${t('runQuality.reportQuality')} ${evalOps.report_quality_score}`,
          time: evalOps.generated_at,
        }
      : null,
    ...auditLogs.slice(0, 5).map((log) => ({
      id: log.id,
      title: displayLabel(log.action, locale),
      meta: `${displayLabel(log.resource_type, locale)} / ${displayLabel(log.actor_type, locale)}${log.actor_id ? `:${log.actor_id}` : ""}`,
      time: log.created_at,
    })),
  ].filter((row): row is { id: string; title: string; meta: string; time: string } => Boolean(row));
}

function addRejectionStat(
  stats: Map<string, { count: number; examples: string[] }>,
  reason: string,
  example: string,
  count: number,
) {
  const key = reason.trim() || "rejected";
  const current = stats.get(key) ?? { count: 0, examples: [] };
  current.count += count;
  if (example && !current.examples.includes(example) && current.examples.length < 3) {
    current.examples.push(example);
  }
  stats.set(key, current);
}

function parseTraceOutput(span: TraceSpan): Record<string, unknown> | null {
  const text = span.full_output || span.output_preview;
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function rejectionLocator(item: Record<string, unknown>) {
  return (
    metadataText(item, "document_id") ??
    metadataText(item, "chunk_id") ??
    metadataText(item, "source_id") ??
    metadataText(item, "url") ??
    ""
  );
}

function metadataNumber(span: TraceSpan, key: string): number | null {
  const value = span.metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metadataText(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function CompetitorsOverviewTable({
  competitorScores,
  competitors,
  evidence,
}: {
  competitorScores: CompetitorScoreReport | null;
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
}) {
  const { t, locale } = useTranslation();
  const evidenceCounts = new Map<string, number>();
  evidence.forEach((item) => evidenceCounts.set(item.competitor_id, (evidenceCounts.get(item.competitor_id) ?? 0) + 1));
  const scoreByCompetitor = new Map(competitorScores?.scores.map((score) => [score.competitor_id, score]) ?? []);
  return (
    <Panel className="competitor-overview-table" title={t("workbench.competitors")} icon={<Layers size={16} aria-hidden />}>
      <div className="compact-data-table">
        <div className="compact-data-head">
          <span>{t('newRun.competitors')}</span>
          <span>{t('runHeader.layer')}</span>
          <span>{t('summary.coverage')}</span>
          <span>{t('workbench.evidence')}</span>
          <span>{t('workbench.score')}</span>
        </div>
        {competitors.slice(0, 8).map((competitor) => {
          const score = scoreByCompetitor.get(competitor.id);
          return (
            <article className="compact-data-row" key={competitor.id}>
              <strong>{competitor.name}</strong>
              <span>{displayLabel(competitor.layer, locale)}</span>
              <span>
                <ProgressBar value={score?.coverage_score ?? 0} />
              </span>
              <span>{evidenceCounts.get(competitor.id) ?? 0}</span>
              <span>{score?.total_score ?? displayLabel('n/a', locale)}</span>
            </article>
          );
        })}
      </div>
    </Panel>
  );
}

function ProgressBar({ value }: { value: number }) {
  const normalized = Math.max(0, Math.min(1, value > 1 ? value / 100 : value));
  return (
    <span className="progress-bar">
      <i style={{ width: `${Math.round(normalized * 100)}%` }} />
    </span>
  );
}
