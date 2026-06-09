import { ExternalLink, Layers } from "lucide-react";

import type { CompetitorRecord, CompetitorScoreReport, EvidenceRecord } from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";

interface CompetitorAssetGridProps {
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  scores: CompetitorScoreReport | null;
}

export function CompetitorAssetGrid({
  competitors,
  evidence,
  scores,
}: CompetitorAssetGridProps) {
  const scoreByCompetitor = new Map(scores?.scores.map((score) => [score.competitor_id, score]) ?? []);

  return (
    <Panel className="competitor-assets-panel" title="Competitor assets" icon={<Layers size={16} aria-hidden />}>
      <div className="competitor-catalog-grid">
        {competitors.map((competitor) => {
          const score = scoreByCompetitor.get(competitor.id);
          const competitorEvidence = evidence.filter((item) => item.competitor_id === competitor.id);
          const dimensions = Array.from(new Set(competitorEvidence.map((item) => item.dimension).filter(Boolean)));
          const acceptedCount = competitorEvidence.filter((item) => item.quality_label === "accepted").length;

          return (
            <article className="competitor-library-card" key={competitor.id}>
              <header>
                <div>
                  <strong>{competitor.name}</strong>
                  <span>{competitor.normalized_name}</span>
                </div>
                <StatusPill>{competitor.layer}</StatusPill>
              </header>

              <div className="competitor-asset-metrics">
                <span>
                  <strong>{score ? Math.round(score.total_score) : "n/a"}</strong>
                  Score
                </span>
                <span>
                  <strong>{competitorEvidence.length}</strong>
                  Evidence
                </span>
                <span>
                  <strong>{acceptedCount}</strong>
                  Accepted
                </span>
              </div>

              <div className="competitor-dimension-chips">
                {dimensions.slice(0, 6).map((dimension) => <span key={dimension}>{dimension}</span>)}
                {dimensions.length === 0 ? <span>no dimensions</span> : null}
              </div>

              {competitor.homepage_url ? (
                <a href={competitor.homepage_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} aria-hidden />
                  Homepage
                </a>
              ) : null}
              {score?.recommendation ? <p>{score.recommendation}</p> : null}
            </article>
          );
        })}
      </div>
    </Panel>
  );
}
