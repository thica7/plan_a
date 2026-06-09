import type { CompetitorRecord, CompetitorScoreReport, EvidenceRecord } from "../../api/types";
import { CompetitorAssetGrid } from "./CompetitorAssetGrid";
import { CompetitorScoreBoard } from "./CompetitorScoreBoard";

export function CompetitorLibrary({
  competitors,
  evidence,
  scores,
}: {
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  scores: CompetitorScoreReport | null;
}) {
  return (
    <div className="competitor-library-workbench">
      <CompetitorScoreBoard competitors={competitors} evidence={evidence} scores={scores} />
      <CompetitorAssetGrid competitors={competitors} evidence={evidence} scores={scores} />
    </div>
  );
}
