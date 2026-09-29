import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EvidenceReviewModal } from "./EvidenceReviewModal";

const payload = {
  sources: [{
    id: "source-1", title: "官方产品页", competitor: "竞品甲", dimension: "pricing",
    url: "https://example.com/source", source_type: "webpage_verified", confidence: 0.82,
    fetched_at: "2026-09-28T10:00:00Z", extracted_at: "2026-09-28T10:01:00Z",
    source_published_at: "2026-09-20", source_updated_at: null,
  }, {
    id: "source-2", title: "不安全链接", competitor: "竞品乙", dimension: "feature",
    url: "javascript:alert(1)", source_type: "community", confidence: 0.4,
    fetched_at: null, extracted_at: "2026-09-28T10:01:00Z",
    source_published_at: null, source_updated_at: null,
  }],
  qa_findings: [{ id: "issue-1", severity: "warn", target_agent: "collector", problem: "来源日期不明" }],
  redo_remaining: 1,
};

describe("EvidenceReviewModal", () => {
  it("renders real evidence metadata and safe external links", () => {
    render(<EvidenceReviewModal message="请审核来源" payload={payload} activeDecision={null} isSubmitting={false} onDecision={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "证据审核" })).toBeInTheDocument();
    expect(screen.getByText("source-1")).toBeInTheDocument();
    expect(screen.getByText("竞品甲")).toBeInTheDocument();
    expect(screen.getByText("pricing")).toBeInTheDocument();
    expect(screen.getByText("webpage_verified")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText("2026-09-20")).toBeInTheDocument();
    expect(screen.getByText("https://example.com/source")).toBeInTheDocument();
    expect(screen.getByText("javascript:alert(1)")).toBeInTheDocument();
    expect(screen.getByText("来源日期不明")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "官方产品页" })).toHaveAttribute("href", "https://example.com/source");
    expect(screen.queryByRole("link", { name: "不安全链接" })).not.toBeInTheDocument();
  });

  it("passes the review note with accept or redo", async () => {
    const onDecision = vi.fn();
    render(<EvidenceReviewModal message="请审核来源" payload={payload} activeDecision={null} isSubmitting={false} onDecision={onDecision} />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "审核说明" }), "  请核对日期  ");
    await user.click(screen.getByRole("button", { name: "补采证据" }));
    await user.click(screen.getByRole("button", { name: "接受证据" }));
    expect(onDecision).toHaveBeenNthCalledWith(1, "redo", "请核对日期");
    expect(onDecision).toHaveBeenNthCalledWith(2, "accept", "请核对日期");
  });

  it("explains why redo is unavailable when its budget is exhausted", () => {
    render(<EvidenceReviewModal message="请审核来源" payload={{ ...payload, redo_remaining: 0 }} activeDecision={null} isSubmitting={false} onDecision={vi.fn()} />);
    expect(screen.getByRole("button", { name: "补采证据" })).toBeDisabled();
    expect(screen.getByText(/补采次数已用完/)).toBeInTheDocument();
  });

  it("shows truncation when the interrupt contains only a preview", () => {
    render(<EvidenceReviewModal message="请审核来源" payload={{
      ...payload, source_count: 120, sources_truncated: true,
      qa_issue_count: 60, qa_findings_truncated: true,
    }} activeDecision={null} isSubmitting={false} onDecision={vi.fn()} />);
    expect(screen.getByText(/仅展示 2 条来源.*共 120 条/)).toBeInTheDocument();
    expect(screen.getByText(/仅展示 1 条问题.*共 60 条/)).toBeInTheDocument();
  });

  it("does not allow approval until the persisted interrupt payload has loaded", () => {
    render(<EvidenceReviewModal message="请审核来源" payload={{}} activeDecision={null} isSubmitting={false} onDecision={vi.fn()} />);
    expect(screen.getByRole("button", { name: "接受证据" })).toBeDisabled();
    expect(screen.getByText(/审核数据尚未加载/)).toBeInTheDocument();
  });
});
