import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { RawSource } from "../../api/types";

interface Props {
  markdown: string;
  sources: RawSource[];
}

export function ReportView({ markdown, sources }: Props) {
  return (
    <section className="panel report-panel">
      <h2>Report</h2>
      {markdown ? (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
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
        <div className="source-list">
          <h3>Evidence</h3>
          {sources.map((source) => (
            <article className="source-card" key={source.id}>
              <div>
                <strong>{source.title}</strong>
                <span>
                  {source.covered_competitors.length > 0 ? source.covered_competitors.join(", ") : source.competitor} /{" "}
                  {source.dimension} / {source.source_type}
                </span>
              </div>
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
