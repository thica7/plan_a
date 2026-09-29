import type { DecisionReplayEvent, TraceSpan } from "../../api/types";
import { translate, type Locale } from "../../stores/i18n";
import { displayLabel, displayScope } from "../../i18n/display";

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

export function formatSpanMeta(span: TraceSpan, locale: Locale = "en-US") {
  const t = (key: string) => translate(key, locale);
  const parts: string[] = [];
  const provider = span.provider ?? span.model;
  if (provider) parts.push(String(provider));
  const contextId = span.metadata.context_id;
  if (typeof contextId === "string") parts.push(contextId.split(":").slice(-2).join(":"));
  const kbWarmStartSummary = formatRagKbWarmStartSpan(span, locale);
  if (kbWarmStartSummary) parts.push(kbWarmStartSummary);
  const resultCount = span.metadata.result_count;
  if (typeof resultCount === "number") parts.push(`${resultCount} ${t('trace.results')}`);
  const validCount = span.metadata.valid_count;
  const unknownCount = span.metadata.unknown_count;
  if (typeof validCount === "number") parts.push(`${validCount} ${t('trace.validRefs')}`);
  if (typeof unknownCount === "number" && unknownCount > 0) parts.push(`${unknownCount} ${t('trace.unknownRefs')}`);
  return parts.join(" / ");
}

export function formatRagKbWarmStartSpan(span: TraceSpan, locale: Locale = "en-US") {
  const t = (key: string) => translate(key, locale);
  if (span.name !== "rag_kb_warm_start") return "";
  const hitCount = numberMetaOrNull(span, "hit_count");
  const sourceCount = numberMetaOrNull(span, "source_count");
  const rejectionCount = numberMetaOrNull(span, "rejection_count");
  const output = parseSpanOutput(span);
  const rejections = arrayValue(output?.rejections);
  const rejectionSummary = rejections.map((item) => formatKbRejection(item, locale)).filter(Boolean).slice(0, 3);
  const hiddenRejections =
    rejectionCount !== null ? Math.max(0, rejectionCount - rejectionSummary.length) : 0;
  const parts: string[] = [];
  if (hitCount !== null) parts.push(`${hitCount} ${t('trace.kbHits')}`);
  if (sourceCount !== null) parts.push(`${sourceCount} ${t('trace.accepted')}`);
  if (rejectionCount !== null) parts.push(`${rejectionCount} ${t('trace.rejected')}`);
  if (rejectionSummary.length > 0) {
    parts.push(
      `${t('trace.rejections')} ${rejectionSummary.join("; ")}${hiddenRejections > 0 ? ` +${hiddenRejections}` : ""}`,
    );
  }
  const topReason = stringValue(span.metadata.top_rejection_reason);
  if (rejectionSummary.length === 0 && topReason) parts.push(`${t('trace.topRejection')} ${locale === 'zh-CN' ? displayLabel(topReason, locale) : topReason}`);
  return parts.join(" / ");
}

export function formatDecisionPayload(event: DecisionReplayEvent, locale: Locale = "en-US") {
  const t = (key: string) => translate(key, locale);
  const label = (value: string) => locale === 'zh-CN' ? displayScope(value, locale) : value;
  const parts: string[] = [];
  if (event.event_type === "claim.validated") {
    const claimCount = numberPayload(event, "claim_count") ?? arrayPayload(event, "claim_ids").length;
    const sourceCount = numberPayload(event, "source_count") ?? arrayPayload(event, "evidence_ids").length;
    const statusCounts = objectPayload(event, "claim_status_counts");
    const releaseGate = objectPayload(event, "release_gate");
    if (claimCount > 0) parts.push(`${claimCount} ${t('trace.validatedClaims')}`);
    if (sourceCount > 0) parts.push(`${sourceCount} ${t('trace.scopedSources')}`);
    if (statusCounts) {
      const supported = numberValue(statusCounts.supported) ?? 0;
      const weak = numberValue(statusCounts.weak) ?? 0;
      const blocked = numberValue(statusCounts.blocked) ?? 0;
      parts.push(`${t('trace.supported')} ${supported} / ${t('trace.weak')} ${weak} / ${t('trace.blocked')} ${blocked}`);
    }
    if (releaseGate) {
      const status = stringValue(releaseGate.status);
      const issues = numberValue(releaseGate.issue_count);
      if (status) parts.push(`${t('trace.releaseGate')} ${label(status)}`);
      if (issues !== null) parts.push(`${issues} ${t('trace.gateIssues')}`);
    }
  }
  if (event.event_type === "self_consistency.sampled") {
    const score = numberPayload(event, "self_consistency_score");
    const votes = objectPayload(event, "consistency_votes");
    const minoritySamples = arrayPayload(event, "minority_validation_samples");
    if (score !== null) parts.push(`${t('trace.score')} ${score}`);
    if (minoritySamples.length > 0) parts.push(`${minoritySamples.length} ${t('trace.minoritySamples')}`);
    if (votes) {
      const textSupport = numberValue(votes.text_support) ?? 0;
      const evidenceQuality = numberValue(votes.evidence_quality) ?? 0;
      const triangulation = numberValue(votes.triangulation) ?? 0;
      parts.push(`${t('trace.votesText')} ${textSupport} / ${t('trace.quality')} ${evidenceQuality} / ${t('trace.triangulation')} ${triangulation}`);
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
    if (query) parts.push(`${t('trace.query')}: ${query}`);
    if (!query && retrievalQueries.length > 0) parts.push(`${retrievalQueries.length} ${t('trace.retrievalQueries')}`);
    if (retrievalContexts.length > 0) parts.push(`${retrievalContexts.length} ${t('trace.gapContexts')}`);
    if (chunkIds.length > 0) parts.push(`${chunkIds.length} ${t('trace.chunks')}`);
    if (rerankScores) parts.push(`${Object.keys(rerankScores).length} ${t('trace.rerankScores')}`);
    if (gapLinks) parts.push(`${Object.keys(gapLinks).length} ${t('trace.linkedGaps')}`);
    if (resultCount !== null) parts.push(`${resultCount} ${t('trace.results')}`);
    if (candidateUrls.length > 0) parts.push(`${candidateUrls.length} ${t('trace.candidateUrls')}`);
  }
  if (event.event_type === "memory.recalled") {
    const score = numberPayload(event, "score") ?? numberPayload(event, "recall_score");
    const candidates = arrayPayload(event, "candidate_ids");
    if (score !== null) parts.push(`${t('trace.recall')} ${score}`);
    if (candidates.length > 0) parts.push(`${candidates.length} ${t('trace.memories')}`);
  }
  if (event.event_type === "memory.feedback_captured") {
    const feedbackId = stringPayload(event, "feedback_id");
    const candidateCount = numberPayload(event, "candidate_count") ?? arrayPayload(event, "candidate_ids").length;
    const targetType = stringPayload(event, "target_type");
    const candidateKinds = stringArrayPayload(event, "candidate_kinds");
    const candidateStatuses = stringArrayPayload(event, "candidate_statuses");
    const redactionCounts = objectPayload(event, "redaction_counts");
    const messageExcerpt = stringPayload(event, "message_excerpt");
    if (feedbackId) parts.push(`${t('trace.feedback')} ${feedbackId}`);
    if (candidateCount > 0) parts.push(`${candidateCount} ${t('trace.candidates')}`);
    if (candidateKinds.length > 0) parts.push(`${t('trace.kinds')} ${candidateKinds.map(label).join(", ")}`);
    if (candidateStatuses.length > 0) parts.push(`${t('trace.statuses')} ${candidateStatuses.map(label).join(", ")}`);
    if (targetType) parts.push(`${t('trace.target')} ${label(targetType)}`);
    if (redactionCounts) parts.push(`${Object.keys(redactionCounts).length} ${t('trace.redactionTypes')}`);
    if (messageExcerpt) parts.push(clipPayloadText(messageExcerpt));
  }
  if (event.event_type === "hitl.reviewed") {
    const decision = stringPayload(event, "decision");
    const stage = stringPayload(event, "stage") ?? event.subagent;
    const dimensions = arrayPayload(event, "dimensions");
    if (decision) parts.push(`${t('trace.decision')} ${label(decision)}`);
    if (stage) parts.push(`${t('trace.stage')} ${label(stage)}`);
    if (dimensions.length > 0) parts.push(`${dimensions.length} ${t('trace.dimensions')}`);
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
    if (issueId) parts.push(`${t('trace.issue')} ${issueId}`);
    if (problem) parts.push(clipPayloadText(problem));
    if (severity) parts.push(`${t('trace.severity')} ${label(severity)}`);
    if (kind) parts.push(`${t('trace.scope')} ${label(kind)}`);
    if (!kind && scopeText) parts.push(`${t('trace.scope')} ${label(scopeText)}`);
    if (subagent) parts.push(`${t('trace.subagent')} ${label(subagent)}`);
    if (competitor) parts.push(`${t('trace.competitor')} ${competitor}`);
    if (claimCount > 0) parts.push(`${claimCount} ${t('trace.claims')}`);
    if (evidenceCount > 0) parts.push(`${evidenceCount} ${t('trace.evidence')}`);
  }
  if (event.event_type === "benchmark.scored") {
    const score = numberPayload(event, "score");
    if (score !== null) parts.push(`${t('trace.score')} ${score}`);
  }
  if (event.event_type === "report.ready") {
    const versionId = stringPayload(event, "updated_report_version_id") || stringPayload(event, "report_version_id");
    const releaseDelta = objectPayload(event, "release_gate_delta");
    const gapLinks = objectPayload(event, "gap_evidence_links");
    if (versionId) parts.push(`${t('trace.version')} ${versionId}`);
    if (gapLinks) parts.push(`${Object.keys(gapLinks).length} ${t('trace.linkedGaps')}`);
    if (releaseDelta) {
      const improved = booleanValue(releaseDelta.release_gate_improved);
      const blockerDelta = numberValue(releaseDelta.release_gate_blocker_delta);
      const readinessDelta = numberValue(releaseDelta.readiness_score_delta);
      if (improved !== null) parts.push(`${t('trace.gateImproved')} ${improved ? t('trace.yes') : t('trace.no')}`);
      if (blockerDelta !== null) parts.push(`${t('trace.blockerDelta')} ${blockerDelta}`);
      if (readinessDelta !== null) parts.push(`${t('trace.readiness')} ${readinessDelta}`);
    }
  }
  return parts.join(" / ");
}

export function formatModuleExecutionStatus(payload: Record<string, unknown>, locale: Locale = "en-US") {
  const t = (key: string) => translate(key, locale);
  const moduleStatus = stringValue(payload.module_status);
  const fallback = objectValue(payload.fallback);
  const fallbackUsed = fallback ? booleanValue(fallback.used) : null;
  if (moduleStatus === "fallback" || fallbackUsed === true) {
    const reason = fallback ? stringValue(fallback.reason) : "";
    const timeoutSeconds = fallback ? numberValue(fallback.timeout_seconds) : null;
    const error = fallback ? stringValue(fallback.error) : "";
    const parts = [t('trace.fallback')];
    if (reason) parts.push(locale === 'zh-CN' ? displayLabel(reason, locale) : reason);
    if (timeoutSeconds !== null) parts.push(`${timeoutSeconds}${t('common.seconds')}`);
    if (error) parts.push(clipPayloadText(error));
    return parts.join(": ");
  }
  if (moduleStatus === "llm" || fallbackUsed === false) {
    return locale === 'zh-CN' ? displayLabel('llm', locale) : "LLM";
  }
  return "";
}

function numberPayload(event: DecisionReplayEvent, key: string) {
  return numberValue(event.payload[key]);
}

function stringPayload(event: DecisionReplayEvent, key: string) {
  return stringValue(event.payload[key]);
}

function objectPayload(event: DecisionReplayEvent, key: string) {
  return objectValue(event.payload[key]);
}

function arrayPayload(event: DecisionReplayEvent, key: string) {
  const value = event.payload[key];
  return arrayValue(value);
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

function objectValue(value: unknown) {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function arrayValue(value: unknown) {
  return Array.isArray(value) ? value : [];
}

function clipPayloadText(value: string) {
  return value.length > 140 ? `${value.slice(0, 137)}...` : value;
}

function numberMeta(span: TraceSpan, key: string) {
  const value = span.metadata[key];
  return typeof value === "number" ? value : 0;
}

function numberMetaOrNull(span: TraceSpan, key: string) {
  const value = span.metadata[key];
  return typeof value === "number" ? value : null;
}

function parseSpanOutput(span: TraceSpan) {
  const text = span.full_output || span.output_preview;
  if (!text) return null;
  try {
    return objectValue(JSON.parse(text));
  } catch {
    return null;
  }
}

function formatKbRejection(value: unknown, locale: Locale) {
  const item = objectValue(value);
  if (!item) return "";
  const rawReason = stringValue(item.reason) || "rejected";
  const reason = locale === 'zh-CN' ? displayLabel(rawReason, locale) : rawReason;
  const rank = numberValue(item.rank);
  const documentId = stringValue(item.document_id);
  const chunkId = stringValue(item.chunk_id);
  const sourceType = stringValue(item.source_type);
  const locator = documentId || chunkId;
  const parts = [`${reason}${rank !== null ? `@${rank}` : ""}`];
  if (locator) parts.push(locator);
  if (sourceType) parts.push(locale === 'zh-CN' ? displayLabel(sourceType, locale) : sourceType);
  return parts.join(" ");
}
