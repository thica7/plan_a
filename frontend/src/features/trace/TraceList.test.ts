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
});
