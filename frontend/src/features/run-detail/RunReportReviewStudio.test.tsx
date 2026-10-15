import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createManualReportRevision, downloadArtifact, getRun, listProjectReportVersions, exportReportVersion, startReportApprovalWorkflow } from "../../api/client";
import type { RawSource, RunDetail } from "../../api/types";
import { useI18n } from "../../stores/i18n";
import { RunReportReviewStudio } from "./RunReportReviewStudio";
import { RunDetail as RunDetailPage } from "../../pages/RunDetail";
import { getRunStore } from "../../stores/run";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";

vi.mock("../../api/client", () => ({
  getRun: vi.fn(),
  listRuns: vi.fn().mockResolvedValue([]),
  getDecisionReplay: vi.fn().mockResolvedValue(null),
  getRunComplianceReport: vi.fn().mockResolvedValue(null),
  getRunQualityComparison: vi.fn().mockResolvedValue(null),
  getTraceSpans: vi.fn().mockResolvedValue([]),
  getAgentMessages: vi.fn().mockResolvedValue([]),
  getToolCallMessages: vi.fn().mockResolvedValue([]),
  createManualReportRevision: vi.fn(),
  downloadArtifact: vi.fn(),
  listProjectReportVersions: vi.fn().mockResolvedValue([]),
  exportReportVersion: vi.fn(),
  startReportApprovalWorkflow: vi.fn(),
}));

afterEach(() => {
  useI18n.getState().setLocale("zh-CN");
  vi.clearAllMocks();
  vi.unstubAllGlobals();
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
    vi.mocked(downloadArtifact).mockResolvedValue(new Blob(["report"]));
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:report"), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
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
    expect(screen.getAllByText("Core evidence.").length).toBeGreaterThanOrEqual(1);
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


let versionFixtureSequence = 0;
function versionDetail() {
  const detail = makeDetail();
  detail.workspace_id = `workspace-fixture-${++versionFixtureSequence}`;
  detail.enterprise_projection = {
    workspace_id: detail.workspace_id, project_id: detail.project_id, run_id: detail.id,
    evidence_records: [], claim_records: [],
    report_version: { id: 'version-1', run_id: detail.id, project_id: detail.project_id, version_number: 1, status: 'approved', report_md: detail.report_md, report_artifact: detail.report_artifact, claim_ids: ['old-claim'], quality_metadata: { release_gate: { allowed: true }, report_claims: { supported: 1 } } },
  } as unknown as NonNullable<RunDetail['enterprise_projection']>;
  return detail;
}

describe('manual revision user loop', () => {
  it('saves a new draft and shows its body and new QA without old artifact or green quality', async () => {
    const detail = versionDetail();
    vi.mocked(createManualReportRevision).mockResolvedValue({ ...detail.enterprise_projection!.report_version,
      id: 'version-2', parent_version_id: 'version-1', version_number: 2, status: 'draft',
      report_md: 'New body in US.', report_artifact: null, claim_ids: ['new-claim'],
      quality_metadata: { manual_semantic_review: { status: 'pending_review' }, run_qa_findings: [{ id: 'new-qa', severity: 'blocker', problem: '新增地区缺少原文证据' }], release_gate: { allowed: false, status: 'blocked' } },
    });
    render(<RunReportReviewStudio detail={detail} reportSources={{ sources: [coreSource], aliases: {} }} />);
    await userEvent.click(screen.getByRole('button', { name: '编辑正文' }));
    const editor = screen.getByRole('textbox', { name: '报告正文' });
    await userEvent.clear(editor); await userEvent.type(editor, 'New body in US.');
    await userEvent.click(screen.getByRole('button', { name: '保存草稿并重验' }));
    expect(createManualReportRevision).toHaveBeenCalledWith('version-1', { report_md: 'New body in US.' });
    expect(await screen.findByText('New body in US.')).toBeInTheDocument();
    expect(screen.getByText('新增地区缺少原文证据')).toBeInTheDocument();
    expect(screen.getByText('事实改写待复核')).toBeInTheDocument();
    expect(screen.getByText(/父版本：\s*version-1/)).toBeInTheDocument();
    expect(screen.queryByText(/Core body/)).not.toBeInTheDocument();
    expect(screen.queryByText('100/100')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '请求审批' })).toBeDisabled();
  });

  it('ignores a save finishing for another run', async () => {
    const detail = versionDetail();
    let finish!: (v: any) => void;
    vi.mocked(createManualReportRevision).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const { rerender } = render(<RunReportReviewStudio detail={detail} reportSources={{ sources: [], aliases: {} }} />);
    await userEvent.click(screen.getByRole('button', { name: '编辑正文' }));
    await userEvent.type(screen.getByRole('textbox', { name: '报告正文' }), ' unsaved');
    await userEvent.click(screen.getByRole('button', { name: '保存草稿并重验' }));
    rerender(<RunReportReviewStudio detail={{ ...makeDetail(), id: 'run-other', report_md: 'Other run', report_artifact: null }} reportSources={{ sources: [], aliases: {} }} />);
    await act(async () => finish({ ...detail.enterprise_projection!.report_version, id: 'late-version', report_md: 'Late old run' }));
    expect(screen.getByText('Other run')).toBeInTheDocument();
    expect(screen.queryByText('Late old run')).not.toBeInTheDocument();
  });

  it('downloads exported bytes and revokes the object URL, and never reports failed downloads as success', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const createObjectURL = vi.fn(() => 'blob:report'); const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL }));
    vi.mocked(exportReportVersion).mockResolvedValue({ artifact: { id: 'artifact-1', filename: '竞品报告.md' } } as any);
    vi.mocked(downloadArtifact).mockResolvedValueOnce(new Blob(['正文'])).mockRejectedValueOnce(new Error('下载权限不足'));
    render(<RunReportReviewStudio detail={versionDetail()} reportSources={{ sources: [], aliases: {} }} />);
    await userEvent.click(screen.getByRole('button', { name: 'MARKDOWN' }));
    expect(await screen.findByText('已导出 竞品报告.md')).toBeInTheDocument();
    expect(downloadArtifact).toHaveBeenCalledWith('artifact-1');
    expect(click.mock.instances[click.mock.instances.length - 1]).toHaveProperty('download', '竞品报告.md');
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:report');
    await userEvent.click(screen.getByRole('button', { name: 'HTML' }));
    expect(await screen.findByText(/下载权限不足/)).toBeInTheDocument();
    expect(screen.queryByText('已导出 竞品报告.md')).not.toBeInTheDocument();
    click.mockRestore();
  });
});

it('protects unsaved edits when switching versions and restores them after returning', async () => {
  const detail = versionDetail();
  const oldVersion = { ...detail.enterprise_projection!.report_version, id: 'version-0', version_number: 0, report_md: 'Older body', report_artifact: null };
  vi.mocked(listProjectReportVersions).mockResolvedValueOnce([oldVersion]);
  vi.stubGlobal('confirm', vi.fn(() => false));
  render(<RunReportReviewStudio detail={detail} reportSources={{ sources: [], aliases: {} }} />);
  await screen.findByRole('option', { name: /v0/ });
  await userEvent.click(screen.getByRole('button', { name: '编辑正文' }));
  const editor = screen.getByRole('textbox', { name: '报告正文' });
  await userEvent.type(editor, ' preserved');
  const select = screen.getByLabelText('报告版本');
  await userEvent.selectOptions(select, 'version-0');
  expect(select).toHaveValue('version-1');
  expect((editor as HTMLTextAreaElement).value).toContain('preserved');
  vi.stubGlobal('confirm', vi.fn(() => true));
  await userEvent.selectOptions(select, 'version-0');
  expect(screen.getByText('Older body')).toBeInTheDocument();
  await userEvent.selectOptions(select, 'version-1');
  expect((screen.getByRole('textbox', { name: '报告正文' }) as HTMLTextAreaElement).value).toContain('preserved');
});

it('shows checked only as a claim check and translates current manual QA into Chinese', () => {
  const detail = versionDetail();
  detail.enterprise_projection!.report_version = { ...detail.enterprise_projection!.report_version, report_artifact: null,
    quality_metadata: { manual_semantic_review: { status: 'checked' }, release_gate: { allowed: false },
      run_qa_findings: [{ id: 'qa', problem: 'Current manual claim has no scoped source citation.', severity: 'blocker', metadata: { line_number: 4, claim_text: 'Phone costs $499 in US.' } }] } };
  render(<RunReportReviewStudio detail={detail} reportSources={{ sources: [], aliases: {} }} />);
  expect(screen.getByText('本轮保守主张检查已完成；发布仍以门禁结果为准。')).toBeInTheDocument();
  expect(screen.getByText('该主张缺少当前项目可用的来源引用，请补充引用后重验。')).toBeInTheDocument();
  expect(screen.getByText(/第4行/)).toHaveTextContent('Phone costs $499 in US.');
  expect(screen.getByRole('button', { name: '请求审批' })).toBeDisabled();
  expect(screen.queryByText('100/100')).not.toBeInTheDocument();
});


it('restores an unsaved draft after actual RunDetail navigation unloads the studio for an uncached run', async () => {
  const a = versionDetail();
  const b = { ...versionDetail(), id: 'uncached-run-b' };
  b.enterprise_projection = { ...b.enterprise_projection!, run_id: b.id, report_version: { ...b.enterprise_projection!.report_version, id: 'version-b', run_id: b.id, report_md: '运行乙正文', report_artifact: null } };
  getRunStore(a.id).getState().reset(); getRunStore(b.id).getState().reset();
  let finishB!: (value: RunDetail) => void;
  vi.mocked(getRun).mockImplementation(id => id === a.id ? Promise.resolve(a) : new Promise(resolve => { finishB = resolve; }));
  let navigate!: ReturnType<typeof useNavigate>;
  function Host() { navigate = useNavigate(); return <Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes>; }
  render(<MemoryRouter initialEntries={['/runs/run-1?view=report']}><Host /></MemoryRouter>);
  await screen.findByRole('button', { name: '编辑正文' });
  fireEvent.click(screen.getByRole('button', { name: '编辑正文' }));
  fireEvent.change(screen.getByRole('textbox', { name: '报告正文' }), { target: { value: '未保存的跨运行草稿' } });
  act(() => navigate('/runs/uncached-run-b?view=report'));
  await waitFor(() => expect(finishB).toBeDefined());
  expect(screen.queryByRole('textbox', { name: '报告正文' })).not.toBeInTheDocument();
  await act(async () => finishB(b));
  await screen.findByText('运行乙正文');
  act(() => navigate('/runs/run-1?view=report'));
  await waitFor(() => {
    const editor = screen.queryByRole('textbox', { name: '报告正文' });
    if (!editor) fireEvent.click(screen.getByRole('button', { name: '编辑正文' }));
    expect(screen.getByRole('textbox', { name: '报告正文' })).toHaveValue('未保存的跨运行草稿');
  });
  expect(screen.getByText('正文有未保存修改；切换后会在本页保留编辑。')).toBeInTheDocument();
  expect(createManualReportRevision).not.toHaveBeenCalled();
});

it('keeps retained drafts within their server workspace, run and version and removes a saved draft', async () => {
  const detail = versionDetail();
  const sources = { sources: [], aliases: {} };
  const first = render(<RunReportReviewStudio detail={detail} reportSources={sources} />);
  fireEvent.click(screen.getByRole('button', { name: '编辑正文' }));
  fireEvent.change(screen.getByRole('textbox', { name: '报告正文' }), { target: { value: '仅原作用域未保存' } });
  first.unmount();
  for (const other of [
    { ...detail, workspace_id: 'different-server-workspace' },
    { ...detail, id: 'different-run' },
    { ...detail, enterprise_projection: { ...detail.enterprise_projection!, report_version: { ...detail.enterprise_projection!.report_version, id: 'different-version' } } },
  ]) {
    const view = render(<RunReportReviewStudio detail={other} reportSources={sources} />);
    expect(screen.queryByRole('textbox', { name: '报告正文' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '编辑正文' }));
    expect(screen.getByRole('textbox', { name: '报告正文' })).toHaveValue(detail.report_md);
    view.unmount();
  }
  const restored = render(<RunReportReviewStudio detail={detail} reportSources={sources} />);
  expect(screen.getByRole('textbox', { name: '报告正文' })).toHaveValue('仅原作用域未保存');
  vi.mocked(createManualReportRevision).mockResolvedValue({ ...detail.enterprise_projection!.report_version, id: 'saved-version', status: 'draft', parent_version_id: 'version-1', report_md: '仅原作用域未保存', report_artifact: null });
  fireEvent.click(screen.getByRole('button', { name: '保存草稿并重验' }));
  await screen.findByText('已保存为新草稿并完成本轮重验。');
  restored.unmount();
  render(<RunReportReviewStudio detail={detail} reportSources={sources} />);
  expect(screen.queryByRole('textbox', { name: '报告正文' })).not.toBeInTheDocument();
  expect(screen.queryByText('正文有未保存修改；切换后会在本页保留编辑。')).not.toBeInTheDocument();
});
