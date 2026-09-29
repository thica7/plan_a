import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useNewRunBuilder } from "./useNewRunBuilder";

const mocks = vi.hoisted(() => ({
  createRun: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("../../api/client", () => ({
  createRun: mocks.createRun,
  getRuntime: vi.fn().mockResolvedValue({
    default_execution_mode: "demo",
    demo_mode: true,
    auto_redo_warn_enabled: false,
    hitl_enabled: false,
    llm_provider: "mock",
    has_web_search_key: true,
  }),
  getWorkspaceQuotaDecision: vi.fn().mockResolvedValue({ allowed: true, reason: "" }),
  listScenarioPacks: vi.fn().mockResolvedValue([]),
  listSkills: vi.fn().mockResolvedValue([{ name: "pricing" }]),
}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      {children}
    </MemoryRouter>
  );
}

describe("useNewRunBuilder output language", () => {
  beforeEach(() => {
    mocks.navigate.mockReset();
    mocks.createRun.mockReset();
    mocks.createRun.mockResolvedValue({ id: "run-1" });
  });

  it("requires a target product before starting research", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.createRun).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/目标产品|product/i);
  });

  it("opens manual competitor input without unrelated AI names", () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    act(() => result.current.updateManualMode());
    expect(result.current.competitors).toBe("");
  });

  it("sends a general product profile with its own research focus", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("示例无线吸尘器");
      result.current.setTargetUrl("https://example.com/vacuum");
      result.current.setProductCategory("家用清洁电器");
      result.current.setProductAudience("小户型家庭");
      result.current.setProductUseCases("清理宠物毛发, 清洁地毯");
      result.current.setProductMarket("中国");
      result.current.setTopic("寻找同类和替代产品");
    });
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.createRun).toHaveBeenCalledWith(expect.objectContaining({
      topic: "寻找同类和替代产品",
      target_product: {
        name: "示例无线吸尘器", official_url: "https://example.com/vacuum",
        category: "家用清洁电器", audience: "小户型家庭",
        use_cases: ["清理宠物毛发", "清洁地毯"], market: "中国",
      },
    }));
  });

  it("defaults new runs to Chinese output", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => result.current.setTargetName("示例产品"));

    await act(async () => {
      await result.current.submitRun();
    });

    expect(mocks.createRun).toHaveBeenCalledWith(
      expect.objectContaining({ output_language: "zh-CN" }),
    );
  });

  it("submits explicit English output language", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));

    act(() => {
      result.current.setTargetName("示例产品");
      result.current.setOutputLanguage("en-US");
    });
    await act(async () => {
      await result.current.submitRun();
    });

    expect(mocks.createRun).toHaveBeenCalledWith(
      expect.objectContaining({ output_language: "en-US" }),
    );
  });

  it("keeps HITL disabled for real auto-discovery runs when only auto-redo is enabled", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));

    act(() => {
      result.current.setTargetName("示例产品");
      result.current.setExecutionMode("real");
      result.current.setCompetitorMode("auto");
      result.current.setAutoRedoWarn(true);
      result.current.setCollaborationMode("ai");
    });
    await act(async () => {
      await result.current.submitRun();
    });

    expect(mocks.createRun).toHaveBeenCalledWith(
      expect.objectContaining({
        auto_redo_warn_enabled: true,
        hitl_enabled: false,
      }),
    );
  });

  it("sends separate research depth, collaboration, and trimmed decision brief fields", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("示例产品");
      result.current.setResearchDepth("deep");
      result.current.setCollaborationMode("assisted");
      result.current.setDecisionQuestion("  应先改进什么？  ");
      result.current.setPrimaryJob("  完成清洁  ");
      result.current.setSuccessMetric("  完成率  ");
    });
    await act(async () => { await result.current.submitRun(); });

    expect(mocks.createRun).toHaveBeenCalledWith(expect.objectContaining({
      research_depth: "deep",
      collaboration_mode: "assisted",
      hitl_enabled: true,
      decision_brief: {
        decision_question: "应先改进什么？",
        primary_job: "完成清洁",
        success_metric: "完成率",
      },
    }));
  });

  it("defaults to standard AI research without human pauses", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => result.current.setTargetName("示例产品"));
    await act(async () => { await result.current.submitRun(); });

    expect(mocks.createRun).toHaveBeenCalledWith(expect.objectContaining({
      research_depth: "standard",
      collaboration_mode: "ai",
      hitl_enabled: false,
    }));
  });

  it("blocks manual scope when target plus competitors exceeds the depth slice limit", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("目标产品");
      result.current.setCompetitorMode("manual");
      result.current.setCompetitors("竞品甲,竞品乙");
      result.current.setSelected(["pricing", "feature", "market"]);
      result.current.setResearchDepth("quick");
    });
    await act(async () => { await result.current.submitRun(); });

    expect(mocks.createRun).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/9.*6|6.*9/);
  });

  it("counts repeated manual competitor names only once, as the backend does", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("目标产品");
      result.current.setCompetitorMode("manual");
      result.current.setCompetitors("竞品甲,竞品甲,竞品甲");
      result.current.setSelected(["pricing", "feature", "market"]);
      result.current.setResearchDepth("quick");
    });
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.createRun).toHaveBeenCalledWith(expect.objectContaining({ competitors: ["竞品甲"] }));
  });

  it("does not count the target twice when its competitor spelling differs by punctuation", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("Foo Bar");
      result.current.setCompetitorMode("manual");
      result.current.setCompetitors("Foo-Bar");
      result.current.setSelected(["pricing", "feature", "market", "persona"]);
      result.current.setResearchDepth("quick");
    });
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.createRun).toHaveBeenCalledTimes(1);
  });

  it("does not falsely block Straße and STRASSE in quick research", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("My App");
      result.current.setCompetitorMode("manual");
      result.current.setCompetitors("Straße,STRASSE");
      result.current.setSelected(["pricing", "feature", "market"]);
      result.current.setResearchDepth("quick");
    });
    await act(async () => { await result.current.submitRun(); });
    expect(result.current.manualScopeError).toBeNull();
    expect(mocks.createRun).toHaveBeenCalledWith(expect.objectContaining({ competitors: ["Straße"] }));
  });

  it("folds Greek final sigma and common ligatures for manual scope counting", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("My App");
      result.current.setCompetitorMode("manual");
      result.current.setCompetitors("ΟΣ,οσ,ﬃ,ffi");
      result.current.setSelected(["pricing", "feature"]);
      result.current.setResearchDepth("quick");
    });
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.createRun).toHaveBeenCalledWith(expect.objectContaining({ competitors: ["ΟΣ", "ﬃ"] }));
  });

  it("keeps distinct Chinese competitor names separate", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("目标产品");
      result.current.setCompetitorMode("manual");
      result.current.setCompetitors("竞品甲,竞品乙");
      result.current.setSelected(["pricing", "feature"]);
      result.current.setResearchDepth("quick");
    });
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.createRun).toHaveBeenCalledWith(expect.objectContaining({ competitors: ["竞品甲", "竞品乙"] }));
  });

  it("matches the target with casefolded competitor spelling", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime?.has_web_search_key).toBe(true));
    act(() => {
      result.current.setTargetName("STRASSE");
      result.current.setCompetitorMode("manual");
      result.current.setCompetitors("Straße");
      result.current.setSelected(["pricing", "feature", "market", "persona"]);
      result.current.setResearchDepth("quick");
    });
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.createRun).toHaveBeenCalledTimes(1);
  });
});
