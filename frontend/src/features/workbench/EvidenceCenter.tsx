import { Database, GitCompare, RefreshCw, Search } from "lucide-react";
import type {
  CompetitorRecord,
  EvidenceGapFillResult,
  EvidenceGapReport,
  EvidenceQualityLabel,
  EvidenceRecord,
} from "../../api/types";
import { MetricCard, Panel } from "../../components/ui";
import { formatPercent } from "./format";

interface EvidenceCenterProps {
  competitorById: Map<string, CompetitorRecord>;
  evidence: EvidenceRecord[];
  evidenceGaps: EvidenceGapReport | null;
  gapFillResult: EvidenceGapFillResult | null;
  isFillingGaps: boolean;
  onEvidenceQuality: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onFillGaps: () => void;
  onSelectEvidence: (evidence: EvidenceRecord) => void;
  query: string;
  selectedEvidenceId: string | null;
  setQuery: (query: string) => void;
}

export function EvidenceCenter({
  competitorById,
  evidence,
  evidenceGaps,
  gapFillResult,
  isFillingGaps,
  onEvidenceQuality,
  onFillGaps,
  onSelectEvidence,
  query,
  selectedEvidenceId,
  setQuery,
}: EvidenceCenterProps) {
  const verifiedCount = evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length;

  return (
    <div className="workspace-two-column">
      <Panel
        className="evidence-table-panel"
        title="Evidence center"
        icon={<Database size={16} aria-hidden />}
        actions={
          <label className="search-control">
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
        <div className="metric-grid compact">
          <MetricCard label="Visible evidence" value={evidence.length} />
          <MetricCard label="Verified-like" value={verifiedCount} tone={verifiedCount >= evidence.length * 0.7 ? "good" : "warn"} />
          <MetricCard label="Accepted" value={evidence.filter((item) => item.quality_label === "accepted").length} />
        </div>
        <div className="evidence-ledger">
          {evidence.slice(0, 80).map((item) => (
            <article
              className={`evidence-ledger-row${item.id === selectedEvidenceId ? " selected" : ""}`}
              id={`evidence-${item.id}`}
              key={item.id}
            >
              <div className="evidence-source-main">
                <strong>{item.title}</strong>
                <em>{item.url ?? item.raw_source_id}</em>
              </div>
              <div className="evidence-source-meta">
                <span>
                  <strong>Competitor</strong>
                  {competitorById.get(item.competitor_id)?.name ?? item.competitor_id}
                </span>
                <span>
                  <strong>Dimension</strong>
                  {item.dimension}
                </span>
                <span>
                  <strong>Reliability</strong>
                  {formatPercent(item.reliability_score)}
                </span>
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
                <button className="table-action-button" type="button" onClick={() => onSelectEvidence(item)}>
                  Inspect
                </button>
              </div>
            </article>
          ))}
        </div>
      </Panel>

      <Panel
        className="inspector-panel"
        title="Gap repair"
        icon={<GitCompare size={16} aria-hidden />}
        actions={
          <button className="icon-text-button" disabled={isFillingGaps} type="button" onClick={onFillGaps}>
            <RefreshCw size={15} aria-hidden />
            {isFillingGaps ? "Filling" : "Fill gaps"}
          </button>
        }
      >
        <div className="metric-grid compact">
          <MetricCard label="Gaps" value={evidenceGaps?.gap_count ?? 0} tone={evidenceGaps?.critical_count ? "warn" : "neutral"} />
          <MetricCard label="Critical" value={evidenceGaps?.critical_count ?? 0} tone={evidenceGaps?.critical_count ? "warn" : "good"} />
          <MetricCard label="High" value={evidenceGaps?.high_count ?? 0} />
        </div>
        {gapFillResult ? (
          <div className="gap-fill-result">
            <strong>{formatPercent(gapFillResult.gap_closure_rate)} closure</strong>
            <span>{gapFillResult.added_evidence_count} evidence added</span>
            <span>{gapFillResult.online_failure_count} online failures</span>
          </div>
        ) : null}
        <div className="recommendation-list compact">
          {(evidenceGaps?.gaps ?? []).slice(0, 8).map((gap) => (
            <article className={`recommendation-card ${gap.severity}`} key={gap.id}>
              <strong>{gap.dimension ?? gap.gap_type}</strong>
              <span>{gap.competitor_name ?? "project"} / {gap.gap_type}</span>
              <p>{gap.message}</p>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}
