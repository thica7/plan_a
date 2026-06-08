import { AlertTriangle, CalendarClock, Layers } from "lucide-react";

import type {
  AuditLogRecord,
  BusinessQAEvaluation,
  ClaimValidationReport,
  CompetitorRecord,
  CompetitorScoreReport,
  EvidenceGapReport,
  EvidenceRecord,
  EvalOpsReport,
  QualityAgentMatrix,
  RedTeamReport,
  ReportVersionRecord,
} from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";
import { formatDate } from "./format";

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
  const rows = [
    ...(qaEvaluation?.findings ?? []).map((finding) => ({
      id: finding.id,
      severity: finding.severity,
      type: finding.rule_name,
      description: finding.message,
      scope: `${finding.competitor_name ?? "project"}${finding.dimension ? ` / ${finding.dimension}` : ""}`,
    })),
    ...(evidenceGaps?.gaps ?? []).slice(0, 4).map((gap) => ({
      id: gap.id,
      severity: gap.severity,
      type: gap.gap_type,
      description: gap.message,
      scope: `${gap.competitor_name ?? "project"}${gap.dimension ? ` / ${gap.dimension}` : ""}`,
    })),
  ].slice(0, 7);
  return (
    <Panel
      className="qa-blocker-panel"
      title="QA blockers"
      icon={<AlertTriangle size={16} aria-hidden />}
      actions={<StatusPill tone={rows.length ? "warn" : "good"}>{rows.length}</StatusPill>}
    >
      <div className="qa-blocker-table">
        <div className="qa-blocker-head">
          <span>Severity</span>
          <span>Type</span>
          <span>Description</span>
          <span>Scope</span>
        </div>
        {rows.map((row) => (
          <article className="qa-blocker-row" key={row.id}>
            <StatusPill tone={row.severity === "blocker" || row.severity === "critical" || row.severity === "high" ? "bad" : "warn"}>
              {row.severity}
            </StatusPill>
            <span>{row.type}</span>
            <strong>{row.description}</strong>
            <em>{row.scope}</em>
          </article>
        ))}
      </div>
      {rows.length === 0 ? <p className="muted-line">No active QA blockers.</p> : null}
      <div className="auto-redo-strip">
        <span>Auto-redo suggestions</span>
        <strong>{matrix?.entries.reduce((total, entry) => total + entry.suggested_redos.length, 0) ?? 0}</strong>
        <span>RedTeam {redTeam?.finding_count ?? 0}</span>
        <span>Claim issues {claimValidation?.issue_count ?? 0}</span>
      </div>
    </Panel>
  );
}

export function RecentActivityPanel({
  auditLogs,
  evalOps,
  selectedVersion,
}: {
  auditLogs: AuditLogRecord[];
  evalOps: EvalOpsReport | null;
  selectedVersion: ReportVersionRecord | null;
}) {
  const rows = [
    selectedVersion
      ? {
          id: `report-${selectedVersion.id}`,
          title: `Report v${selectedVersion.version_number} ${selectedVersion.status}`,
          meta: `${selectedVersion.claim_ids.length} claims / ${selectedVersion.evidence_ids.length} evidence`,
          time: selectedVersion.created_at,
        }
      : null,
    evalOps
      ? {
          id: "evalops",
          title: `EvalOps gate ${evalOps.regression_gate_status}`,
          meta: `${evalOps.run_count} runs / quality ${evalOps.report_quality_score}`,
          time: evalOps.generated_at,
        }
      : null,
    ...auditLogs.slice(0, 5).map((log) => ({
      id: log.id,
      title: log.action,
      meta: `${log.resource_type} / ${log.actor_type}${log.actor_id ? `:${log.actor_id}` : ""}`,
      time: log.created_at,
    })),
  ].filter((row): row is { id: string; title: string; meta: string; time: string } => Boolean(row));
  return (
    <Panel className="recent-activity-panel" title="Recent activity" icon={<CalendarClock size={16} aria-hidden />}>
      <div className="activity-timeline compact">
        {rows.slice(0, 7).map((row) => (
          <article key={row.id}>
            <i aria-hidden />
            <div>
              <strong>{row.title}</strong>
              <span>{row.meta}</span>
            </div>
            <time dateTime={row.time}>{formatDate(row.time)}</time>
          </article>
        ))}
      </div>
    </Panel>
  );
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
  const evidenceCounts = new Map<string, number>();
  evidence.forEach((item) => evidenceCounts.set(item.competitor_id, (evidenceCounts.get(item.competitor_id) ?? 0) + 1));
  const scoreByCompetitor = new Map(competitorScores?.scores.map((score) => [score.competitor_id, score]) ?? []);
  return (
    <Panel className="competitor-overview-table" title="Competitors" icon={<Layers size={16} aria-hidden />}>
      <div className="compact-data-table">
        <div className="compact-data-head">
          <span>Competitor</span>
          <span>Layer</span>
          <span>Coverage</span>
          <span>Evidence</span>
          <span>Score</span>
        </div>
        {competitors.slice(0, 8).map((competitor) => {
          const score = scoreByCompetitor.get(competitor.id);
          return (
            <article className="compact-data-row" key={competitor.id}>
              <strong>{competitor.name}</strong>
              <span>{competitor.layer}</span>
              <span>
                <ProgressBar value={score?.coverage_score ?? 0} />
              </span>
              <span>{evidenceCounts.get(competitor.id) ?? 0}</span>
              <span>{score?.total_score ?? "n/a"}</span>
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
