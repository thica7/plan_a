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
    aliases[item.id] = item.raw_source_id;
    for (const alias of evidenceRawSourceAliases(item)) {
      aliases[alias] = item.raw_source_id;
    }
    const candidateOrigin =
      metadataText(item.metadata, "kb_collector_candidate_origin") ??
      metadataText(item.metadata, "collector_candidate_origin") ??
      (metadataText(item.metadata, "kb_sync") ? "rag_kb" : "enterprise_evidence");
    const fetchMethod =
      metadataText(item.metadata, "kb_collector_fetch_method") ??
      metadataText(item.metadata, "collector_fetch_method") ??
      "enterprise_projection";
    const candidateConfidence = metadataNumber(item.metadata, "kb_collector_confidence");
    sources.push({
      id: item.raw_source_id,
      competitor: competitorName,
      covered_competitors: [competitorName],
      dimension: item.dimension,
      source_type: item.source_type,
      title: item.title,
      url: item.url ?? null,
      snippet: item.snippet,
      content_hash: item.content_hash,
      confidence: item.reliability_score,
      candidate_origin: candidateOrigin,
      candidate_rank: null,
      candidate_confidence: candidateConfidence,
      fetch_method: fetchMethod,
      quality_score: item.reliability_score,
      failure_reason: null,
      metadata: item.metadata,
      extracted_at: item.captured_at,
    });
  }

  return { sources, aliases };
}

function evidenceRawSourceAliases(item: EvidenceRecord): string[] {
  const aliases = item.metadata.raw_source_aliases;
  const normalizedAliases = Array.isArray(aliases)
    ? aliases.map((alias) => String(alias).trim())
    : [];
  const kbRawSourceId = metadataText(item.metadata, "kb_raw_source_id");
  if (kbRawSourceId) normalizedAliases.push(kbRawSourceId);
  return normalizedAliases.filter(
    (alias, index, values) =>
      alias.length > 0 && alias !== item.raw_source_id && values.indexOf(alias) === index,
  );
}

function metadataText(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "boolean") return value ? "true" : null;
  return null;
}

function metadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
