import type { RunEvent } from "../../api/sse_types";
import type { DecisionReplayEvent, DecisionReplayReport, RunMetrics, TraceSpan } from "../../api/types";

interface Props {
  events: RunEvent[];
  metrics: RunMetrics;
  spans: TraceSpan[];
  replay?: DecisionReplayReport | null;
}

export function TraceList({ events, metrics, spans, replay }: Props) {
  const contextRows = buildContextRows(spans);
  const replayEvents = replay?.events.slice(0, 12) ?? [];

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
          Schema
          <strong>{Math.round(metrics.schema_pass_rate * 100)}%</strong>
        </span>
        <span>
          QA
          <strong>{metrics.qa_issue_count}</strong>
        </span>
      </div>
      {replay ? (
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
                    <em>{event.agent || "system"}{event.subagent ? `/${event.subagent}` : ""}</em>
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
      ) : null}
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

export function formatDecisionPayload(event: DecisionReplayEvent) {
  const parts: string[] = [];
  if (event.event_type === "claim.validated") {
    const claimCount = numberPayload(event, "claim_count") ?? arrayPayload(event, "claim_ids").length;
    const sourceCount = numberPayload(event, "source_count") ?? arrayPayload(event, "evidence_ids").length;
    const statusCounts = objectPayload(event, "claim_status_counts");
    const releaseGate = objectPayload(event, "release_gate");
    if (claimCount > 0) parts.push(`${claimCount} validated claims`);
    if (sourceCount > 0) parts.push(`${sourceCount} scoped sources`);
    if (statusCounts) {
      const supported = numberValue(statusCounts.supported) ?? 0;
      const weak = numberValue(statusCounts.weak) ?? 0;
      const blocked = numberValue(statusCounts.blocked) ?? 0;
      parts.push(`supported ${supported} / weak ${weak} / blocked ${blocked}`);
    }
    if (releaseGate) {
      const status = stringValue(releaseGate.status);
      const issues = numberValue(releaseGate.issue_count);
      if (status) parts.push(`release gate ${status}`);
      if (issues !== null) parts.push(`${issues} gate issues`);
    }
  }
  if (event.event_type === "self_consistency.sampled") {
    const score = numberPayload(event, "self_consistency_score");
    const votes = objectPayload(event, "consistency_votes");
    const minoritySamples = arrayPayload(event, "minority_validation_samples");
    if (score !== null) parts.push(`score ${score}`);
    if (minoritySamples.length > 0) parts.push(`${minoritySamples.length} minority samples`);
    if (votes) {
      const textSupport = numberValue(votes.text_support) ?? 0;
      const evidenceQuality = numberValue(votes.evidence_quality) ?? 0;
      const triangulation = numberValue(votes.triangulation) ?? 0;
      parts.push(
        `votes text ${textSupport} / quality ${evidenceQuality} / triangulation ${triangulation}`,
      );
    }
  }
  if (event.event_type === "rag.retrieved") {
    const query = stringPayload(event, "query");
    const retrievalQueries = arrayPayload(event, "retrieval_queries");
    const retrievalContexts = arrayPayload(event, "retrieval_contexts");
    const chunkIds = arrayPayload(event, "chunk_ids");
    const rerankScores = objectPayload(event, "rerank_scores");
    const resultCount = numberPayload(event, "result_count");
    const candidateUrls = arrayPayload(event, "candidate_urls");
    if (query) parts.push(`query: ${query}`);
    if (!query && retrievalQueries.length > 0) parts.push(`${retrievalQueries.length} retrieval queries`);
    if (retrievalContexts.length > 0) parts.push(`${retrievalContexts.length} gap contexts`);
    if (chunkIds.length > 0) parts.push(`${chunkIds.length} chunks`);
    if (rerankScores) parts.push(`${Object.keys(rerankScores).length} rerank scores`);
    if (resultCount !== null) parts.push(`${resultCount} results`);
    if (candidateUrls.length > 0) parts.push(`${candidateUrls.length} candidate URLs`);
  }
  if (event.event_type === "memory.recalled") {
    const score = numberPayload(event, "score") ?? numberPayload(event, "recall_score");
    const candidates = arrayPayload(event, "candidate_ids");
    if (score !== null) parts.push(`recall ${score}`);
    if (candidates.length > 0) parts.push(`${candidates.length} memories`);
  }
  if (event.event_type === "memory.feedback_captured") {
    const feedbackId = stringPayload(event, "feedback_id");
    const candidateCount =
      numberPayload(event, "candidate_count") ?? arrayPayload(event, "candidate_ids").length;
    const targetType = stringPayload(event, "target_type");
    if (feedbackId) parts.push(`feedback ${feedbackId}`);
    if (candidateCount > 0) parts.push(`${candidateCount} candidates`);
    if (targetType) parts.push(`target ${targetType}`);
  }
  if (event.event_type === "hitl.reviewed") {
    const decision = stringPayload(event, "decision");
    const stage = stringPayload(event, "stage") ?? event.subagent;
    const dimensions = arrayPayload(event, "dimensions");
    if (decision) parts.push(`decision ${decision}`);
    if (stage) parts.push(`stage ${stage}`);
    if (dimensions.length > 0) parts.push(`${dimensions.length} dimensions`);
  }
  if (event.event_type === "qa.blocked" || event.event_type === "redo.routed") {
    const issueId = stringPayload(event, "issue_id");
    const problem = stringPayload(event, "problem");
    const severity = stringPayload(event, "severity");
    const scope = objectPayload(event, "redo_scope");
    const scopeText = stringPayload(event, "redo_scope");
    const kind = scope ? stringValue(scope.kind) : "";
    const subagent = scope ? stringValue(scope.target_subagent) : "";
    const competitor = scope ? stringValue(scope.target_competitor) : "";
    const claimCount = arrayPayload(event, "claim_ids").length || event.claim_ids.length;
    const evidenceCount = arrayPayload(event, "evidence_ids").length || event.evidence_ids.length;
    if (issueId) parts.push(`issue ${issueId}`);
    if (problem) parts.push(clipPayloadText(problem));
    if (severity) parts.push(`severity ${severity}`);
    if (kind) parts.push(`scope ${kind}`);
    if (!kind && scopeText) parts.push(`scope ${scopeText}`);
    if (subagent) parts.push(`subagent ${subagent}`);
    if (competitor) parts.push(`competitor ${competitor}`);
    if (claimCount > 0) parts.push(`${claimCount} claims`);
    if (evidenceCount > 0) parts.push(`${evidenceCount} evidence`);
  }
  if (event.event_type === "benchmark.scored") {
    const score = numberPayload(event, "score");
    if (score !== null) parts.push(`score ${score}`);
  }
  if (event.event_type === "report.ready") {
    const versionId =
      stringPayload(event, "updated_report_version_id") ||
      stringPayload(event, "report_version_id");
    const releaseDelta = objectPayload(event, "release_gate_delta");
    if (versionId) parts.push(`version ${versionId}`);
    if (releaseDelta) {
      const improved = booleanValue(releaseDelta.release_gate_improved);
      const blockerDelta = numberValue(releaseDelta.release_gate_blocker_delta);
      const readinessDelta = numberValue(releaseDelta.readiness_score_delta);
      if (improved !== null) parts.push(`gate improved ${improved ? "yes" : "no"}`);
      if (blockerDelta !== null) parts.push(`blocker delta ${blockerDelta}`);
      if (readinessDelta !== null) parts.push(`readiness ${readinessDelta}`);
    }
  }
  return parts.join(" / ");
}

function numberPayload(event: DecisionReplayEvent, key: string) {
  return numberValue(event.payload[key]);
}

function stringPayload(event: DecisionReplayEvent, key: string) {
  return stringValue(event.payload[key]);
}

function objectPayload(event: DecisionReplayEvent, key: string) {
  const value = event.payload[key];
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function arrayPayload(event: DecisionReplayEvent, key: string) {
  const value = event.payload[key];
  return Array.isArray(value) ? value : [];
}

function numberValue(value: unknown) {
  return typeof value === "number" ? value : null;
}

function booleanValue(value: unknown) {
  return typeof value === "boolean" ? value : null;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function clipPayloadText(value: string) {
  return value.length > 140 ? `${value.slice(0, 137)}...` : value;
}

function numberMeta(span: TraceSpan, key: string) {
  const value = span.metadata[key];
  return typeof value === "number" ? value : 0;
}
