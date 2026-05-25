import type { RunEvent } from "../../api/sse_types";
import type { RunMetrics, TraceSpan } from "../../api/types";

interface Props {
  events: RunEvent[];
  metrics: RunMetrics;
  spans: TraceSpan[];
}

export function TraceList({ events, metrics, spans }: Props) {
  const contextRows = buildContextRows(spans);

  return (
    <section className="panel trace-panel">
      <h2>Trace</h2>
      <div className="trace-metrics">
        <span>
          Spans
          <strong>{metrics.total_spans}</strong>
        </span>
        <span>
          Duration
          <strong>{metrics.total_duration_ms}ms</strong>
        </span>
        <span>
          LLM
          <strong>{metrics.llm_calls}</strong>
        </span>
        <span>
          Search
          <strong>{metrics.search_calls}</strong>
        </span>
        <span>
          Fetch
          <strong>{metrics.fetch_calls}</strong>
        </span>
        <span>
          Tool
          <strong>{spans.filter((span) => span.kind === "tool").length}</strong>
        </span>
        <span>
          Tokens est.
          <strong>{metrics.input_tokens_estimate + metrics.output_tokens_estimate}</strong>
        </span>
        <span>
          Coverage
          <strong>{Math.round(metrics.source_coverage_rate * 100)}%</strong>
        </span>
        <span>
          Verified
          <strong>{Math.round(metrics.verified_source_rate * 100)}%</strong>
        </span>
        <span>
          Cited claims
          <strong>{Math.round(metrics.claim_citation_rate * 100)}%</strong>
        </span>
        <span>
          QA
          <strong>{metrics.qa_issue_count}</strong>
        </span>
      </div>
      {contextRows.length > 0 ? (
        <div className="context-list" aria-label="Subagent contexts">
          {contextRows.map((row) => (
            <article key={row.contextId}>
              <div>
                <strong>{row.agent}{row.subagent ? `/${row.subagent}` : ""}</strong>
                <code>{row.shortContextId}</code>
              </div>
              <span>LLM {row.llm}</span>
              <span>Search {row.search}</span>
              <span>Fetch {row.fetch}</span>
              <span>Tool {row.tool}</span>
              <em>{row.messageCount} messages / {row.toolCallCount} tool calls</em>
            </article>
          ))}
        </div>
      ) : null}
      {spans.length > 0 ? (
        <ol className="span-list">
          {spans.map((span) => (
            <li key={span.id} className={span.status}>
              <div>
                <strong>{span.kind}</strong>
                <span>{span.agent}{span.subagent ? `/${span.subagent}` : ""}</span>
              </div>
              <div>
                <em>{span.name}</em>
                <span>{span.duration_ms}ms / in {span.input_tokens_estimate} / out {span.output_tokens_estimate}</span>
                <small>{formatSpanMeta(span)}</small>
              </div>
              <p>{span.input_preview}</p>
              <p>{span.output_preview}</p>
            </li>
          ))}
        </ol>
      ) : null}
      {events.length === 0 ? (
        <p>No trace events yet.</p>
      ) : (
        <ol className="trace-list">
          {events.map((event) => (
            <li key={event.id}>
              <span>{event.id}</span>
              <strong>{event.type}</strong>
              <em>{event.agent || "system"}{event.subagent ? `/${event.subagent}` : ""}</em>
              <p>{event.message}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

interface ContextRow {
  contextId: string;
  shortContextId: string;
  agent: string;
  subagent?: string | null;
  llm: number;
  search: number;
  fetch: number;
  tool: number;
  messageCount: number;
  toolCallCount: number;
}

function buildContextRows(spans: TraceSpan[]): ContextRow[] {
  const rows = new Map<string, ContextRow>();
  spans.forEach((span) => {
    const contextId = span.metadata.context_id;
    if (typeof contextId !== "string" || !contextId) return;
    const row = rows.get(contextId) ?? {
      contextId,
      shortContextId: contextId.split(":").slice(-3).join(":"),
      agent: span.agent,
      subagent: span.subagent,
      llm: 0,
      search: 0,
      fetch: 0,
      tool: 0,
      messageCount: 0,
      toolCallCount: 0,
    };
    if (span.kind === "llm") row.llm += 1;
    if (span.kind === "search") row.search += 1;
    if (span.kind === "fetch") row.fetch += 1;
    if (span.kind === "tool") row.tool += 1;
    row.messageCount = Math.max(row.messageCount, numberMeta(span, "message_count"));
    row.toolCallCount = Math.max(row.toolCallCount, numberMeta(span, "tool_call_count"));
    rows.set(contextId, row);
  });
  return [...rows.values()].sort((left, right) =>
    `${left.agent}:${left.subagent ?? ""}`.localeCompare(`${right.agent}:${right.subagent ?? ""}`),
  );
}

function formatSpanMeta(span: TraceSpan) {
  const parts: string[] = [];
  const provider = span.provider ?? span.model;
  if (provider) parts.push(String(provider));
  const contextId = span.metadata.context_id;
  if (typeof contextId === "string") parts.push(contextId.split(":").slice(-2).join(":"));
  const resultCount = span.metadata.result_count;
  if (typeof resultCount === "number") parts.push(`${resultCount} results`);
  const validCount = span.metadata.valid_count;
  const unknownCount = span.metadata.unknown_count;
  if (typeof validCount === "number") parts.push(`${validCount} valid refs`);
  if (typeof unknownCount === "number" && unknownCount > 0) parts.push(`${unknownCount} unknown refs`);
  return parts.join(" / ");
}

function numberMeta(span: TraceSpan, key: string) {
  const value = span.metadata[key];
  return typeof value === "number" ? value : 0;
}
