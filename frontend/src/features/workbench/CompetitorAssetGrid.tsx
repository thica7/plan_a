import { ExternalLink, Layers } from "lucide-react";

import type { CompetitorRecord, CompetitorScoreReport, EvidenceRecord } from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
import { displayLabel } from '../../i18n/display';
import { SystemMessage } from '../../i18n/SystemMessage';

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
  const { t, locale } = useTranslation();
  const scoreByCompetitor = new Map(scores?.scores.map((score) => [score.competitor_id, score]) ?? []);

  return (
    <Panel className="competitor-assets-panel" title={t('workbench.competitorAssets')} icon={<Layers size={16} aria-hidden />}>
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
                <StatusPill><span title={competitor.layer}>{displayLabel(competitor.layer, locale)}</span></StatusPill>
              </header>

              <div className="competitor-asset-metrics">
                <span>
                  <strong>{score ? Math.round(score.total_score) : displayLabel('n/a', locale)}</strong>
                  {t('workbench.score')}
                </span>
                <span>
                  <strong>{competitorEvidence.length}</strong>
                  {t('workbench.evidence')}
                </span>
                <span>
                  <strong>{acceptedCount}</strong>
                  {t('workbench.acceptedCol')}
                </span>
              </div>

              <div className="competitor-dimension-chips">
                {dimensions.slice(0, 6).map((dimension) => <span key={dimension} title={dimension}>{displayLabel(dimension, locale)}</span>)}
                {dimensions.length === 0 ? <span>{t('workbench.noDimensions')}</span> : null}
              </div>

              {competitor.homepage_url ? (
                <a href={competitor.homepage_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} aria-hidden />
                  {t('workbench.homepage')}
                </a>
              ) : null}
              {score?.recommendation ? <p><SystemMessage message={score.recommendation} /></p> : null}
            </article>
          );
        })}
      </div>
    </Panel>
  );
}
