import type {
  CompetitorRecord,
  EvidenceGapFillResult,
  EvidenceGapReport,
  EvidenceQualityLabel,
  EvidenceRecord,
} from "../../api/types";
import { EvidenceLedgerPanel } from "./EvidenceLedgerPanel";
import { GapRepairPanel } from "./GapRepairPanel";

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
  return (
    <div className="evidence-workbench">
      <EvidenceLedgerPanel
        competitorById={competitorById}
        evidence={evidence}
        onEvidenceQuality={onEvidenceQuality}
        onSelectEvidence={onSelectEvidence}
        query={query}
        selectedEvidenceId={selectedEvidenceId}
        setQuery={setQuery}
      />
      <aside className="evidence-side-rail">
        <GapRepairPanel
          evidenceGaps={evidenceGaps}
          gapFillResult={gapFillResult}
          isFillingGaps={isFillingGaps}
          onFillGaps={onFillGaps}
        />
      </aside>
    </div>
  );
}
