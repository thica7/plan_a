import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { RawSource } from "../../api/types";

interface Props {
  markdown: string;
  sources: RawSource[];
}

export function ReportView({ markdown, sources }: Props) {
  const sourceIds = useMemo(() => new Set(sources.map((source) => source.id)), [sources]);
  const missingSourceIds = useMemo(
    () =>
      extractSourceTokens(markdown).filter(
        (sourceId, index, tokens) => !sourceIds.has(sourceId) && tokens.indexOf(sourceId) === index,
      ),
    [markdown, sourceIds],
  );
  const linkedMarkdown = useMemo(
    () => linkSourceTokens(markdown, sourceIds),
    [markdown, sourceIds],
  );
  return (
    <section className="panel report-panel">
      <h2>Report</h2>
      {markdown ? (
        <ReactMarkdown
          components={{
            a({ href, children, ...props }) {
              const sourceLink = href?.startsWith("#source-");
              const missingSourceLink = href?.startsWith("#missing-source-");
              return (
                <a
                  className={
                    sourceLink || missingSourceLink
                      ? `source-token-link${missingSourceLink ? " missing" : ""}`
                      : undefined
                  }
                  href={href}
                  title={missingSourceLink ? "Missing source token" : undefined}
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
      <div className="source-strip">
        {sources.map((source) => (
          <span key={source.id} title={`${source.source_type} / ${source.content_hash}`}>
            {source.dimension} / {sourceTypeLabel(source.source_type)} /{" "}
            {Math.round(source.confidence * 100)}%
          </span>
        ))}
      </div>
      {sources.length > 0 ? (
        <div className="source-list" id="source-list">
          <h3>Evidence</h3>
          {sources.map((source) => (
            <article className="source-card" id={`source-${source.id}`} key={source.id}>
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
      {missingSourceIds.length > 0 ? (
        <div className="missing-source-list" id="missing-source-list">
          <h3>Missing sources</h3>
          {missingSourceIds.map((sourceId) => (
            <article className="missing-source-card" id={`missing-source-${sourceId}`} key={sourceId}>
              <strong>[source:{sourceId}]</strong>
              <span>No matching RawSource id exists in this run.</span>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function linkSourceTokens(markdown: string, sourceIds: Set<string>) {
  return markdown.replace(/\[source:([A-Za-z0-9_.:-]+)\]/g, (token, sourceId: string) => {
    const target = sourceIds.has(sourceId) ? `#source-${sourceId}` : `#missing-source-${sourceId}`;
    return `[${token}](${target})`;
  });
}

function extractSourceTokens(markdown: string) {
  return Array.from(markdown.matchAll(/\[source:([A-Za-z0-9_.:-]+)\]/g), (match) => match[1]);
}

function sourceTypeLabel(sourceType: string) {
  if (sourceType === "webpage_verified") return "fetched";
  if (sourceType === "survey_simulated" || sourceType === "interview_record") return "research";
  if (sourceType === "web_search_result") return "search";
  return "llm";
}
