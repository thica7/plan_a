import type { RunEvent } from "../../api/sse_types";
import type { DecisionReplayReport, RunMetrics, TraceSpan } from "../../api/types";
import { formatDecisionPayload, formatSpanMeta, type ContextRow } from "./traceModel";

export function TraceMetricsBar({
  metrics,
  toolSpanCount,
}: {
  metrics: RunMetrics;
  toolSpanCount: number;
}) {
  const items = [
    ["Spans", metrics.total_spans],
    ["Duration", `${metrics.total_duration_ms}ms`],
    ["LLM", metrics.llm_calls],
    ["Search", metrics.search_calls],
    ["Fetch", metrics.fetch_calls],
    ["Tool", toolSpanCount],
    ["Tokens est.", metrics.input_tokens_estimate + metrics.output_tokens_estimate],
    ["Coverage", `${Math.round(metrics.source_coverage_rate * 100)}%`],
    ["Verified", `${Math.round(metrics.verified_source_rate * 100)}%`],
    ["Cited claims", `${Math.round(metrics.claim_citation_rate * 100)}%`],
    ["Schema", `${Math.round(metrics.schema_pass_rate * 100)}%`],
    ["QA", metrics.qa_issue_count],
  ];
  return (
    <div className="trace-metrics">
      {items.map(([label, value]) => (
        <span key={label}>
          {label}
          <strong>{value}</strong>
        </span>
      ))}
    </div>
  );
}

export function DecisionReplaySection({ replay }: { replay: DecisionReplayReport | null | undefined }) {
  if (!replay) return null;
  const replayEvents = replay.events.slice(0, 12);
  return (
    <div className="decision-replay">
      <div className="panel-heading-row">
        <h3>Decision replay</h3>
        <span className="muted-text">{replay.replay_coverage_score}% coverage</span>
      </div>
      <div className="trace-metrics compact">
        <span>
          Events
          <strong>{replay.event_count}</strong>
        </span>
        <span>
          Blockers
          <strong>{replay.blocker_count}</strong>
        </span>
        <span>
          Warnings
          <strong>{replay.warn_count}</strong>
        </span>
        <span>
          Types
          <strong>{Object.keys(replay.event_type_counts).length}</strong>
        </span>
      </div>
      {replayEvents.length > 0 ? (
        <ol className="trace-list replay-list">
          {replayEvents.map((event) => {
            const payloadSummary = formatDecisionPayload(event);
            return (
              <li key={event.id}>
                <span>{event.source_event_id ?? "S"}</span>
                <strong>{event.event_type}</strong>
                <em>
                  {event.agent || "system"}
                  {event.subagent ? `/${event.subagent}` : ""}
                </em>
                <p>{event.message}</p>
                <small>
                  {event.evidence_ids.length} evidence / {event.claim_ids.length} claims /{" "}
                  {event.related_span_ids.length} spans
                </small>
                {payloadSummary ? <small className="replay-payload">{payloadSummary}</small> : null}
              </li>
            );
          })}
        </ol>
      ) : (
        <p>No replay events yet.</p>
      )}
    </div>
  );
}

export function ContextRows({ rows }: { rows: ContextRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="context-list" aria-label="Subagent contexts">
      {rows.map((row) => (
        <article key={row.contextId}>
          <div>
            <strong>
              {row.agent}
              {row.subagent ? `/${row.subagent}` : ""}
            </strong>
            <code>{row.shortContextId}</code>
          </div>
          <span>LLM {row.llm}</span>
          <span>Search {row.search}</span>
          <span>Fetch {row.fetch}</span>
          <span>Tool {row.tool}</span>
          <em>
            {row.messageCount} messages / {row.toolCallCount} tool calls
          </em>
        </article>
      ))}
    </div>
  );
}

export function SpanList({ spans }: { spans: TraceSpan[] }) {
  if (spans.length === 0) return null;
  return (
    <ol className="span-list">
      {spans.map((span) => (
        <li key={span.id} className={span.status}>
          <div>
            <strong>{span.kind}</strong>
            <span>
              {span.agent}
              {span.subagent ? `/${span.subagent}` : ""}
            </span>
          </div>
          <div>
            <em>{span.name}</em>
            <span>
              {span.duration_ms}ms / in {span.input_tokens_estimate} / out {span.output_tokens_estimate}
            </span>
            <small>{formatSpanMeta(span)}</small>
          </div>
          <p>{span.input_preview}</p>
          <p>{span.output_preview}</p>
        </li>
      ))}
    </ol>
  );
}

export function EventList({ events }: { events: RunEvent[] }) {
  if (events.length === 0) return <p>No trace events yet.</p>;
  return (
    <ol className="trace-list">
      {events.map((event) => (
        <li key={event.id}>
          <span>{event.id}</span>
          <strong>{event.type}</strong>
          <em>
            {event.agent || "system"}
            {event.subagent ? `/${event.subagent}` : ""}
          </em>
          <p>{event.message}</p>
        </li>
      ))}
    </ol>
  );
}
