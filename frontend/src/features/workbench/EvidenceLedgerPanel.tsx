import { Database, Search } from "lucide-react";

import type {
  CompetitorRecord,
  EvidenceQualityLabel,
  EvidenceRecord,
} from "../../api/types";
import { EmptyState, MetricCard, Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
import { formatPercent } from "./format";

interface EvidenceLedgerPanelProps {
  competitorById: Map<string, CompetitorRecord>;
  evidence: EvidenceRecord[];
  onEvidenceQuality: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onSelectEvidence: (evidence: EvidenceRecord) => void;
  query: string;
  selectedEvidenceId: string | null;
  setQuery: (query: string) => void;
}

export function EvidenceLedgerPanel({
  competitorById,
  evidence,
  onEvidenceQuality,
  onSelectEvidence,
  query,
  selectedEvidenceId,
  setQuery,
}: EvidenceLedgerPanelProps) {
  const { t } = useTranslation();
  const verifiedCount = evidence.filter(isVerifiedLikeEvidence).length;
  const acceptedCount = evidence.filter((item) => item.quality_label === "accepted").length;

  return (
    <Panel
      className="evidence-ledger-panel"
      title={t('workbench.evidenceStatus')}
      icon={<Database size={16} aria-hidden />}
      actions={
        <label className="search-control evidence-search-control">
          <Search size={15} aria-hidden />
          <input
            aria-label="Search evidence"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search source, dimension, competitor"
          />
        </label>
      }
    >
      <div className="metric-grid compact evidence-ledger-summary">
        <MetricCard label="Visible evidence" value={evidence.length} />
        <MetricCard
          label="Verified-like"
          value={verifiedCount}
          tone={verifiedCount >= evidence.length * 0.7 ? "good" : "warn"}
        />
        <MetricCard label="Accepted" value={acceptedCount} />
      </div>

      {evidence.length === 0 ? (
        <EmptyState title="No evidence found">Try another keyword or collect more project evidence.</EmptyState>
      ) : (
        <div className="evidence-ledger-list" role="list">
          {evidence.slice(0, 80).map((item) => (
            <article
              className={`evidence-ledger-row${item.id === selectedEvidenceId ? " selected" : ""}`}
              id={`evidence-${item.id}`}
              key={item.id}
              role="listitem"
            >
              <button className="evidence-ledger-open" type="button" onClick={() => onSelectEvidence(item)}>
                <span>{normalizeSourceType(item.source_type)}</span>
                <strong>{item.title}</strong>
                <em>{item.url ?? item.raw_source_id}</em>
              </button>

              <div className="evidence-source-meta">
                <span>
                  <strong>Competitor</strong>
                  <em>{competitorById.get(item.competitor_id)?.name ?? item.competitor_id}</em>
                </span>
                <span>
                  <strong>Dimension</strong>
                  <em>{item.dimension}</em>
                </span>
                <span>
                  <strong>Freshness</strong>
                  <em>{formatPercent(item.freshness_score)}</em>
                </span>
              </div>

              <div className="evidence-review-actions">
                <StatusPill tone={evidenceTone(item)}>{formatPercent(item.reliability_score)}</StatusPill>
                <select
                  aria-label={`Quality for ${item.title}`}
                  value={item.quality_label}
                  onChange={(event) => onEvidenceQuality(item.id, event.target.value as EvidenceQualityLabel)}
                >
                  <option value="unreviewed">unreviewed</option>
                  <option value="accepted">accepted</option>
                  <option value="rejected">rejected</option>
                  <option value="stale">stale</option>
                </select>
              </div>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}

function isVerifiedLikeEvidence(item: EvidenceRecord) {
  return item.source_type.includes("verified") || item.reliability_score >= 0.72;
}

function evidenceTone(item: EvidenceRecord): "good" | "neutral" | "warn" | "bad" {
  if (item.quality_label === "rejected" || item.quality_label === "stale") return "bad";
  if (isVerifiedLikeEvidence(item)) return "good";
  if (item.reliability_score >= 0.5) return "warn";
  return "neutral";
}

function normalizeSourceType(sourceType: string) {
  return sourceType.split("_").join(" ");
}
