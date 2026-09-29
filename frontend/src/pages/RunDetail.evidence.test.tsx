import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RunDetail } from "./RunDetail";

const mocks = vi.hoisted(() => ({ controller: vi.fn(), handleHitl: vi.fn() }));
vi.mock("../features/run-detail/useRunDetailController", () => ({ useRunDetailController: mocks.controller }));
vi.mock("../features/run-detail/RunDetailHeader", () => ({ RunDetailHeader: () => null }));
vi.mock("../features/run-detail/RunSummaryStrip", () => ({ RunSummaryStrip: () => null }));
vi.mock("../features/run-detail/RunDetailTabs", () => ({ RunDetailTabs: () => null }));
vi.mock("../features/run-detail/RunDetailContent", () => ({ RunDetailContent: () => null }));

describe("RunDetail evidence entry", () => {
  beforeEach(() => {
    mocks.handleHitl.mockReset();
    mocks.controller.mockReturnValue({
      detail: { status: "interrupted" }, error: null, activeView: "overview",
      latestInterrupt: { message: "请审核来源", payload: { stage: "evidence", sources: [], qa_findings: [], redo_remaining: 0 } },
      interruptStage: "evidence", activeHitlDecision: null, isHitlSubmitting: false, isRedoing: false,
      handleHitl: mocks.handleHitl,
    });
  });

  it("opens evidence review from the persisted interrupt stage", async () => {
    render(<RunDetail />);
    expect(screen.getByRole("heading", { name: "证据审核" })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "接受证据" }));
    expect(mocks.handleHitl).toHaveBeenCalledWith("accept", "");
  });
});
