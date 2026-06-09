import type { RawSource } from "../../api/types";
import type { MouseEvent } from "react";
import { sourceTypeLabel, type SourceTokenGroup } from "./sourceTokens";

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
          return (
            <a
              className={`source-trace-chip${activeSourceId === group.sourceId ? " active" : ""}`}
              href={`#source-${group.sourceId}`}
              key={group.sourceId}
              onClick={(event) => onSourceJump(event, `#source-${group.sourceId}`)}
              title={source.url || source.title}
            >
              <strong>
                {label} · {source.title}
              </strong>
              <span>{source.url || group.tokens.map((token) => `[source:${token}]`).join(", ")}</span>
              <em>
                {source.dimension} / {sourceTypeLabel(source.source_type)} / {group.count} cite
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
      {sources.map((source) => (
        <span
          className={citedSourceIds.has(source.id) ? "cited" : undefined}
          key={source.id}
          title={`${source.source_type} / ${source.content_hash}`}
        >
          {source.dimension} / {sourceTypeLabel(source.source_type)} / {Math.round(source.confidence * 100)}%
        </span>
      ))}
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
  return (
    <div className="source-list" id="source-list">
      <h3>Evidence</h3>
      {sources.map((source) => (
        <article
          className={`source-card${citedSourceIds.has(source.id) ? " cited" : ""}${
            activeSourceId === source.id ? " active" : ""
          }`}
          id={`source-${source.id}`}
          key={source.id}
        >
          <div>
            <strong>
              {citationLabels.get(source.id) ?? "uncited"} · {source.title}
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
          {source.snippet ? <p>{source.snippet}</p> : null}
          <code>{source.content_hash}</code>
        </article>
      ))}
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
  return (
    <div className="missing-source-list" id="missing-source-list">
      <h3>Missing sources</h3>
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
