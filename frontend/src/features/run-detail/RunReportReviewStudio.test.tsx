import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { exportReportVersion, startReportApprovalWorkflow } from "../../api/client";
import type { RawSource, RunDetail } from "../../api/types";
import { useI18n } from "../../stores/i18n";
import { RunReportReviewStudio } from "./RunReportReviewStudio";
import { MemoryRouter, useLocation } from "react-router-dom";

vi.mock("../../api/client", () => ({
  exportReportVersion: vi.fn(),
  startReportApprovalWorkflow: vi.fn(),
}));

afterEach(() => {
  useI18n.getState().setLocale("zh-CN");
  vi.clearAllMocks();
});

const coreSource: RawSource = {
  id: "core-source",
  candidate_origin: "unknown",
  fetch_method: "unknown",
  quality_score: 0.9,
  metadata: {},
  competitor: "OpenAI",
  covered_competitors: ["OpenAI"],
  dimension: "pricing",
  source_type: "webpage_verified",
  title: "Core source",
  url: "https://example.com/core",
  snippet: "Core evidence.",
  content_hash: "hash-core",
  confidence: 0.9,
  extracted_at: "2026-06-10T00:00:00Z",
};

function makeDetail(): RunDetail {
  return {
    id: "run-1",
    idempotency_key: "key-1",
    workspace_id: "workspace-1",
    project_id: "project-1",
    topic: "AI",
    status: "completed",
    execution_mode: "real",
    output_language: "zh-CN",
    created_at: "2026-06-10T00:00:00Z",
    updated_at: "2026-06-10T00:00:01Z",
    plan: {
      topic: "AI",
      competitors: ["OpenAI"],
      dimensions: ["pricing"],
      complexity: "medium",
      competitor_layer: "L1",
      scenario_id: null,
      scenario_recommended_dimensions: [],
      qa_rule_ids: [],
      homepage_hints: {},
      task_decomposition: [],
      created_at: "2026-06-10T00:00:00Z",
    },
    max_iterations: 2,
    auto_redo_warn_enabled: false,
    hitl_enabled: false,
    report_md: "## Legacy Outline\n\nLegacy body [source:legacy-source].",
    claim_card_bundles: [],
    decision_card_bundle: null,
    section_briefs: [],
    report_artifact: {
      artifact_version: 2,
      run_id: "run-1",
      core_report: {
        layer: "core",
        markdown: "## Core Outline\n\nCore body [source:core-source].",
        sections: [],
      },
      support_appendix: {
        layer: "support",
        markdown: "## Evidence Outline\n\nEvidence body.",
        sections: [],
      },
      audit_log: {
        layer: "audit",
        markdown: "## Audit Outline\n\nAudit body.",
        sections: [],
      },
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
        core_markdown: "## Core Outline\n\nCore body [source:core-source].",
        support_markdown: "## Evidence Outline\n\nEvidence body.",
        audit_markdown: "## Audit Outline\n\nAudit body.",
        full_markdown:
          "## Core Outline\n\nCore body [source:core-source].\n\n## Evidence Outline\n\nEvidence body.\n\n## Audit Outline\n\nAudit body.",
      },
      legacy: { source: "report_artifact_v2", report_md_alias: true },
    },
    raw_sources: [coreSource],
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
      total_spans: 0,
      total_duration_ms: 0,
      llm_calls: 0,
      search_calls: 0,
      fetch_calls: 0,
      input_tokens_estimate: 0,
      output_tokens_estimate: 0,
      cost_estimate_usd: 0,
      source_coverage_rate: 1,
      verified_source_rate: 1,
      claim_citation_rate: 1,
      schema_pass_rate: 1,
      human_override_rate: 0,
      acceptance_rate: 1,
      qa_issue_count: 0,
      revision_count: 0,
      compliance_redaction_count: 0,
    },
    current_node: null,
    enterprise_projection: null,
  };
}

describe("RunReportReviewStudio artifact layers", () => {
  it('keeps outline and source jumps inside their report and preserves the run query', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const Path = () => { const l = useLocation(); return <output>{l.pathname + l.search + l.hash}</output>; };
    const { container } = render(<><MemoryRouter initialEntries={['/runs/a?view=report']}><RunReportReviewStudio detail={makeDetail()} reportSources={{ aliases: {}, sources: [coreSource] }} /></MemoryRouter><MemoryRouter initialEntries={['/runs/b?view=report']}><Path /><RunReportReviewStudio detail={makeDetail()} reportSources={{ aliases: {}, sources: [coreSource] }} /></MemoryRouter></>);
    const reports = container.querySelectorAll('.run-report-review-studio');
    const heading = reports[1].querySelector('[id="report-section-core-outline"]');
    expect(heading).not.toBeNull();
    await userEvent.click(within(reports[1] as HTMLElement).getByRole('button', { name: '目录与来源' }));
    await userEvent.click(within(reports[1] as HTMLElement).getByRole('link', { name: 'Core Outline' }));
    expect(scroll.mock.instances[scroll.mock.instances.length - 1]).toBe(reports[1].querySelector('[id="report-section-core-outline"]'));
    expect(screen.getByText('/runs/b?view=report#report-section-core-outline')).toBeInTheDocument();
    await userEvent.click(reports[1].querySelector('.source-token-link')!);
    expect(scroll.mock.instances[scroll.mock.instances.length - 1]).toBe(reports[1].querySelector('[id="source-core-source"]'));
    expect(screen.getByText('/runs/b?view=report#source-core-source')).toBeInTheDocument();
  });
  it('makes unavailable compare explicit and offers a real details toggle', async () => {
    render(<RunReportReviewStudio detail={makeDetail()} reportSources={{ aliases: {}, sources: [coreSource] }} />);
    expect(screen.getByRole('button', { name: '比较' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '比较' })).toHaveAttribute('title', '报告比较尚未开放');
    const toggle = screen.getByRole('button', { name: '目录与来源' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });
  it.each([
    { button: "MARKDOWN", chinese: "已导出 report.md", english: "Exported report.md" },
    { button: "请求审批", chinese: "审批流程 运行中: approval-1", english: "Approval workflow Running: approval-1" },
  ])("updates $button feedback when the UI language changes after completion", async ({ button, chinese, english }) => {
    vi.mocked(exportReportVersion).mockResolvedValue({ artifact: { filename: "report.md" } } as Awaited<ReturnType<typeof exportReportVersion>>);
    vi.mocked(startReportApprovalWorkflow).mockResolvedValue({ status: "running", workflow_id: "approval-1" } as unknown as Awaited<ReturnType<typeof startReportApprovalWorkflow>>);
    const detail = makeDetail();
    detail.enterprise_projection = {
      report_version: { id: "report-1", version_number: 1, status: "draft", claim_ids: [] },
    } as unknown as RunDetail["enterprise_projection"];
    render(<RunReportReviewStudio detail={detail} reportSources={{ aliases: {}, sources: [coreSource] }} />);

    await userEvent.setup().click(screen.getByRole("button", { name: button }));
    expect(await screen.findByText(chinese)).toBeInTheDocument();
    act(() => useI18n.getState().setLocale("en-US"));
    expect(screen.getByText(english)).toBeInTheDocument();
    expect(screen.queryByText(chinese)).not.toBeInTheDocument();
    if (button === "MARKDOWN") {
      expect(exportReportVersion).toHaveBeenCalledWith("report-1", "markdown");
    } else {
      expect(startReportApprovalWorkflow).toHaveBeenCalledWith({ report_version_id: "report-1", requested_by: "frontend-review-studio" });
    }
  });

  it.each([
    { button: "MARKDOWN", pendingChinese: "导出中... MARKDOWN", pendingEnglish: "Exporting... MARKDOWN", errorChinese: "无法导出报告", errorEnglish: "Unable to export report" },
    { button: "请求审批", pendingChinese: "正在启动审批流程...", pendingEnglish: "Starting approval workflow...", errorChinese: "无法请求审批", errorEnglish: "Unable to request approval" },
  ])("updates pending and fallback error feedback for $button when the UI language changes", async ({ button, pendingChinese, pendingEnglish, errorChinese, errorEnglish }) => {
    let rejectRequest!: (reason: unknown) => void;
    const request = new Promise<never>((_, reject) => { rejectRequest = reject; });
    if (button === "MARKDOWN") {
      vi.mocked(exportReportVersion).mockReturnValue(request);
    } else {
      vi.mocked(startReportApprovalWorkflow).mockReturnValue(request);
    }
    const detail = makeDetail();
    detail.enterprise_projection = {
      report_version: { id: "report-1", version_number: 1, status: "draft", claim_ids: [] },
    } as unknown as RunDetail["enterprise_projection"];
    render(<RunReportReviewStudio detail={detail} reportSources={{ aliases: {}, sources: [coreSource] }} />);

    await userEvent.setup().click(screen.getByRole("button", { name: button }));
    expect(screen.getByText(pendingChinese)).toBeInTheDocument();
    act(() => useI18n.getState().setLocale("en-US"));
    expect(screen.getByText(pendingEnglish)).toBeInTheDocument();
    expect(screen.queryByText(pendingChinese)).not.toBeInTheDocument();
    await act(async () => rejectRequest(null));
    expect(screen.getByText(errorEnglish)).toBeInTheDocument();
    act(() => useI18n.getState().setLocale("zh-CN"));
    expect(screen.getByText(errorChinese)).toBeInTheDocument();
    expect(screen.queryByText(errorEnglish)).not.toBeInTheDocument();
  });

  it("shows Chinese review labels and counts Chinese text by characters", () => {
    const detail = { ...makeDetail(), report_md: "中文报告", report_artifact: null };
    render(<RunReportReviewStudio detail={detail} reportSources={{ aliases: {}, sources: [coreSource] }} />);
    expect(screen.getByLabelText("报告审核状态")).toHaveTextContent("4 字符");
    expect(screen.getByText("审查操作")).toBeInTheDocument();
    expect(screen.getByText("中文报告")).toBeInTheDocument();
    expect(screen.getByText("Core evidence.")).toBeInTheDocument();
  });
  it("uses the selected artifact layer for the visible outline and source trace", async () => {
    render(
      <RunReportReviewStudio
        detail={makeDetail()}
        reportSources={{ aliases: {}, sources: [coreSource] }}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: '目录与来源' }));

    const outline = screen.getByRole("navigation", { name: /outline|大纲/i });
    expect(within(outline).getByText("Core Outline")).toBeInTheDocument();
    expect(within(outline).queryByText("Legacy Outline")).not.toBeInTheDocument();
    expect(screen.queryByText("legacy-source")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Evidence|\u8bc1\u636e/ }));

    expect(within(outline).getByText("Evidence Outline")).toBeInTheDocument();
    expect(within(outline).queryByText("Core Outline")).not.toBeInTheDocument();
  });
});
