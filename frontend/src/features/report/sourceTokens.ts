import type { RawSource } from "../../api/types";

export interface SourceTokenGroup {
  sourceId: string;
  tokens: string[];
  count: number;
  source?: RawSource;
}

const SOURCE_TOKEN_RE = /\[source:([A-Za-z0-9_.:#-]+)\]/g;

export function collectSourceTokenGroups(
  markdown: string,
  sourceMap: Map<string, RawSource>,
  sourceAliases: Record<string, string>,
) {
  const groups = new Map<string, SourceTokenGroup>();
  for (const token of extractSourceTokens(markdown)) {
    const sourceId = resolveSourceId(token, sourceMap, sourceAliases);
    const existing =
      groups.get(sourceId) ||
      ({
        sourceId,
        tokens: [],
        count: 0,
        source: sourceMap.get(sourceId),
      } satisfies SourceTokenGroup);
    existing.count += 1;
    if (!existing.tokens.includes(token)) {
      existing.tokens.push(token);
    }
    groups.set(sourceId, existing);
  }
  return Array.from(groups.values());
}

export function linkSourceTokens(
  markdown: string,
  sourceMap: Map<string, RawSource>,
  sourceAliases: Record<string, string>,
  citationLabels: Map<string, string> = new Map(),
) {
  return markdown.replace(SOURCE_TOKEN_RE, (token, sourceId: string) => {
    const normalizedSourceId = resolveSourceId(sourceId, sourceMap, sourceAliases);
    const target = sourceMap.has(normalizedSourceId)
      ? `#source-${normalizedSourceId}`
      : `#missing-source-${normalizedSourceId}`;
    const label = citationLabels.get(normalizedSourceId) ?? token;
    return `[${label}](${target})`;
  });
}

export function extractSourceTokens(markdown: string) {
  return Array.from(markdown.matchAll(SOURCE_TOKEN_RE), (match) => match[1]);
}

export function resolveSourceId(
  token: string,
  sourceMap: Map<string, RawSource>,
  sourceAliases: Record<string, string>,
) {
  const sourceId = normalizeSourceToken(token);
  if (sourceMap.has(sourceId)) return sourceId;
  return sourceAliases[sourceId] ?? sourceId;
}

export function sourceTypeLabel(sourceType: string) {
  if (sourceType === "webpage_verified") return "fetched";
  if (
    sourceType === "survey_simulated" ||
    sourceType === "survey_response" ||
    sourceType === "interview_record" ||
    sourceType === "manual_transcript" ||
    sourceType === "manual_note" ||
    sourceType === "manual"
  ) {
    return "research";
  }
  if (sourceType === "web_search_result") return "search";
  return "llm";
}

export function buildCitationLabels(sourceGroups: SourceTokenGroup[]) {
  const labels = new Map<string, string>();
  let citedIndex = 1;
  let missingIndex = 1;
  for (const group of sourceGroups) {
    if (group.source) {
      labels.set(group.sourceId, `S${citedIndex}`);
      citedIndex += 1;
    } else {
      labels.set(group.sourceId, `missing ${missingIndex}`);
      missingIndex += 1;
    }
  }
  return labels;
}

function normalizeSourceToken(token: string) {
  return token.split("#", 1)[0];
}
