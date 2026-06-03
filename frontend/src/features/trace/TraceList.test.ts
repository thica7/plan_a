import { describe, expect, it } from "vitest";
import type { DecisionReplayEvent } from "../../api/types";
import { formatDecisionPayload } from "./TraceList";

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
});
