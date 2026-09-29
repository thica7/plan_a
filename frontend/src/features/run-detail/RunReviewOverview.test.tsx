import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DecisionReplayReport, RunDetail, TraceSpan } from "../../api/types";
import { RunReviewOverview } from "./RunReviewOverview";

const recordedAt = "2026-09-29T12:00:00Z";
const span = {
  id: "span-1",
  agent: "collector",
  subagent: "feature::Acme",
  kind: "tool",
  name: "fetch_page",
  status: "ok",
  duration_ms: 12,
  created_at: recordedAt,
  metadata: {},
} as TraceSpan;

function runDetail(traceSpans: TraceSpan[]): RunDetail {
  return {
    id: "run-1",
    status: "completed",
    current_node: null,
    report_md: "Original report prose.",
    plan: { competitor_layer: "L1", scenario_id: null, qa_rule_ids: [], task_decomposition: [] },
    metrics: { verified_source_rate: 1, source_coverage_rate: 1, claim_citation_rate: 1, schema_pass_rate: 1 },
    raw_sources: [],
    qa_findings: [],
    reflections: [],
    agent_messages: [],
    trace_spans: traceSpans,
    comparison_matrix: null,
    enterprise_projection: null,
  } as unknown as RunDetail;
}

describe("RunReviewOverview timeline labels", () => {
  it.each(["replay", "span"])("shows translated composite dimensions for %s records and keeps product names intact", (source) => {
    const decisionReplay = source === "replay" ? {
      events: [{
        id: "event-1", event_type: "tool.called", agent: "collector", subagent: "feature::Acme",
        message: "Original system detail.", created_at: recordedAt,
      }],
    } as DecisionReplayReport : null;

    render(<RunReviewOverview
      decisionReplay={decisionReplay}
      detail={runDetail(source === "span" ? [span] : [])}
      events={[]}
      isRedoing={false}
      onRedo={vi.fn()}
      onViewChange={vi.fn()}
      qualityComparison={null}
      redoLimitReached={false}
      reflectionItems={[]}
      reportSources={{ aliases: {}, sources: [] }}
    />);

    expect(screen.getByText(/资料采集\/功能体验 \/ Acme/)).toBeInTheDocument();
    expect(screen.queryByText(/feature::Acme/)).not.toBeInTheDocument();
    if (source === "replay") expect(screen.getByText(/Original system detail\./)).toBeInTheDocument();
  });
});
