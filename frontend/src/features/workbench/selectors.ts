import type { CompetitorRecord, EvidenceRecord, ReportVersionRecord } from "../../api/types";
import { buildReportSourceBundle } from "../report/sourceBundle";

export function buildCompetitorMap(competitors: CompetitorRecord[]) {
  return new Map(competitors.map((competitor) => [competitor.id, competitor]));
}

export function buildEvidenceMap(evidence: EvidenceRecord[]) {
  return new Map(evidence.map((item) => [item.id, item]));
}

export function buildWorkbenchReportSources(
  evidence: EvidenceRecord[],
  competitorById: Map<string, CompetitorRecord>,
  selectedVersion: ReportVersionRecord | null,
) {
  return buildReportSourceBundle(evidence, {
    competitorById,
    scopedEvidenceIds: selectedVersion?.evidence_ids ?? null,
  });
}

export function filterWorkbenchEvidence(
  evidence: EvidenceRecord[],
  competitorById: Map<string, CompetitorRecord>,
  query: string,
) {
  const needle = query.trim().toLowerCase();
  if (!needle) return evidence;

  return evidence.filter((item) => {
    const competitor = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
    return [item.title, item.dimension, item.source_type, item.snippet, competitor]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });
}
