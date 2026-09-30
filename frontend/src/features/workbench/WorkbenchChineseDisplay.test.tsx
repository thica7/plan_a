import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { CompetitorRecord, EvidenceRecord, ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { useI18n } from "../../stores/i18n";
import { CoverageHeatmap } from "./OverviewSummaryCards";
import { ReportReleasePanel } from "./ReportReleasePanel";
import { ReportVersionPanel } from "./ReportVersionPanel";

const version = {
  id: "report:version-1",
  workspace_id: "workspace-1",
  project_id: "project-1",
  run_id: "run-1",
  version_number: 1,
  topic_normalized: "Original research topic",
  competitor_layer: "L1",
  competitor_set_hash: "hash",
  status: "draft",
  report_md: "# Original report",
  core_report_md: "# Original report",
  support_appendix_md: "",
  audit_log_md: "",
  full_report_md: "# Original report",
  created_at: "2026-09-29T00:00:00Z",
  evidence_ids: [],
  claim_ids: [],
} satisfies ReportVersionRecord;

beforeEach(() => useI18n.getState().setLocale("zh-CN"));

it("shows Chinese coverage and draft labels while preserving report callback values", async () => {
  const onSelect = vi.fn();
  const onInspect = vi.fn();
  const user = userEvent.setup();
  render(<>
    <CoverageHeatmap
      competitors={[{ id: "competitor-1", name: "Original Product" } as CompetitorRecord]}
      evidence={[{ competitor_id: "competitor-1", dimension: "feature" } as EvidenceRecord]}
    />
    <ReportVersionPanel versions={[version]} selectedVersionId={null} setSelectedVersionId={onSelect} onSelectReport={onInspect} />
  </>);

  expect(screen.getByText("覆盖热图")).toBeInTheDocument();
  expect(screen.getByText("功能体验")).toBeInTheDocument();
  expect(screen.getByText("Original Product")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /草稿/ }));
  expect(onSelect).toHaveBeenCalledWith("report:version-1");
  expect(onInspect).toHaveBeenCalledWith(version);
  expect(version.status).toBe("draft");

  act(() => useI18n.getState().setLocale("en-US"));
  expect(screen.getByText("Coverage heatmap")).toBeInTheDocument();
  expect(screen.getByText("Draft")).toBeInTheDocument();
});

it("explains a blocked publish in its release context and keeps the action value", async () => {
  const user = userEvent.setup();
  const onReportAction = vi.fn();
  const gate = { status: "blocked", allowed: false, blocker_count: 1, warn_count: 0, readiness: { score: 62 } } as ReportReleaseGate;
  render(<ReportReleasePanel isPending={false} lastExport={null} onExport={vi.fn()} onReportAction={onReportAction} releaseGate={gate} selectedVersion={version} />);

  expect(screen.getByText("未满足发布条件")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /发布/ })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: /开始审核/ }));
  expect(onReportAction).toHaveBeenCalledWith("start_review");
  expect(gate.status).toBe("blocked");
});
