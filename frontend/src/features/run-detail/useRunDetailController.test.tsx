import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRunStore } from "../../stores/run";
import { useRunDetailController } from "./useRunDetailController";

const mocks = vi.hoisted(() => ({
  getRun: vi.fn(),
  getRunQualityComparison: vi.fn(),
  getDecisionReplay: vi.fn(),
  getRunComplianceReport: vi.fn(),
  listRuns: vi.fn(),
  redoRun: vi.fn(),
  resumeRun: vi.fn(),
  subscribeRun: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  exportRunComplianceReport: vi.fn(),
  getDecisionReplay: mocks.getDecisionReplay,
  getRun: mocks.getRun,
  getRunComplianceReport: mocks.getRunComplianceReport,
  getRunQualityComparison: mocks.getRunQualityComparison,
  listRuns: mocks.listRuns,
  redoRun: mocks.redoRun,
  resumeRun: mocks.resumeRun,
  subscribeRun: mocks.subscribeRun,
}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter
      initialEntries={["/runs/run-1"]}
      future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
    >
      <Routes>
        <Route path="/runs/:runId" element={children} />
      </Routes>
    </MemoryRouter>
  );
}

function makeDetail() {
  return {
    id: "run-1",
    idempotency_key: "key-1",
    workspace_id: "default-workspace",
    project_id: "project-1",
    topic: "AI",
    status: "interrupted",
    execution_mode: "real",
    output_language: "zh-CN",
    created_at: "2026-06-10T00:00:00Z",
    updated_at: "2026-06-10T00:00:01Z",
    plan: {
      topic: "AI",
      competitors: ["OpenAI", "Anthropic"],
      dimensions: ["pricing"],
      complexity: "medium",
      competitor_layer: "L1",
      scenario_id: "l1_pricing_pack",
      scenario_recommended_dimensions: ["pricing"],
      qa_rule_ids: [],
      memory_candidate_ids: [],
      memory_prompt_context: [],
      memory_recall_score: 0,
      homepage_hints: {},
      homepage_verified: {},
      task_decomposition: [],
      created_at: "2026-06-10T00:00:00Z",
    },
    max_iterations: 2,
    auto_redo_warn_enabled: false,
    hitl_enabled: true,
    report_md: "",
    raw_sources: [],
    competitor_kbs: {},
    competitor_knowledge: {},
    competitor_discovery: null,
    comparison_matrix: null,
    qa_findings: [],
    reflections: [],
    revisions: [],
    agent_messages: [],
    tool_call_messages: [],
    trace_spans: [],
    metrics: {
      source_coverage_rate: 1,
      verified_source_rate: 1,
      claim_citation_rate: 1,
      schema_pass_rate: 1,
    },
    current_node: "qa_hitl",
    enterprise_projection: null,
  };
}

describe("useRunDetailController background refresh", () => {
  beforeEach(() => {
    useRunStore.getState().reset();
    mocks.getRun.mockReset();
    mocks.getRunQualityComparison.mockReset();
    mocks.getDecisionReplay.mockReset();
    mocks.getRunComplianceReport.mockReset();
    mocks.listRuns.mockReset();
    mocks.redoRun.mockReset();
    mocks.resumeRun.mockReset();
    mocks.subscribeRun.mockReset();

    mocks.getRunQualityComparison.mockResolvedValue(null);
    mocks.getDecisionReplay.mockResolvedValue(null);
    mocks.getRunComplianceReport.mockResolvedValue(null);
    mocks.listRuns.mockResolvedValue([]);
    mocks.subscribeRun.mockImplementation((runId, onEvent) => {
      window.setTimeout(() => {
        onEvent({
          id: 1,
          run_id: runId,
          type: "interrupt",
          message: "QA findings are ready for review.",
          payload: { stage: "qa", interrupt_node: "qa_hitl" },
          created_at: "2026-06-10T00:00:02Z",
        });
      }, 0);
      return vi.fn();
    });
  });

  it("keeps the loaded detail when an event-triggered refresh fails", async () => {
    const detail = makeDetail();
    mocks.getRun.mockResolvedValueOnce(detail).mockRejectedValueOnce(new Error("Failed to fetch"));

    const { result } = renderHook(() => useRunDetailController(), { wrapper });

    await waitFor(() => expect(result.current.detail?.id).toBe("run-1"));
    await waitFor(() => expect(mocks.getRun).toHaveBeenCalledTimes(2));

    expect(result.current.detail?.id).toBe("run-1");
    expect(result.current.error).toBeNull();
  });
});
