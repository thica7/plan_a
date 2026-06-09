import { SearchCheck } from "lucide-react";
import type { CompetitorDiscovery } from "../../api/types";

interface CompetitorDiscoveryViewProps {
  discovery?: CompetitorDiscovery | null;
}

export function CompetitorDiscoveryView({ discovery }: CompetitorDiscoveryViewProps) {
  if (!discovery) {
    return null;
  }

  return (
    <section className="panel discovery-panel">
      <div className="panel-heading-row">
        <h2>Competitor discovery</h2>
        <SearchCheck size={17} aria-hidden />
      </div>

      <div className="discovery-summary">
        <span>{discovery.selected_competitors.length} selected</span>
        <code>{discovery.query}</code>
      </div>
      {discovery.rationale ? <p className="discovery-rationale">{discovery.rationale}</p> : null}

      <div className="candidate-grid">
        {discovery.candidates.map((candidate) => (
          <article className={candidate.selected ? "candidate-card selected" : "candidate-card"} key={candidate.name}>
            <div>
              <strong>{candidate.rank}. {candidate.name}</strong>
              <span>{candidate.selected ? "Selected" : "Candidate"} · {Math.round(candidate.confidence * 100)}%</span>
            </div>
            {candidate.rationale ? <p>{candidate.rationale}</p> : null}
            {candidate.evidence_urls.length > 0 ? (
              <div className="candidate-evidence">
                {candidate.evidence_urls.slice(0, 2).map((url, index) => (
                  <a href={url} key={url} rel="noreferrer" target="_blank">
                    {candidate.evidence_titles[index] || url}
                  </a>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
