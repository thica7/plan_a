import { useMemo, useState, type MouseEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { RawSource } from "../../api/types";

interface Props {
  markdown: string;
  sources: RawSource[];
  sourceAliases?: Record<string, string>;
}

const EMPTY_SOURCE_ALIASES: Record<string, string> = {};

export function ReportView({ markdown, sources, sourceAliases = EMPTY_SOURCE_ALIASES }: Props) {
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const sourceMap = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources]);
  const sourceGroups = useMemo(
    () => collectSourceTokenGroups(markdown, sourceMap, sourceAliases),
    [markdown, sourceAliases, sourceMap],
  );
  const citedSourceGroups = sourceGroups.filter((group) => group.source);
  const missingSourceGroups = sourceGroups.filter((group) => !group.source);
  const citedSourceIds = useMemo(
    () => new Set(citedSourceGroups.map((group) => group.sourceId)),
    [citedSourceGroups],
  );
  const linkedMarkdown = useMemo(
    () => linkSourceTokens(markdown, sourceMap, sourceAliases),
    [markdown, sourceAliases, sourceMap],
  );
  const totalCitationCount = sourceGroups.reduce((total, group) => total + group.count, 0);

  function handleSourceJump(event: MouseEvent<HTMLAnchorElement>, href: string | undefined) {
    const anchorId = href?.startsWith("#") ? href.slice(1) : "";
    if (!anchorId) return;
    const target = document.getElementById(anchorId);
    if (!target) return;
    event.preventDefault();
    const sourceId = anchorId.startsWith("source-")
      ? anchorId.slice("source-".length)
      : anchorId.startsWith("missing-source-")
        ? anchorId.slice("missing-source-".length)
        : null;
    setActiveSourceId(sourceId);
    window.history.replaceState(null, "", `#${anchorId}`);
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <section className="panel report-panel">
      <h2>Report</h2>
      {markdown ? (
        <ReactMarkdown
          components={{
            a({ href, children, ...props }) {
              const sourceLink = href?.startsWith("#source-");
              const missingSourceLink = href?.startsWith("#missing-source-");
              const sourceId = sourceLink ? href?.slice("#source-".length) : undefined;
              const source = sourceId ? sourceMap.get(sourceId) : undefined;
              return (
                <a
                  className={
                    sourceLink || missingSourceLink
                      ? `source-token-link${missingSourceLink ? " missing" : ""}${
                          sourceId && activeSourceId === sourceId ? " active" : ""
                        }`
                      : undefined
                  }
                  data-source-id={sourceId}
                  href={href}
                  onClick={(event) => handleSourceJump(event, href)}
                  title={
                    missingSourceLink
                      ? "Missing source token"
                      : source
                        ? `${source.title} / ${sourceTypeLabel(source.source_type)} / ${Math.round(
                            source.confidence * 100,
                          )}%`
                        : undefined
                  }
                  {...props}
                >
                  {children}
                </a>
              );
            },
          }}
          remarkPlugins={[remarkGfm]}
        >
          {linkedMarkdown}
        </ReactMarkdown>
      ) : (
        <p>The writer has not produced a draft yet.</p>
      )}
      {sourceGroups.length > 0 ? (
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
              return (
                <a
                  className={`source-trace-chip${activeSourceId === group.sourceId ? " active" : ""}`}
                  href={`#source-${group.sourceId}`}
                  key={group.sourceId}
                  onClick={(event) => handleSourceJump(event, `#source-${group.sourceId}`)}
                  title={source.url || source.title}
                >
                  <strong>{source.title}</strong>
                  <span>{group.tokens.map((token) => `[source:${token}]`).join(", ")}</span>
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
                onClick={(event) => handleSourceJump(event, `#missing-source-${group.sourceId}`)}
                title="No matching RawSource id exists in this run."
              >
                <strong>{group.sourceId}</strong>
                <span>{group.tokens.map((token) => `[source:${token}]`).join(", ")}</span>
                <em>{group.count} unresolved cite</em>
              </a>
            ))}
          </div>
        </div>
      ) : null}
      <div className="source-strip">
        {sources.map((source) => (
          <span
            className={citedSourceIds.has(source.id) ? "cited" : undefined}
            key={source.id}
            title={`${source.source_type} / ${source.content_hash}`}
          >
            {source.dimension} / {sourceTypeLabel(source.source_type)} /{" "}
            {Math.round(source.confidence * 100)}%
          </span>
        ))}
      </div>
      {sources.length > 0 ? (
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
                <strong>{source.title}</strong>
                <span>
                  {source.covered_competitors.length > 0 ? source.covered_competitors.join(", ") : source.competitor} /{" "}
                  {source.dimension} / {source.source_type}
                </span>
              </div>
              <code>{source.id}</code>
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
      ) : null}
      {missingSourceGroups.length > 0 ? (
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
      ) : null}
    </section>
  );
}

interface SourceTokenGroup {
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
) {
  return markdown.replace(SOURCE_TOKEN_RE, (token, sourceId: string) => {
    const normalizedSourceId = resolveSourceId(sourceId, sourceMap, sourceAliases);
    const target = sourceMap.has(normalizedSourceId)
      ? `#source-${normalizedSourceId}`
      : `#missing-source-${normalizedSourceId}`;
    return `[${token}](${target})`;
  });
}

export function extractSourceTokens(markdown: string) {
  return Array.from(markdown.matchAll(SOURCE_TOKEN_RE), (match) => match[1]);
}

function normalizeSourceToken(token: string) {
  return token.split("#", 1)[0];
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

function sourceTypeLabel(sourceType: string) {
  if (sourceType === "webpage_verified") return "fetched";
  if (sourceType === "survey_simulated" || sourceType === "interview_record") return "research";
  if (sourceType === "web_search_result") return "search";
  return "llm";
}
