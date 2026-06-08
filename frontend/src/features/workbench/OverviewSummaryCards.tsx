import type { CSSProperties } from "react";
import { FileText, Gauge, ShieldCheck } from "lucide-react";

import type { CompetitorRecord, EvidenceRecord, ProjectReadinessScore, ReportVersionRecord } from "../../api/types";
import { EmptyState, Panel, StatusPill } from "../../components/ui";
import { formatDate, formatPercent, reportStatusTone } from "./format";

export function ReadinessCard({ readiness }: { readiness: ProjectReadinessScore | null }) {
  const scoreItems = [
    { label: "Coverage", value: readiness?.coverage_score ?? null },
    { label: "Quality", value: readiness?.evidence_score ?? null },
    { label: "Claims", value: readiness?.claim_score ?? null },
    { label: "QA", value: readiness?.qa_score ?? null },
  ];

  return (
    <Panel className="concept-card readiness-card" title="Readiness score" icon={<FileText size={16} aria-hidden />}>
      {readiness ? (
        <div className="readiness-score compact">
          <strong>{readiness.score}</strong>
          <span>{readiness.risk_level}</span>
        </div>
      ) : (
        <div className="readiness-empty">
          <span>Not scored</span>
          <strong>Waiting for readiness projection</strong>
        </div>
      )}
      <ScoreBreakdown items={scoreItems} />
      <p>{readiness?.summary ?? "Run analysis or refresh project signals to generate a readiness score."}</p>
    </Panel>
  );
}

export function EvidenceQualityCard({
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
  const verified = evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length;
  return (
    <Panel className="concept-card" title="Evidence quality" icon={<ShieldCheck size={16} aria-hidden />}>
      {evidence.length > 0 ? (
        <>
          <strong className="large-metric">
            {verified}
            <span>/{evidence.length}</span>
          </strong>
          <p>{formatPercent(verifiedRate)} verified-like sources</p>
        </>
      ) : (
        <SummaryEmpty title="No evidence yet" description="Evidence quality appears after sources are projected." />
      )}
      <div className="compact-stat-list">
        <span>
          Accepted <strong>{accepted}</strong>
        </span>
        <span>
          Rejected <strong>{rejected}</strong>
        </span>
        <span>
          Accepted rate <strong>{formatPercent(acceptedRate)}</strong>
        </span>
      </div>
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
  const dimensions = [...new Set(evidence.map((item) => item.dimension).filter(Boolean))].slice(0, 7);
  const visibleCompetitors = competitors.slice(0, 6);
  const coverage = new Map<string, number>();
  for (const item of evidence) {
    const key = `${item.competitor_id}:${item.dimension}`;
    coverage.set(key, (coverage.get(key) ?? 0) + 1);
  }
  return (
    <Panel className="concept-card heatmap-card" title="Coverage" icon={<Gauge size={16} aria-hidden />}>
      {dimensions.length > 0 && visibleCompetitors.length > 0 ? (
        <>
          <div className="coverage-heatmap" style={{ "--heatmap-cols": dimensions.length } as CSSProperties}>
            <span />
            {dimensions.map((dimension) => (
              <strong key={dimension} title={dimension}>
                {dimension.slice(0, 2).toUpperCase()}
              </strong>
            ))}
            {visibleCompetitors.map((competitor) => (
              <CoverageRow competitor={competitor} coverage={coverage} dimensions={dimensions} key={competitor.id} />
            ))}
          </div>
          <div className="heatmap-legend">
            <span>Low</span>
            <i />
            <i />
            <i />
            <span>High</span>
          </div>
        </>
      ) : (
        <SummaryEmpty title="No coverage matrix" description="Coverage appears after evidence is mapped to competitors and dimensions." />
      )}
    </Panel>
  );
}

export function ActiveReportCard({ selectedVersion }: { selectedVersion: ReportVersionRecord | null }) {
  return (
    <Panel className="concept-card active-report-card" title="Active report" icon={<FileText size={16} aria-hidden />}>
      {selectedVersion ? (
        <div className="report-version-summary">
          <StatusPill tone={reportStatusTone(selectedVersion.status)}>{selectedVersion.status}</StatusPill>
          <strong>Report v{selectedVersion.version_number}</strong>
          <span>{selectedVersion.report_md.length.toLocaleString()} characters</span>
          <span>
            {selectedVersion.claim_ids.length} claims / {selectedVersion.evidence_ids.length} evidence links
          </span>
          <time dateTime={selectedVersion.created_at}>{formatDate(selectedVersion.created_at)}</time>
        </div>
      ) : (
        <EmptyState title="No report version yet" />
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

function ScoreBreakdown({ items }: { items: Array<{ label: string; value: number | null }> }) {
  return (
    <div className="score-breakdown">
      {items.map((item) => (
        <ScoreLine key={item.label} label={item.label} value={item.value} />
      ))}
    </div>
  );
}

function ScoreLine({ label, value }: { label: string; value: number | null }) {
  const normalized = value === null ? null : Math.max(0, Math.min(1, value > 1 ? value / 100 : value));
  return (
    <span className={normalized === null ? "empty" : undefined}>
      <em>{label}</em>
      <b style={{ width: `${Math.round((normalized ?? 0) * 100)}%` }} />
      <strong>{normalized === null ? "n/a" : formatPercent(normalized)}</strong>
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
