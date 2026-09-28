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
      result.current.toggleHitl(false);
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
});
