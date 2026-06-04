import type { CompetitorRecord, EvidenceRecord, RawSource } from "../../api/types";

interface ReportSourceBundleOptions {
  competitorById?: Map<string, CompetitorRecord>;
  scopedEvidenceIds?: string[] | null;
}

export interface ReportSourceBundle {
  sources: RawSource[];
  aliases: Record<string, string>;
}

export function buildReportSourceBundle(
  evidence: EvidenceRecord[],
  options: ReportSourceBundleOptions = {},
): ReportSourceBundle {
  const scopedEvidenceIds =
    options.scopedEvidenceIds && options.scopedEvidenceIds.length > 0
      ? new Set(options.scopedEvidenceIds)
      : null;
  const sources: RawSource[] = [];
  const aliases: Record<string, string> = {};

  for (const item of evidence) {
    if (scopedEvidenceIds && !scopedEvidenceIds.has(item.id)) continue;
    const competitorName =
      options.competitorById?.get(item.competitor_id)?.name ?? item.competitor_id;
    aliases[item.raw_source_id] = item.id;
    for (const alias of evidenceRawSourceAliases(item)) {
      aliases[alias] = item.id;
    }
    sources.push({
      id: item.id,
      competitor: competitorName,
      covered_competitors: [competitorName],
      dimension: item.dimension,
      source_type: item.source_type,
      title: item.title,
      url: item.url ?? null,
      snippet: item.snippet,
      content_hash: item.content_hash,
      confidence: item.reliability_score,
      extracted_at: item.captured_at,
    });
  }

  return { sources, aliases };
}

function evidenceRawSourceAliases(item: EvidenceRecord): string[] {
  const aliases = item.metadata.raw_source_aliases;
  if (!Array.isArray(aliases)) return [];
  return aliases
    .map((alias) => String(alias).trim())
    .filter((alias) => alias.length > 0 && alias !== item.raw_source_id);
}
