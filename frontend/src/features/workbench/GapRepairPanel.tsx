import { GitCompare, RefreshCw } from "lucide-react";

import type { EvidenceGapFillResult, EvidenceGapReport } from "../../api/types";
import { EmptyState, MetricCard, Panel, StatusPill } from "../../components/ui";
import { formatPercent } from "./format";

interface GapRepairPanelProps {
  evidenceGaps: EvidenceGapReport | null;
  gapFillResult: EvidenceGapFillResult | null;
  isFillingGaps: boolean;
  onFillGaps: () => void;
}

export function GapRepairPanel({
  evidenceGaps,
  gapFillResult,
  isFillingGaps,
  onFillGaps,
}: GapRepairPanelProps) {
  const gaps = evidenceGaps?.gaps ?? [];

  return (
    <Panel
      className="gap-repair-panel"
      title="Gap repair"
      icon={<GitCompare size={16} aria-hidden />}
      actions={
        <button className="icon-text-button" disabled={isFillingGaps} type="button" onClick={onFillGaps}>
          <RefreshCw size={15} aria-hidden />
          {isFillingGaps ? "Filling" : "Fill gaps"}
        </button>
      }
    >
      <div className="metric-grid compact gap-repair-summary">
        <MetricCard label="Gaps" value={evidenceGaps?.gap_count ?? 0} tone={evidenceGaps?.critical_count ? "warn" : "neutral"} />
        <MetricCard label="Critical" value={evidenceGaps?.critical_count ?? 0} tone={evidenceGaps?.critical_count ? "warn" : "good"} />
        <MetricCard label="High" value={evidenceGaps?.high_count ?? 0} />
      </div>

      {gapFillResult ? (
        <div className="gap-fill-result">
          <strong>{formatPercent(gapFillResult.gap_closure_rate)} closure</strong>
          <span>{gapFillResult.added_evidence_count} evidence added</span>
          <span>{gapFillResult.online_failure_count} online failures</span>
          <span>{gapFillResult.gap_fill_chain_closed ? "Repair chain closed" : "Repair chain still open"}</span>
        </div>
      ) : null}

      {gaps.length === 0 ? (
        <EmptyState title="No open evidence gaps">The current project has no typed gap repair tasks.</EmptyState>
      ) : (
        <div className="gap-card-list" role="list">
          {gaps.slice(0, 8).map((gap) => (
            <article className={`gap-card ${gap.severity}`} key={gap.id} role="listitem">
              <header>
                <StatusPill tone={gapTone(gap.severity)}>{gap.severity}</StatusPill>
                <strong>{gap.dimension ?? gap.gap_type}</strong>
              </header>
              <span>{gap.competitor_name ?? "project"} / {gap.gap_type}</span>
              <p>{gap.message}</p>
              {gap.recommended_query ? <em>{gap.recommended_query}</em> : null}
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}

function gapTone(severity: string): "neutral" | "warn" | "bad" {
  if (severity === "critical" || severity === "high") return "bad";
  if (severity === "medium") return "warn";
  return "neutral";
}
