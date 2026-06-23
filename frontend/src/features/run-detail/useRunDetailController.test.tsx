import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRunStore } from "../../stores/run";
import type { RunDetail } from "../../api/types";
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
    claim_card_bundles: [],
    decision_card_bundle: null,
    section_briefs: [],
    report_artifact: null,
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

function makeReportArtifact() {
  return {
    artifact_version: 2,
    run_id: "run-1",
    core_report: { layer: "core", markdown: "## Core\n\nCore body.", sections: [] },
    support_appendix: { layer: "support", markdown: "## Evidence\n\nEvidence body.", sections: [] },
    audit_log: { layer: "audit", markdown: "## Audit\n\nAudit body.", sections: [] },
    claim_card_bundles: [],
    decision_card_bundle: null,
    section_briefs: [],
    quality: {
      core_gate: {},
      support_gate: {},
      audit_gate: {},
      warnings: [],
      blockers: [],
      revision_count: 0,
    },
    render_cache: {
      core_markdown: "## Core\n\nCore body.",
      support_markdown: "## Evidence\n\nEvidence body.",
      audit_markdown: "## Audit\n\nAudit body.",
      full_markdown: "## Core\n\nCore body.\n\n## Evidence\n\nEvidence body.\n\n## Audit\n\nAudit body.",
    },
    legacy: { source: "report_artifact_v2", report_md_alias: true },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
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

  it("applies report artifact updates from SSE events", async () => {
    const detail = makeDetail();
    const reportArtifact = makeReportArtifact();
    mocks.getRun.mockResolvedValue(detail);
    mocks.subscribeRun.mockImplementation((runId, onEvent) => {
      window.setTimeout(() => {
        onEvent({
          id: 2,
          run_id: runId,
          type: "report_updated",
          message: "Report updated.",
          payload: {
            report_md: "## Updated",
            report_artifact: reportArtifact,
          },
          created_at: "2026-06-10T00:00:02Z",
        });
      }, 0);
      return vi.fn();
    });

    const { result } = renderHook(() => useRunDetailController(), { wrapper });

    await waitFor(() => expect(result.current.detail?.report_md).toBe("## Updated"));
    expect(result.current.detail?.report_artifact).toBe(reportArtifact);
    expect(mocks.getRun).toHaveBeenCalledTimes(1);
  });

  it("clears an existing report artifact when SSE sends explicit null", async () => {
    const reportArtifact = makeReportArtifact();
    const detail = { ...makeDetail(), report_artifact: reportArtifact };
    mocks.getRun.mockResolvedValue(detail);
    mocks.subscribeRun.mockImplementation((runId, onEvent) => {
      window.setTimeout(() => {
        onEvent({
          id: 3,
          run_id: runId,
          type: "report_updated",
          message: "Report reverted to legacy markdown.",
          payload: {
            report_md: "## Legacy update",
            report_artifact: null,
          },
          created_at: "2026-06-10T00:00:02Z",
        });
      }, 0);
      return vi.fn();
    });

    const { result } = renderHook(() => useRunDetailController(), { wrapper });

    await waitFor(() => expect(result.current.detail?.report_md).toBe("## Legacy update"));
    expect(result.current.detail?.report_artifact).toBeNull();
  });

  it("preserves an existing report artifact in the store when SSE omits the artifact field", () => {
    const reportArtifact = makeReportArtifact();
    const detail = { ...makeDetail(), report_artifact: reportArtifact };
    useRunStore.getState().setDetail(detail as unknown as RunDetail);

    useRunStore.getState().addEvent({
      id: 4,
      run_id: "run-1",
      type: "report_updated",
      message: "Report markdown updated.",
      payload: {
        report_md: "## Artifact markdown update",
      },
      created_at: "2026-06-10T00:00:02Z",
    });

    expect(useRunStore.getState().detail?.report_md).toBe("## Artifact markdown update");
    expect(useRunStore.getState().detail?.report_artifact).toBe(reportArtifact);
  });

  it("clears report markdown when SSE sends an explicit empty string", async () => {
    const detail = { ...makeDetail(), report_md: "## Previous" };
    mocks.getRun.mockResolvedValue(detail);
    mocks.subscribeRun.mockImplementation((runId, onEvent) => {
      window.setTimeout(() => {
        onEvent({
          id: 5,
          run_id: runId,
          type: "report_updated",
          message: "Report cleared.",
          payload: {
            report_md: "",
            report_artifact: null,
          },
          created_at: "2026-06-10T00:00:02Z",
        });
      }, 0);
      return vi.fn();
    });

    const { result } = renderHook(() => useRunDetailController(), { wrapper });

    await waitFor(() => expect(result.current.detail?.report_md).toBe(""));
  });

  it("refetches detail when a report update omits the artifact field", async () => {
    const initial = makeDetail();
    const refreshed = {
      ...makeDetail(),
      report_md: "## Refetched artifact markdown",
      report_artifact: makeReportArtifact(),
    };
    mocks.getRun.mockResolvedValueOnce(initial).mockResolvedValueOnce(refreshed);
    mocks.subscribeRun.mockImplementation((runId, onEvent) => {
      window.setTimeout(() => {
        onEvent({
          id: 6,
          run_id: runId,
          type: "report_updated",
          message: "Report updated without artifact payload.",
          payload: {
            report_md: "## Streaming markdown",
          },
          created_at: "2026-06-10T00:00:02Z",
        });
      }, 0);
      return vi.fn();
    });

    const { result } = renderHook(() => useRunDetailController(), { wrapper });

    await waitFor(() => expect(mocks.getRun).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.detail?.report_artifact).toBe(refreshed.report_artifact));
    expect(result.current.detail?.report_md).toBe("## Refetched artifact markdown");
  });

  it("does not refetch again for later unrelated events after an omitted-artifact report update", async () => {
    const initial = makeDetail();
    const refreshed = {
      ...makeDetail(),
      report_md: "## Refetched artifact markdown",
      report_artifact: makeReportArtifact(),
    };
    mocks.getRun.mockResolvedValueOnce(initial).mockResolvedValue(refreshed);
    mocks.subscribeRun.mockImplementation((runId, onEvent) => {
      window.setTimeout(() => {
        onEvent({
          id: 7,
          run_id: runId,
          type: "report_updated",
          message: "Report updated without artifact payload.",
          payload: {
            report_md: "## Streaming markdown",
          },
          created_at: "2026-06-10T00:00:02Z",
        });
      }, 0);
      window.setTimeout(() => {
        onEvent({
          id: 8,
          run_id: runId,
          type: "tool.called",
          message: "Collector called a tool.",
          payload: { tool_name: "search" },
          created_at: "2026-06-10T00:00:03Z",
        });
      }, 20);
      return vi.fn();
    });

    const { result } = renderHook(() => useRunDetailController(), { wrapper });

    await waitFor(() => expect(result.current.events.some((event) => event.id === 8)).toBe(true));
    await new Promise((resolve) => window.setTimeout(resolve, 20));
    expect(mocks.getRun).toHaveBeenCalledTimes(2);
  });

  it("does not let an older omitted-artifact refetch overwrite a newer artifact SSE update", async () => {
    const initial = makeDetail();
    const newerArtifact = makeReportArtifact();
    const staleRefetch = {
      ...makeDetail(),
      report_md: "## Stale refetch",
      report_artifact: null,
    };
    const refetch = deferred<ReturnType<typeof makeDetail>>();
    mocks.getRun.mockResolvedValueOnce(initial).mockReturnValueOnce(refetch.promise);
    mocks.subscribeRun.mockImplementation((runId, onEvent) => {
      window.setTimeout(() => {
        onEvent({
          id: 9,
          run_id: runId,
          type: "report_updated",
          message: "Report updated without artifact payload.",
          payload: {
            report_md: "## Streaming markdown",
          },
          created_at: "2026-06-10T00:00:02Z",
        });
      }, 0);
      window.setTimeout(() => {
        onEvent({
          id: 10,
          run_id: runId,
          type: "report_updated",
          message: "Report artifact arrived over SSE.",
          payload: {
            report_md: "## New artifact markdown",
            report_artifact: newerArtifact,
          },
          created_at: "2026-06-10T00:00:03Z",
        });
      }, 10);
      return vi.fn();
    });

    const { result } = renderHook(() => useRunDetailController(), { wrapper });

    await waitFor(() => expect(result.current.detail?.report_artifact).toBe(newerArtifact));
    refetch.resolve(staleRefetch);
    await new Promise((resolve) => window.setTimeout(resolve, 0));

    expect(result.current.detail?.report_md).toBe("## New artifact markdown");
    expect(result.current.detail?.report_artifact).toBe(newerArtifact);
  });
});
