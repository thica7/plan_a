import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { RunDetail } from "../../api/types";
import { AgentHandoffSummary } from "./AgentHandoffSummary";

function detail() {
  return {
    id: "new-run", execution_mode: "real", reflections: [], trace_spans: [], report_md: "",
    plan: { competitor_layer: "L1", scenario_id: null, qa_rule_ids: [], task_decomposition: [] },
    comparison_matrix: null,
  } as unknown as RunDetail;
}

describe("历史报告线索", () => {
  it("显示必须重新核验和中文跳过原因，可展开原始链接与时间", async () => {
    const run = detail();
    run.plan.report_reuse_context = {
      selected: [{ report_id: "old-report", project_id: "old-project", reason: "related_product_scope", advisory_facts: ["旧断言不能展示为已验证"], advisory_only: true }],
      skipped: [{ report_id: "old-report", evidence_id: "old-evidence", reason: "expired" }],
      refresh_required: [{ report_id: "old-report", evidence_id: "old-evidence", competitor: "Cursor", dimension: "pricing",
        title: "原始价格页面", url: "https://cursor.com/pricing", captured_at: "2026-09-01T12:00:00",
        source_published_at: "2026-08-28", freshness: "stale", reason: "expired", requires_refresh: true }],
    };
    render(<AgentHandoffSummary detail={run} messages={[]} />);
    expect(screen.getByText("历史报告线索")).toBeInTheDocument();
    expect(screen.getByText(/1 条线索/)).toBeInTheDocument();
    expect(screen.getByText("必须重新抓取并核验后才能用于当前报告")).toBeInTheDocument();
    expect(screen.getByText("跳过: 事实已过期")).toBeInTheDocument();
    expect(screen.queryByText("旧断言不能展示为已验证")).not.toBeInTheDocument();
    expect(screen.queryByText(/expired/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("查看原始链接与时间"));
    expect(screen.getByRole("link", { name: "原始价格页面" })).toHaveAttribute("href", "https://cursor.com/pricing");
    expect(screen.getByText(/2026-09-01T12:00:00/)).toBeInTheDocument();
    expect(screen.getByText(/2026-08-28/)).toBeInTheDocument();
  });

  it("旧运行没有复用字段时继续正常展示", () => {
    render(<AgentHandoffSummary detail={detail()} messages={[]} />);
    expect(screen.getByText("代理交接")).toBeInTheDocument();
    expect(screen.queryByText("历史报告线索")).not.toBeInTheDocument();
  });
});
