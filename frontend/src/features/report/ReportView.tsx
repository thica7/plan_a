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
              return (
                <a className={sourceLink ? "source-token-link" : undefined} href={href} {...props}>
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
            {source.dimension} / {source.source_type === "webpage_verified" ? "fetched" : "llm"} /{" "}
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
    </section>
  );
}

function linkSourceTokens(markdown: string, sourceIds: Set<string>) {
  return markdown.replace(/\[source:([A-Za-z0-9_.:-]+)\]/g, (token, sourceId: string) => {
    const target = sourceIds.has(sourceId) ? `#source-${sourceId}` : "#source-list";
    return `[${token}](${target})`;
  });
}
