import type { RawSource } from "../../api/types";
import type { MouseEvent } from "react";
import { sourceTypeLabel, type SourceTokenGroup } from "./sourceTokens";
import { useTranslation } from "../../stores/i18n";

interface ReportSourceTraceProps {
  activeSourceId: string | null;
  citationLabels: Map<string, string>;
  citedSourceIds: Set<string>;
  citedSourceGroups: SourceTokenGroup[];
  missingSourceGroups: SourceTokenGroup[];
  onSourceJump: (event: MouseEvent<HTMLAnchorElement>, href: string) => void;
  sources: RawSource[];
  totalCitationCount: number;
}

export interface SourceAuditRow {
  label: string;
  value: string;
}

export function ReportSourceTrace({
  activeSourceId,
  citationLabels,
  citedSourceIds,
  citedSourceGroups,
  missingSourceGroups,
  onSourceJump,
  sources,
  totalCitationCount,
}: ReportSourceTraceProps) {
  return (
    <>
      {citedSourceGroups.length > 0 || missingSourceGroups.length > 0 ? (
        <SourceTraceSummary
          activeSourceId={activeSourceId}
          citationLabels={citationLabels}
          citedSourceGroups={citedSourceGroups}
          missingSourceGroups={missingSourceGroups}
          onSourceJump={onSourceJump}
          totalCitationCount={totalCitationCount}
        />
      ) : null}
      <SourceStrip citedSourceIds={citedSourceIds} sources={sources} />
      {sources.length > 0 ? (
        <SourceList
          activeSourceId={activeSourceId}
          citationLabels={citationLabels}
          citedSourceIds={citedSourceIds}
          sources={sources}
        />
      ) : null}
      {missingSourceGroups.length > 0 ? (
        <MissingSourceList
          activeSourceId={activeSourceId}
          missingSourceGroups={missingSourceGroups}
        />
      ) : null}
    </>
  );
}

function SourceTraceSummary({
  activeSourceId,
  citationLabels,
  citedSourceGroups,
  missingSourceGroups,
  onSourceJump,
  totalCitationCount,
}: {
  activeSourceId: string | null;
  citationLabels: Map<string, string>;
  citedSourceGroups: SourceTokenGroup[];
  missingSourceGroups: SourceTokenGroup[];
  onSourceJump: (event: MouseEvent<HTMLAnchorElement>, href: string) => void;
  totalCitationCount: number;
}) {
  return (
    <div className="source-trace-summary">
      <div className="source-trace-metrics">
        <span>
          <strong>{totalCitationCount}</strong>
          <em>source citations</em>
        </span>
        <span>
          <strong>{citedSourceGroups.length}</strong>
          <em>resolved evidence</em>
        </span>
        <span className={missingSourceGroups.length > 0 ? "warn" : "ok"}>
          <strong>{missingSourceGroups.length}</strong>
          <em>missing tokens</em>
        </span>
      </div>
      <div className="source-trace-grid">
        {citedSourceGroups.map((group) => {
          const source = group.source;
          if (!source) return null;
          const label = citationLabels.get(group.sourceId) ?? "S?";
          const provenance = sourceProvenanceLabel(source);
          return (
            <a
              className={`source-trace-chip${activeSourceId === group.sourceId ? " active" : ""}`}
              href={`#source-${group.sourceId}`}
              key={group.sourceId}
              onClick={(event) => onSourceJump(event, `#source-${group.sourceId}`)}
              title={source.url || source.title}
            >
              <strong>
                {label} 路 {source.title}
              </strong>
              <span>{source.url || group.tokens.map((token) => `[source:${token}]`).join(", ")}</span>
              <em>
                {source.dimension} / {sourceTypeLabel(source.source_type)} / {group.count} cite
                {provenance ? ` / ${provenance}` : ""}
              </em>
            </a>
          );
        })}
        {missingSourceGroups.map((group) => (
          <a
            className="source-trace-chip missing"
            href={`#missing-source-${group.sourceId}`}
            key={group.sourceId}
            onClick={(event) => onSourceJump(event, `#missing-source-${group.sourceId}`)}
            title="No matching RawSource id exists in this run."
          >
            <strong>{group.sourceId}</strong>
            <span>{group.tokens.map((token) => `[source:${token}]`).join(", ")}</span>
            <em>{group.count} unresolved cite</em>
          </a>
        ))}
      </div>
    </div>
  );
}

function SourceStrip({ citedSourceIds, sources }: { citedSourceIds: Set<string>; sources: RawSource[] }) {
  return (
    <div className="source-strip">
      {sources.map((source) => {
        const provenance = sourceProvenanceLabel(source);
        return (
          <span
            className={citedSourceIds.has(source.id) ? "cited" : undefined}
            key={source.id}
            title={`${source.source_type} / ${source.content_hash}`}
          >
            {source.dimension} / {sourceTypeLabel(source.source_type)} / {Math.round(source.confidence * 100)}%
            {provenance ? ` / ${provenance}` : ""}
          </span>
        );
      })}
    </div>
  );
}

function SourceList({
  activeSourceId,
  citationLabels,
  citedSourceIds,
  sources,
}: {
  activeSourceId: string | null;
  citationLabels: Map<string, string>;
  citedSourceIds: Set<string>;
  sources: RawSource[];
}) {
  const { t } = useTranslation();
  return (
    <div className="source-list" id="source-list">
      <h3>{t("report.evidence")}</h3>
      {sources.map((source) => {
        const auditRows = buildSourceAuditRows(source);
        return (
          <article
            className={`source-card${citedSourceIds.has(source.id) ? " cited" : ""}${
              activeSourceId === source.id ? " active" : ""
            }`}
            id={`source-${source.id}`}
            key={source.id}
          >
            <div>
              <strong>
                {citationLabels.get(source.id) ?? "uncited"} 路 {source.title}
              </strong>
              <span>
                {source.covered_competitors.length > 0 ? source.covered_competitors.join(", ") : source.competitor} /{" "}
                {source.dimension} / {source.source_type}
              </span>
            </div>
            <code>raw source: {source.id}</code>
            {source.url ? (
              <a href={source.url} rel="noreferrer" target="_blank">
                {source.url}
              </a>
            ) : null}
            {auditRows.length > 0 ? (
              <dl className="source-audit-grid" aria-label={`Audit metadata for ${source.id}`}>
                {auditRows.map((row) => (
                  <div key={`${row.label}:${row.value}`}>
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            {source.snippet ? <p>{source.snippet}</p> : null}
            <code>{source.content_hash}</code>
          </article>
        );
      })}
    </div>
  );
}

function MissingSourceList({
  activeSourceId,
  missingSourceGroups,
}: {
  activeSourceId: string | null;
  missingSourceGroups: SourceTokenGroup[];
}) {
  const { t } = useTranslation();
  return (
    <div className="missing-source-list" id="missing-source-list">
      <h3>{t("report.missingSources")}</h3>
      {missingSourceGroups.map((group) => (
        <article
          className={`missing-source-card${activeSourceId === group.sourceId ? " active" : ""}`}
          id={`missing-source-${group.sourceId}`}
          key={group.sourceId}
        >
          <strong>{group.tokens.map((token) => `[source:${token}]`).join(", ")}</strong>
          <span>No matching RawSource id exists in this run.</span>
        </article>
      ))}
    </div>
  );
}

export function buildSourceAuditRows(source: RawSource): SourceAuditRow[] {
  const rows: SourceAuditRow[] = [];
  const provenance = sourceProvenanceLabel(source);
  if (provenance) rows.push({ label: "Origin", value: provenance });
  if (source.fetch_method) rows.push({ label: "Fetch", value: source.fetch_method });
  if (source.candidate_confidence !== null && source.candidate_confidence !== undefined) {
    rows.push({ label: "Candidate", value: formatPercent(source.candidate_confidence) });
  }

  if (!isKbSource(source)) return rows;

  const metadata = source.metadata;
  const status = metadataText(metadata, "kb_document_status");
  const documentId = metadataText(metadata, "kb_document_id");
  const version = metadataText(metadata, "kb_document_version");
  const chunkId = metadataText(metadata, "kb_chunk_id");
  const chunkIds = metadataStringList(metadata, "kb_chunk_ids");
  const retrievalQuery = metadataText(metadata, "kb_retrieval_query");
  const hitScore = metadataNumber(metadata, "kb_hit_score");
  const rerankScore = metadataNumber(metadata, "kb_rerank_score");
  const rawSourceId = metadataText(metadata, "kb_raw_source_id");
  const collectorRunId = metadataText(metadata, "kb_collector_run_id");
  const fetchedAt = metadataDate(metadata, "kb_fetched_at");
  const lastSeenAt = metadataDate(metadata, "kb_last_seen_at");
  const freshnessScore = metadataNumber(metadata, "kb_freshness_score");

  if (status) rows.push({ label: "KB status", value: status });
  if (documentId) rows.push({ label: "KB document", value: documentId });
  if (version) rows.push({ label: "KB version", value: `v${version}` });
  if (chunkId) rows.push({ label: "KB chunk", value: chunkId });
  if (!chunkId && chunkIds.length > 0) {
    rows.push({ label: "KB chunks", value: formatList(chunkIds, 3) });
  }
  if (retrievalQuery) rows.push({ label: "KB query", value: compactText(retrievalQuery, 120) });
  if (hitScore !== null) rows.push({ label: "KB hit", value: formatScore(hitScore) });
  if (rerankScore !== null) rows.push({ label: "KB rerank", value: formatScore(rerankScore) });
  if (rawSourceId) rows.push({ label: "KB raw source", value: rawSourceId });
  if (collectorRunId) rows.push({ label: "Collector run", value: collectorRunId });
  if (fetchedAt) rows.push({ label: "Fetched", value: fetchedAt });
  if (lastSeenAt) rows.push({ label: "Last seen", value: lastSeenAt });
  if (freshnessScore !== null) rows.push({ label: "Freshness", value: formatPercent(freshnessScore) });

  return rows;
}

export function isKbSource(source: RawSource) {
  const metadata = source.metadata;
  return Boolean(
    source.candidate_origin === "rag_kb" ||
      metadataBoolean(metadata, "kb_sync") ||
      metadataBoolean(metadata, "kb_retrieved") ||
      metadataText(metadata, "kb_document_id") ||
      metadataText(metadata, "kb_chunk_id") ||
      metadataStringList(metadata, "kb_chunk_ids").length > 0 ||
      metadataText(metadata, "kb_raw_source_id") ||
      metadataText(metadata, "kb_document_status") ||
      metadataText(metadata, "kb_document_version"),
  );
}

function sourceProvenanceLabel(source: RawSource) {
  if (isKbSource(source)) return "KB reused";
  if (source.candidate_origin && source.candidate_origin !== "unknown") return source.candidate_origin;
  return "";
}

function metadataText(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
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

function metadataStringList(metadata: Record<string, unknown>, key: string): string[] {
  const value = metadata[key];
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  const text = metadataText(metadata, key);
  return text ? [text] : [];
}

function metadataBoolean(metadata: Record<string, unknown>, key: string): boolean {
  const value = metadata[key];
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return value.toLowerCase() === "true";
  return false;
}

function metadataDate(metadata: Record<string, unknown>, key: string): string | null {
  const raw = metadataText(metadata, key);
  if (!raw) return null;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toISOString().slice(0, 10);
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatScore(value: number) {
  return value <= 1 ? formatPercent(value) : value.toFixed(2);
}

function formatList(values: string[], limit: number) {
  const visible = values.slice(0, limit);
  const suffix = values.length > limit ? ` +${values.length - limit}` : "";
  return `${visible.join(", ")}${suffix}`;
}

function compactText(value: string, maxChars: number) {
  if (value.length <= maxChars) return value;
  return `${value.slice(0, Math.max(0, maxChars - 3)).trimEnd()}...`;
}
