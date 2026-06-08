import { useMemo } from "react";
import { ExternalLink, Layers } from "lucide-react";

import type { CompetitorRecord, CompetitorScoreReport, EvidenceRecord } from "../../api/types";
import { MetricCard, Panel } from "../../components/ui";
import { formatPercent } from "./format";

export function CompetitorLibrary({
  competitors,
  evidence,
  scores,
}: {
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  scores: CompetitorScoreReport | null;
}) {
  const evidenceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    evidence.forEach((item) => counts.set(item.competitor_id, (counts.get(item.competitor_id) ?? 0) + 1));
    return counts;
  }, [evidence]);
  const scoreByCompetitor = new Map(scores?.scores.map((score) => [score.competitor_id, score]) ?? []);

  return (
    <Panel title="Competitor library" icon={<Layers size={16} aria-hidden />}>
      <div className="competitor-catalog-grid">
        {competitors.map((competitor) => {
          const score = scoreByCompetitor.get(competitor.id);
          return (
            <article className="competitor-library-card" key={competitor.id}>
              <div>
                <strong>{competitor.name}</strong>
                <span>{competitor.layer} / {competitor.normalized_name}</span>
              </div>
              <div className="metric-grid compact">
                <MetricCard label="Score" value={score?.total_score ?? "n/a"} />
                <MetricCard label="Evidence" value={evidenceCounts.get(competitor.id) ?? 0} />
                <MetricCard label="Coverage" value={score ? formatPercent(score.coverage_score) : "n/a"} />
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
