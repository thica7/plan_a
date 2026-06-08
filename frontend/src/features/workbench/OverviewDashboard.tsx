import { useState, type CSSProperties } from "react";
import { AlertTriangle, CalendarClock, FileText, Gauge, Layers, ShieldCheck } from "lucide-react";

import type {
  AuditLogRecord,
  BusinessQAEvaluation,
  ClaimRecord,
  ClaimValidationReport,
  CompetitorRecord,
  CompetitorScoreReport,
  EvidenceGapReport,
  EvidenceRecord,
  EvalOpsReport,
  ProjectReadinessScore,
  QualityAgentMatrix,
  RedTeamReport,
  ReportVersionRecord,
} from "../../api/types";
import { EmptyState, Panel, StatusPill } from "../../components/ui";
import { formatDate, formatPercent, reportStatusTone } from "./format";
import "./overview.css";

export interface OverviewDashboardProps {
  auditLogs: AuditLogRecord[];
  claimValidation: ClaimValidationReport | null;
  claims: ClaimRecord[];
  competitorScores: CompetitorScoreReport | null;
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  evidenceGaps: EvidenceGapReport | null;
  evalOps: EvalOpsReport | null;
  matrix: QualityAgentMatrix | null;
  qaEvaluation: BusinessQAEvaluation | null;
  readiness: ProjectReadinessScore | null;
  redTeam: RedTeamReport | null;
  selectedVersion: ReportVersionRecord | null;
}

export function OverviewDashboard({
  auditLogs,
  claimValidation,
  claims,
  competitorScores,
  competitors,
  evidence,
  evidenceGaps,
  evalOps,
  matrix,
  qaEvaluation,
  readiness,
  redTeam,
  selectedVersion,
}: OverviewDashboardProps) {
  const verifiedRate = evidence.length
    ? evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length /
      evidence.length
    : 0;
  const acceptedRate = evidence.length
    ? evidence.filter((item) => item.quality_label === "accepted").length / evidence.length
    : 0;
  const [inspectorTab, setInspectorTab] = useState<"source" | "claim" | "report">("source");
  const selectedSource =
    evidence.find((item) => item.quality_label === "accepted") ??
    evidence.find((item) => item.url) ??
    evidence[0] ??
    null;
  const selectedClaim =
    claims.find((claim) => selectedSource && claim.evidence_ids.includes(selectedSource.id)) ??
    claims[0] ??
    null;

  return (
    <div className="concept-workbench-grid">
      <div className="concept-main-column">
        <div className="concept-summary-grid">
          <ReadinessCard readiness={readiness} />
          <EvidenceQualityCard acceptedRate={acceptedRate} evidence={evidence} verifiedRate={verifiedRate} />
          <CoverageHeatmap competitors={competitors} evidence={evidence} />
          <ActiveReportCard selectedVersion={selectedVersion} />
        </div>

        <div className="concept-lower-grid">
          <QaBlockersPanel
            claimValidation={claimValidation}
            evidenceGaps={evidenceGaps}
            matrix={matrix}
            qaEvaluation={qaEvaluation}
            redTeam={redTeam}
          />
          <RecentActivityPanel auditLogs={auditLogs} evalOps={evalOps} selectedVersion={selectedVersion} />
        </div>

        <CompetitorsOverviewTable
          competitorScores={competitorScores}
          competitors={competitors}
          evidence={evidence}
        />
      </div>

      <ContextInspector
        claim={selectedClaim}
        evidence={selectedSource}
        report={selectedVersion}
        selectedTab={inspectorTab}
        setSelectedTab={setInspectorTab}
      />
    </div>
  );
}

function ReadinessCard({ readiness }: { readiness: ProjectReadinessScore | null }) {
  return (
    <Panel className="concept-card readiness-card" title="Readiness score" icon={<FileText size={16} aria-hidden />}>
      <div className="readiness-score compact">
        <strong>{readiness?.score ?? "n/a"}</strong>
        <span>{readiness?.risk_level ?? "not scored"}</span>
      </div>
      <div className="score-breakdown">
        <ScoreLine label="Coverage" value={readiness?.coverage_score ?? 0} />
        <ScoreLine label="Quality" value={readiness?.evidence_score ?? 0} />
        <ScoreLine label="Claims" value={readiness?.claim_score ?? 0} />
        <ScoreLine label="QA" value={readiness?.qa_score ?? 0} />
      </div>
      <p>{readiness?.summary ?? "Readiness is generated after project evidence and QA are projected."}</p>
    </Panel>
  );
}

function EvidenceQualityCard({
  acceptedRate,
  evidence,
  verifiedRate,
}: {
  acceptedRate: number;
  evidence: EvidenceRecord[];
  verifiedRate: number;
}) {
  const accepted = evidence.filter((item) => item.quality_label === "accepted").length;
  const rejected = evidence.filter((item) => item.quality_label === "rejected").length;
  return (
    <Panel className="concept-card" title="Evidence quality" icon={<ShieldCheck size={16} aria-hidden />}>
      <strong className="large-metric">
        {evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length}
        <span>/{evidence.length}</span>
      </strong>
      <p>{formatPercent(verifiedRate)} verified-like sources</p>
      <div className="compact-stat-list">
        <span>Accepted <strong>{accepted}</strong></span>
        <span>Rejected <strong>{rejected}</strong></span>
        <span>Accepted rate <strong>{formatPercent(acceptedRate)}</strong></span>
      </div>
    </Panel>
  );
}

function CoverageHeatmap({
  competitors,
  evidence,
}: {
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
}) {
  const dimensions = [...new Set(evidence.map((item) => item.dimension).filter(Boolean))].slice(0, 7);
  const visibleCompetitors = competitors.slice(0, 6);
  const coverage = new Map<string, number>();
  for (const item of evidence) {
    const key = `${item.competitor_id}:${item.dimension}`;
    coverage.set(key, (coverage.get(key) ?? 0) + 1);
  }
  return (
    <Panel className="concept-card heatmap-card" title="Coverage" icon={<Gauge size={16} aria-hidden />}>
      <div className="coverage-heatmap" style={{ "--heatmap-cols": dimensions.length || 1 } as CSSProperties}>
        <span />
        {dimensions.map((dimension) => (
          <strong key={dimension} title={dimension}>{dimension.slice(0, 2).toUpperCase()}</strong>
        ))}
        {visibleCompetitors.map((competitor) => (
          <CoverageRow
            competitor={competitor}
            coverage={coverage}
            dimensions={dimensions}
            key={competitor.id}
          />
        ))}
      </div>
      <div className="heatmap-legend">
        <span>Low</span>
        <i />
        <i />
        <i />
        <span>High</span>
      </div>
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
  return (
    <>
      <em title={competitor.name}>{competitor.name}</em>
      {dimensions.map((dimension) => {
        const count = coverage.get(`${competitor.id}:${dimension}`) ?? 0;
        const level = count >= 5 ? "high" : count >= 2 ? "mid" : count === 1 ? "low" : "empty";
        return (
          <span
            className={`heat-cell ${level}`}
            key={`${competitor.id}-${dimension}`}
            title={`${competitor.name} / ${dimension}: ${count}`}
          />
        );
      })}
    </>
  );
}

function ActiveReportCard({ selectedVersion }: { selectedVersion: ReportVersionRecord | null }) {
  return (
    <Panel className="concept-card active-report-card" title="Active report" icon={<FileText size={16} aria-hidden />}>
      {selectedVersion ? (
        <div className="report-version-summary">
          <StatusPill tone={reportStatusTone(selectedVersion.status)}>{selectedVersion.status}</StatusPill>
          <strong>Report v{selectedVersion.version_number}</strong>
          <span>{selectedVersion.report_md.length.toLocaleString()} characters</span>
          <span>{selectedVersion.claim_ids.length} claims / {selectedVersion.evidence_ids.length} evidence links</span>
          <time dateTime={selectedVersion.created_at}>{formatDate(selectedVersion.created_at)}</time>
        </div>
      ) : (
        <EmptyState title="No report version yet" />
      )}
    </Panel>
  );
}

function QaBlockersPanel({
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

function RecentActivityPanel({
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

function CompetitorsOverviewTable({
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

function ContextInspector({
  claim,
  evidence,
  report,
  selectedTab,
  setSelectedTab,
}: {
  claim: ClaimRecord | null;
  evidence: EvidenceRecord | null;
  report: ReportVersionRecord | null;
  selectedTab: "source" | "claim" | "report";
  setSelectedTab: (tab: "source" | "claim" | "report") => void;
}) {
  return (
    <aside className="concept-inspector">
      <div className="inspector-tabs">
        {(["source", "claim", "report"] as const).map((tab) => (
          <button
            className={selectedTab === tab ? "active" : ""}
            key={tab}
            type="button"
            onClick={() => setSelectedTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      {selectedTab === "source" ? <SourceInspector evidence={evidence} /> : null}
      {selectedTab === "claim" ? <ClaimInspector claim={claim} /> : null}
      {selectedTab === "report" ? <ReportInspector report={report} /> : null}
    </aside>
  );
}

function SourceInspector({ evidence }: { evidence: EvidenceRecord | null }) {
  if (!evidence) return <EmptyState title="No source selected" />;
  return (
    <div className="inspector-body">
      <StatusPill tone={evidence.quality_label === "accepted" ? "good" : "warn"}>
        {evidence.quality_label}
      </StatusPill>
      <h3>{evidence.title}</h3>
      {evidence.url ? <a href={evidence.url} target="_blank" rel="noreferrer">{evidence.url}</a> : null}
      <code>{evidence.raw_source_id}</code>
      <div className="inspector-meta-grid">
        <span>Type <strong>{evidence.source_type}</strong></span>
        <span>Dimension <strong>{evidence.dimension}</strong></span>
        <span>Reliability <strong>{formatPercent(evidence.reliability_score)}</strong></span>
        <span>Freshness <strong>{formatPercent(evidence.freshness_score)}</strong></span>
      </div>
      <section className="snapshot-box">
        <strong>Snapshot</strong>
        <p>{evidence.snippet}</p>
      </section>
    </div>
  );
}

function ClaimInspector({ claim }: { claim: ClaimRecord | null }) {
  if (!claim) return <EmptyState title="No claim selected" />;
  return (
    <div className="inspector-body">
      <StatusPill tone={claim.status === "accepted" ? "good" : claim.status === "rejected" ? "bad" : "neutral"}>
        {claim.status}
      </StatusPill>
      <h3>{claim.claim_type}</h3>
      <p>{claim.claim_text}</p>
      <div className="inspector-meta-grid">
        <span>Confidence <strong>{formatPercent(claim.confidence)}</strong></span>
        <span>Evidence <strong>{claim.evidence_ids.length}</strong></span>
        <span>Agent <strong>{claim.created_by_agent ?? "unknown"}</strong></span>
      </div>
      <div className="linked-chip-list">
        {claim.evidence_ids.slice(0, 6).map((id) => (
          <span key={id}>{id}</span>
        ))}
      </div>
    </div>
  );
}

function ReportInspector({ report }: { report: ReportVersionRecord | null }) {
  if (!report) return <EmptyState title="No report selected" />;
  return (
    <div className="inspector-body">
      <StatusPill tone={reportStatusTone(report.status)}>{report.status}</StatusPill>
      <h3>Report v{report.version_number}</h3>
      <div className="inspector-meta-grid">
        <span>Claims <strong>{report.claim_ids.length}</strong></span>
        <span>Evidence <strong>{report.evidence_ids.length}</strong></span>
        <span>Size <strong>{report.report_md.length.toLocaleString()}</strong></span>
      </div>
      <section className="snapshot-box">
        <strong>Preview</strong>
        <p>{report.report_md.slice(0, 420)}</p>
      </section>
    </div>
  );
}

function ScoreLine({ label, value }: { label: string; value: number }) {
  const normalized = Math.max(0, Math.min(1, value > 1 ? value / 100 : value));
  return (
    <span>
      <em>{label}</em>
      <b style={{ width: `${Math.round(normalized * 100)}%` }} />
      <strong>{formatPercent(normalized)}</strong>
    </span>
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
