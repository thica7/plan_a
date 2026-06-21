import { describe, expect, it } from "vitest";
import type { DecisionReplayEvent, TraceSpan } from "../../api/types";
import { formatDecisionPayload } from "./TraceList";
import { formatModuleExecutionStatus, formatRagKbWarmStartSpan, formatSpanMeta } from "./traceModel";

describe("TraceList decision replay formatting", () => {
  it("summarizes QA blocker issue identity and reason", () => {
    const event: DecisionReplayEvent = {
      id: "decision-1",
      run_id: "run-1",
      event_type: "qa.blocked",
      agent: "qa",
      subagent: "pricing",
      message: "Pricing evidence is missing.",
      related_span_ids: [],
      evidence_ids: [],
      claim_ids: [],
      payload: {
        issue_id: "missing-pricing",
        problem: "No evidence sources were collected for pricing.",
        severity: "blocker",
        redo_scope: {
          kind: "collector",
          target_subagent: "pricing",
        },
      },
      created_at: "2026-05-31T00:00:00Z",
    };

    const summary = formatDecisionPayload(event);

    expect(summary).toContain("issue missing-pricing");
    expect(summary).toContain("No evidence sources were collected for pricing.");
    expect(summary).toContain("severity blocker");
    expect(summary).toContain("scope collector");
    expect(summary).toContain("subagent pricing");
  });

  it("summarizes RAG gap evidence links", () => {
    const event: DecisionReplayEvent = {
      id: "decision-rag",
      run_id: "run-1",
      event_type: "rag.retrieved",
      agent: "rag_gap_fill",
      subagent: null,
      message: "Retrieved candidate evidence.",
      related_span_ids: [],
      evidence_ids: ["evidence-gap-1"],
      claim_ids: [],
      payload: {
        retrieval_queries: ["A SOC 2 SSO trust center"],
        retrieval_contexts: [{ gap_id: "gap-security" }],
        chunk_ids: ["chunk-gap-1"],
        rerank_scores: { "chunk-gap-1": 0.92 },
        gap_evidence_links: { "gap-security": ["evidence-gap-1"] },
      },
      created_at: "2026-05-31T00:00:00Z",
    };

    const summary = formatDecisionPayload(event);

    expect(summary).toContain("1 retrieval queries");
    expect(summary).toContain("1 gap contexts");
    expect(summary).toContain("1 chunks");
    expect(summary).toContain("1 rerank scores");
    expect(summary).toContain("1 linked gaps");
  });

  it("summarizes memory feedback audit candidate kinds and redaction", () => {
    const event: DecisionReplayEvent = {
      id: "decision-memory-feedback",
      run_id: "run-1",
      event_type: "memory.feedback_captured",
      agent: "memory",
      subagent: null,
      message: "Memory feedback captured.",
      related_span_ids: [],
      evidence_ids: [],
      claim_ids: [],
      payload: {
        feedback_id: "feedback-1",
        candidate_count: 2,
        candidate_kinds: ["source_preference", "domain_fact"],
        candidate_statuses: ["candidate"],
        target_type: "report",
        message_excerpt: "Prefer official sources and remember category benchmark context.",
        redaction_counts: { email: 1 },
      },
      created_at: "2026-05-31T00:00:00Z",
    };

    const summary = formatDecisionPayload(event);

    expect(summary).toContain("feedback feedback-1");
    expect(summary).toContain("2 candidates");
    expect(summary).toContain("kinds source_preference, domain_fact");
    expect(summary).toContain("statuses candidate");
    expect(summary).toContain("target report");
    expect(summary).toContain("1 redaction types");
    expect(summary).toContain("Prefer official sources");
  });

  it("summarizes module fallback and normal LLM status", () => {
    expect(
      formatModuleExecutionStatus({
        module_status: "fallback",
        fallback: {
          used: true,
          reason: "llm_error",
          error: "LLM returned empty content.",
        },
      }),
    ).toContain("Fallback: llm_error");

    expect(
      formatModuleExecutionStatus({
        module_status: "llm",
        fallback: { used: false },
      }),
    ).toBe("LLM");
  });

  it("summarizes rejected RAG KB warm-start hits from trace output", () => {
    const span: TraceSpan = {
      id: "span-kb",
      trace_id: "trace-1",
      otel_span_id: "otel-span-1",
      parent_span_id: null,
      traceparent: "00-trace-otel-01",
      kind: "tool",
      agent: "collector",
      subagent: "feature::Acme",
      name: "rag_kb_warm_start",
      status: "ok",
      model: null,
      provider: null,
      duration_ms: 12,
      input_chars: 10,
      output_chars: 10,
      input_tokens_estimate: 2,
      output_tokens_estimate: 2,
      cost_estimate_usd: 0,
      input_preview: "{}",
      output_preview: "",
      full_input: "{}",
      full_output: JSON.stringify({
        hit_count: 3,
        source_ids: ["raw-source-feature-1"],
        rejections: [
          {
            rank: 0,
            reason: "missing_text",
            document_id: "kb-doc-empty",
            chunk_id: "kb-chunk-empty",
            source_type: "webpage_verified",
          },
          {
            rank: 1,
            reason: "disallowed_source_type",
            document_id: "kb-doc-search",
            source_type: "web_search_result",
          },
        ],
      }),
      metadata: {
        hit_count: 3,
        source_count: 1,
        rejection_count: 2,
        top_rejection_reason: "missing_text",
      },
      created_at: "2026-05-31T00:00:00Z",
    };

    const summary = formatRagKbWarmStartSpan(span);

    expect(summary).toBe(
      "3 KB hits / 1 accepted / 2 rejected / rejections missing_text@0 kb-doc-empty webpage_verified; disallowed_source_type@1 kb-doc-search web_search_result",
    );
    expect(formatSpanMeta(span)).toContain(summary);
  });
});
