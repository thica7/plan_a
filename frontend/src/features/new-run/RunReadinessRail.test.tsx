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
        collaborationMode="ai"
        dynamicScenarioSelected={false}
        error={null}
        executionMode="real"
        manualScopeError={null}
        isSubmitting={false}
        quotaDecision={quotaDecision}
        runBlockedByQuota={false}
        runtime={runtime}
        targetName="示例产品"
        selected={["pricing"]}
        selectedLayer="L1"
        researchDepth="standard"
        selectedScenario={null}
        setAutoRedoWarn={vi.fn()}
        {...props}
      />
    </form>,
  );
}

describe("RunReadinessRail", () => {
  it("requires web search for automatic competitor discovery", () => {
    renderRail({ competitorMode: "auto", runtime: { ...runtime, has_web_search_key: false } });
    expect(screen.getByRole("button", { name: /开始运行/i })).toBeDisabled();
    expect(screen.getByText(/搜索服务/)).toBeInTheDocument();
  });
  it("disables launch until the target product is named", () => {
    renderRail({ targetName: "" });
    expect(screen.getByRole("button", { name: /开始运行/i })).toBeDisabled();
    expect(screen.getByText(/目标产品/)).toBeInTheDocument();
  });
  it("does not display fabricated dollar estimates", () => {
    renderRail();
    expect(screen.getByText("研究视角")).toBeInTheDocument();
    expect(screen.queryByText("~$48.60")).not.toBeInTheDocument();
  });
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

  it("shows one collaboration selection and keeps AI auto redo unavailable in assisted mode", async () => {
    const setAutoRedoWarn = vi.fn();
    renderRail({ collaborationMode: "assisted", setAutoRedoWarn });
    expect(screen.queryByRole("checkbox", { name: /human review pauses|人工审核暂停/i })).not.toBeInTheDocument();
    const autoRedo = screen.getByRole("checkbox", { name: /自动重做警告|auto-redo warnings/i });
    expect(autoRedo).toBeDisabled();
    await userEvent.setup().click(autoRedo);
    expect(setAutoRedoWarn).not.toHaveBeenCalled();
  });

  it("never shows AI auto redo as selected during assisted review", () => {
    renderRail({ collaborationMode: "assisted", autoRedoWarn: true });
    expect(screen.getByRole("checkbox", { name: /自动重做警告|auto-redo warnings/i })).not.toBeChecked();
  });

  it("blocks a manual scope that exceeds its slice budget before submit", () => {
    renderRail({ manualScopeError: "请求 9 个切片，当前档位最多 6 个切片。" });
    expect(screen.getByRole("button", { name: /开始运行/i })).toBeDisabled();
    expect(screen.getByText(/请求 9 个切片/)).toBeInTheDocument();
  });
});
