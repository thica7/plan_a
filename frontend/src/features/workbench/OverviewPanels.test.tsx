import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TraceSpan } from "../../api/types";
import { buildKbWarmStartSummary, TraceTimelinePanel } from "./OverviewPanels";

describe("OverviewPanels KB warm-start diagnostics", () => {
  it("aggregates accepted and rejected KB warm-start hits", () => {
    const summary = buildKbWarmStartSummary([
      traceSpan({
        full_output: JSON.stringify({
          rejections: [
            {
              rank: 0,
              reason: "missing_text",
              document_id: "kb-doc-empty",
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
        },
      }),
      traceSpan({
        id: "span-kb-2",
        full_output: "",
        metadata: {
          hit_count: 2,
          source_count: 0,
          rejection_count: 2,
          top_rejection_reason: "duplicate_source",
        },
      }),
    ]);

    expect(summary).toEqual({
      acceptedCount: 1,
      hitCount: 5,
      rejectedCount: 4,
      spanCount: 2,
      topRejections: [
        { count: 2, examples: [], reason: "duplicate_source" },
        { count: 1, examples: ["kb-doc-search"], reason: "disallowed_source_type" },
        { count: 1, examples: ["kb-doc-empty"], reason: "missing_text" },
      ],
    });
  });

  it("renders KB warm-start diagnostics in the trace timeline panel", () => {
    render(
      <TraceTimelinePanel
        auditLogs={[]}
        decisionReplay={null}
        evalOps={null}
        selectedVersion={null}
        traceSpans={[
          traceSpan({
            full_output: JSON.stringify({
              rejections: [
                {
                  rank: 0,
                  reason: "missing_text",
                  document_id: "kb-doc-empty",
                },
              ],
            }),
            metadata: {
              hit_count: 3,
              source_count: 1,
              rejection_count: 1,
            },
          }),
        ]}
      />,
    );

    expect(screen.getByLabelText("KB warm-start diagnostics")).toBeInTheDocument();
    expect(screen.getByText("KB hits")).toBeInTheDocument();
    expect(screen.getByText("Accepted")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("missing_text")).toBeInTheDocument();
    expect(screen.getByText("kb-doc-empty")).toBeInTheDocument();
  });
});

function traceSpan(overrides: Partial<TraceSpan> = {}): TraceSpan {
  return {
    id: "span-kb-1",
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
    full_output: JSON.stringify({ rejections: [] }),
    metadata: {},
    created_at: "2026-05-31T00:00:00Z",
    ...overrides,
  };
}
