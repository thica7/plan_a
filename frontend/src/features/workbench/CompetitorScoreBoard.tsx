import { BarChart3 } from "lucide-react";

import type { CompetitorRecord, CompetitorScoreReport, EvidenceRecord } from "../../api/types";
import { MetricCard, Panel, StatusPill } from "../../components/ui";

interface CompetitorScoreBoardProps {
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  scores: CompetitorScoreReport | null;
}

export function CompetitorScoreBoard({
  competitors,
  evidence,
  scores,
}: CompetitorScoreBoardProps) {
  const dimensions = Array.from(new Set(evidence.map((item) => item.dimension).filter(Boolean))).slice(0, 6);
  const topScore = scores?.scores.find((score) => score.competitor_id === scores.top_competitor_id) ?? scores?.scores[0] ?? null;
  const verifiedEvidenceCount = evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length;
  const averageCoverage = scores?.scores.length
    ? scores.scores.reduce((sum, score) => sum + normalizeScore(score.coverage_score), 0) / scores.scores.length
    : 0;

  return (
    <Panel className="competitor-score-panel" title="Competitive position" icon={<BarChart3 size={16} aria-hidden />}>
      <div className="competitor-score-grid">
        <MetricCard label="Competitors" value={competitors.length} />
        <MetricCard label="Verified evidence" value={verifiedEvidenceCount} tone={verifiedEvidenceCount ? "good" : "warn"} />
        <MetricCard label="Avg coverage" value={formatScorePercent(averageCoverage)} tone={averageCoverage >= 0.7 ? "good" : "warn"} />
        <MetricCard label="Current leader" value={topScore?.competitor_name ?? "n/a"} />
      </div>

      <div className="competitor-rank-list" role="list">
        {(scores?.scores ?? []).slice(0, 5).map((score) => (
          <article className="competitor-rank-row" key={score.competitor_id} role="listitem">
            <strong>#{score.rank} {score.competitor_name}</strong>
            <StatusPill tone={score.total_score >= 80 ? "good" : score.total_score >= 60 ? "warn" : "neutral"}>
              {Math.round(score.total_score)}
            </StatusPill>
            <span>{score.recommendation}</span>
          </article>
        ))}
      </div>

      <div className="competitor-coverage-matrix" aria-label="Competitor evidence coverage">
        <div className="competitor-coverage-head">
          <span>Competitor</span>
          {dimensions.map((dimension) => <span key={dimension}>{dimension}</span>)}
        </div>
        {competitors.map((competitor) => (
          <div className="competitor-coverage-row" key={competitor.id}>
            <strong>{competitor.name}</strong>
            {dimensions.map((dimension) => {
              const count = evidence.filter((item) => item.competitor_id === competitor.id && item.dimension === dimension).length;
              return <span className={count ? "filled" : ""} key={dimension}>{count || "-"}</span>;
            })}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function normalizeScore(value: number) {
  return value > 1 ? value / 100 : value;
}

function formatScorePercent(value: number) {
  return `${Math.round(normalizeScore(value) * 100)}%`;
}
