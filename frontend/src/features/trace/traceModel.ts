import type { DecisionReplayEvent, TraceSpan } from "../../api/types";

export interface ContextRow {
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

export function buildContextRows(spans: TraceSpan[]): ContextRow[] {
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

export function formatSpanMeta(span: TraceSpan) {
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
      parts.push(`votes text ${textSupport} / quality ${evidenceQuality} / triangulation ${triangulation}`);
    }
  }
  if (event.event_type === "rag.retrieved") {
    const query = stringPayload(event, "query");
    const retrievalQueries = arrayPayload(event, "retrieval_queries");
    const retrievalContexts = arrayPayload(event, "retrieval_contexts");
    const chunkIds = arrayPayload(event, "chunk_ids");
    const rerankScores = objectPayload(event, "rerank_scores");
    const gapLinks = objectPayload(event, "gap_evidence_links");
    const resultCount = numberPayload(event, "result_count");
    const candidateUrls = arrayPayload(event, "candidate_urls");
    if (query) parts.push(`query: ${query}`);
    if (!query && retrievalQueries.length > 0) parts.push(`${retrievalQueries.length} retrieval queries`);
    if (retrievalContexts.length > 0) parts.push(`${retrievalContexts.length} gap contexts`);
    if (chunkIds.length > 0) parts.push(`${chunkIds.length} chunks`);
    if (rerankScores) parts.push(`${Object.keys(rerankScores).length} rerank scores`);
    if (gapLinks) parts.push(`${Object.keys(gapLinks).length} linked gaps`);
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
    const candidateCount = numberPayload(event, "candidate_count") ?? arrayPayload(event, "candidate_ids").length;
    const targetType = stringPayload(event, "target_type");
    const candidateKinds = stringArrayPayload(event, "candidate_kinds");
    const candidateStatuses = stringArrayPayload(event, "candidate_statuses");
    const redactionCounts = objectPayload(event, "redaction_counts");
    const messageExcerpt = stringPayload(event, "message_excerpt");
    if (feedbackId) parts.push(`feedback ${feedbackId}`);
    if (candidateCount > 0) parts.push(`${candidateCount} candidates`);
    if (candidateKinds.length > 0) parts.push(`kinds ${candidateKinds.join(", ")}`);
    if (candidateStatuses.length > 0) parts.push(`statuses ${candidateStatuses.join(", ")}`);
    if (targetType) parts.push(`target ${targetType}`);
    if (redactionCounts) parts.push(`${Object.keys(redactionCounts).length} redaction types`);
    if (messageExcerpt) parts.push(clipPayloadText(messageExcerpt));
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
    const versionId = stringPayload(event, "updated_report_version_id") || stringPayload(event, "report_version_id");
    const releaseDelta = objectPayload(event, "release_gate_delta");
    const gapLinks = objectPayload(event, "gap_evidence_links");
    if (versionId) parts.push(`version ${versionId}`);
    if (gapLinks) parts.push(`${Object.keys(gapLinks).length} linked gaps`);
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
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function arrayPayload(event: DecisionReplayEvent, key: string) {
  const value = event.payload[key];
  return Array.isArray(value) ? value : [];
}

function stringArrayPayload(event: DecisionReplayEvent, key: string) {
  return arrayPayload(event, key).filter((item): item is string => typeof item === "string");
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
