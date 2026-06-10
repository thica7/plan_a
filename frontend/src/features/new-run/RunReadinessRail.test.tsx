import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import type { RuntimeConfig, WorkspaceQuotaDecision } from "../../api/types";
import { RunReadinessRail } from "./RunReadinessRail";

const runtime = {
  has_ark_api_key: true,
  has_ark_model: true,
  ark_model: "doubao",
  has_backup_llm_api_key: false,
  has_backup_llm_model: false,
  has_web_search_key: true,
  web_search_provider: "Search",
  temporal_cutover_ready: true,
  temporal_task_queue: "competiscope",
  compliance_redaction_enabled: true,
  pydantic_ai_model_backed_ready: true,
  pydantic_ai_model_name: "agent",
  auto_redo_enabled: true,
} as RuntimeConfig;

const quotaDecision = {
  allowed: true,
  reason: "ok",
} as WorkspaceQuotaDecision;

function renderRail(props: Partial<ComponentProps<typeof RunReadinessRail>> = {}) {
  return render(
    <form>
      <RunReadinessRail
        autoRedoWarn={false}
        competitorList={["Competitor A"]}
        competitorMode="manual"
        dynamicScenarioSelected={false}
        error={null}
        executionMode="real"
        hitlEnabled={false}
        isSubmitting={false}
        quotaDecision={quotaDecision}
        runBlockedByQuota={false}
        runtime={runtime}
        selected={["pricing"]}
        selectedLayer="L1"
        selectedScenario={null}
        setAutoRedoWarn={vi.fn()}
        toggleHitl={vi.fn()}
        {...props}
      />
    </form>,
  );
}

describe("RunReadinessRail", () => {
  it("submits only when required dimensions are selected", () => {
    renderRail({ selected: [] });

    expect(screen.getByRole("button", { name: /开始运行/i })).toBeDisabled();
    expect(screen.getByText("开始运行前至少选择一个分析维度")).toBeInTheDocument();
  });

  it("locks launch while submitting", () => {
    renderRail({ isSubmitting: true });

    const button = screen.getByRole("button", { name: /正在启动运行/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("data-action-state", "loading");
  });

  it("updates real HITL local state", async () => {
    const user = userEvent.setup();
    const toggleHitl = vi.fn();
    renderRail({ toggleHitl });

    await user.click(screen.getByRole("checkbox", { name: /human review pauses/i }));

    expect(toggleHitl).toHaveBeenCalledWith(true);
  });
});
