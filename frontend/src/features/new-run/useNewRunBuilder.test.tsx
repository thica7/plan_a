import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useNewRunBuilder } from "./useNewRunBuilder";

const mocks = vi.hoisted(() => ({
  createRun: vi.fn(),
  getRuntime: vi.fn(),
  getQuota: vi.fn(),
  navigate: vi.fn(),
  location: { search: "" },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
    useLocation: () => mocks.location,
  };
});

vi.mock("../../api/client", () => ({
  createRun: mocks.createRun,
  getRuntime: mocks.getRuntime.mockResolvedValue({
    default_execution_mode: "demo",
    demo_mode: true,
    auto_redo_warn_enabled: false,
    hitl_enabled: false,
    llm_provider: "mock",
    has_web_search_key: true,
  }),
  getWorkspaceQuotaDecision: mocks.getQuota.mockResolvedValue({ allowed: true, reason: "" }),
  listScenarioPacks: vi.fn().mockResolvedValue([]),
  listSkills: vi.fn().mockResolvedValue([{ name: "pricing" }]),
}));

beforeEach(() => {
  mocks.location.search = "";
  localStorage.removeItem("competiscope.workspaceId");
});

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


describe("durable submission routing and replay", () => {
  beforeEach(() => {
    mocks.navigate.mockReset();
    mocks.createRun.mockReset().mockResolvedValue({ id: "legacy" });
    mocks.getRuntime.mockResolvedValue({ task_center_enabled: true, default_execution_mode: "demo", has_web_search_key: false });
    mocks.getQuota.mockResolvedValue({ allowed: true });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "submission-1" }), { status: 202 })));
  });

  async function builder() {
    const hook = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(hook.result.current.runtime).not.toBeNull());
    act(() => hook.result.current.setTargetName("示例产品"));
    return hook;
  }

  it("uses durable submission in demo without search credentials", async () => {
    const { result } = await builder();
    await act(async () => { await result.current.submitRun(); });
    expect(fetch).toHaveBeenCalledWith("/api/task-submissions", expect.objectContaining({ method: "POST", credentials: "same-origin" }));
    expect(mocks.createRun).not.toHaveBeenCalled();
    expect(mocks.navigate).toHaveBeenCalledWith("/submissions/submission-1?workspace_id=default-workspace");
  });

  it.each([false, undefined])("keeps the legacy path for flag %s", async flag => {
    mocks.getRuntime.mockResolvedValue({ task_center_enabled: flag, default_execution_mode: "demo", has_web_search_key: true });
    const { result } = await builder();
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.createRun).toHaveBeenCalledTimes(1);
    expect(fetch).not.toHaveBeenCalled();
    expect(mocks.navigate).toHaveBeenCalledWith("/runs/legacy");
  });

  it("does not fall back after an uncertain result and replays the same normalized intent at zero old quota", async () => {
    mocks.getQuota.mockResolvedValue({ allowed: false, reason: "quota denied" });
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = await builder();
    await act(async () => { await result.current.submitRun(); });
    act(() => result.current.setTargetName("  示例产品  "));
    await act(async () => { await result.current.submitRun(); });
    expect(fetch).toHaveBeenCalledTimes(2);
    const bodies = vi.mocked(fetch).mock.calls.map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies[0].idempotency_key).toBe(bodies[1].idempotency_key);
    expect(bodies[0].request.idempotency_key).toBe(bodies[0].idempotency_key);
    expect(mocks.createRun).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/连接|刷新|重试/);
    expect(result.current.error).not.toContain("Failed to fetch");
    act(() => result.current.setTargetName("新的产品"));
    await act(async () => { await result.current.submitRun(); });
    const changed = JSON.parse(String(vi.mocked(fetch).mock.calls[2][1]?.body));
    expect(changed.idempotency_key).not.toBe(bodies[0].idempotency_key);
  });

  it("keeps the successful intent key when navigation has not completed and suppresses rapid double submit", async () => {
    let resolve!: (r: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const { result } = await builder();
    let pending!: Promise<void>;
    act(() => { pending = result.current.submitRun(); void result.current.submitRun(); });
    expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { resolve(new Response(JSON.stringify({ id: "submission-1" }), { status: 202 })); await pending; });
    await act(async () => { await result.current.submitRun(); });
    const calls = vi.mocked(fetch).mock.calls;
    expect(JSON.parse(String(calls[0][1]?.body)).idempotency_key).toBe(JSON.parse(String(calls[1][1]?.body)).idempotency_key);
  });

  it("still blocks automatic discovery in real mode without search", async () => {
    const { result } = await builder();
    act(() => result.current.setExecutionMode("real"));
    await act(async () => { await result.current.submitRun(); });
    expect(fetch).not.toHaveBeenCalled();
    expect(mocks.createRun).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/搜索/);
  });
});

it('does not choose a delivery route before runtime capability is known or after its request fails', async () => {
  mocks.createRun.mockClear();
  mocks.getQuota.mockResolvedValue({ allowed: true });
  let rejectRuntime!: (e: Error) => void;
  mocks.getRuntime.mockImplementationOnce(() => new Promise((_, reject) => { rejectRuntime = reject; }));
  const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
  act(() => result.current.setTargetName('能力未知的产品'));
  await act(async () => { await result.current.submitRun(); });
  expect(mocks.createRun).not.toHaveBeenCalled();
  await act(async () => { rejectRuntime(new Error('<html>offline</html>')); });
  await act(async () => { await result.current.submitRun(); });
  expect(mocks.createRun).not.toHaveBeenCalled();
  expect(result.current.error).toMatch(/配置|连接|刷新/);
  expect(result.current.error).not.toContain('<html>');
});


describe("workspace continuity", () => {
  beforeEach(() => {
    mocks.navigate.mockReset();
    mocks.createRun.mockReset().mockResolvedValue({ id: "legacy" });
    mocks.getQuota.mockClear().mockResolvedValue({ allowed: true });
    mocks.getRuntime.mockResolvedValue({ task_center_enabled: true, default_execution_mode: "demo", has_web_search_key: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation((_path, init) => Promise.resolve(new Response(JSON.stringify({
      id: "scoped-submission", workspace_id: JSON.parse(String(init?.body)).request.workspace_id,
    }), { status: 202 }))));
  });

  it.each([
    { search: "?workspace_id=url-space", identity: "identity-space", expected: "url-space" },
    { search: "", identity: "identity-space", expected: "identity-space" },
    { search: "", identity: "", expected: "default-workspace" },
  ])("uses $expected for quota, payload and detail navigation", async ({ search, identity, expected }) => {
    mocks.location.search = search;
    if (identity) localStorage.setItem("competiscope.workspaceId", identity);
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime).not.toBeNull());
    act(() => result.current.setTargetName("工作空间测试产品"));
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.getQuota).toHaveBeenCalledWith(expected);
    const body = JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body));
    expect(body.request.workspace_id).toBe(expected);
    expect(mocks.navigate).toHaveBeenCalledWith(`/submissions/scoped-submission?workspace_id=${expected}`);
  });

  it("uses the confirmed submission workspace for successful detail navigation", async () => {
    mocks.location.search = "?workspace_id=request-space";
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ id: "scoped-submission", workspace_id: "confirmed-space" }), { status: 202 }));
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime).not.toBeNull());
    act(() => result.current.setTargetName("服务确认空间"));
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.navigate).toHaveBeenCalledWith('/submissions/scoped-submission?workspace_id=confirmed-space');
  });

  it("changes intent keys and quota scope when workspace changes without remounting the form", async () => {
    mocks.location.search = "?workspace_id=space-a";
    vi.mocked(fetch).mockRejectedValue(new TypeError("unknown outcome"));
    const { result, rerender } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime).not.toBeNull());
    act(() => result.current.setTargetName("相同研究问题"));
    await act(async () => { await result.current.submitRun(); });
    mocks.location.search = "?workspace_id=space-b";
    rerender();
    await waitFor(() => expect(mocks.getQuota).toHaveBeenCalledWith("space-b"));
    await act(async () => { await result.current.submitRun(); });
    const requests = vi.mocked(fetch).mock.calls.map(([, init]) => JSON.parse(String(init?.body)));
    expect(requests[0].request.workspace_id).toBe("space-a");
    expect(requests[1].request.workspace_id).toBe("space-b");
    expect(requests[1].idempotency_key).not.toBe(requests[0].idempotency_key);
  });

  it("keeps the legacy delivery path while respecting its explicit workspace", async () => {
    mocks.location.search = "?workspace_id=legacy-space";
    mocks.getRuntime.mockResolvedValue({ task_center_enabled: false, default_execution_mode: "demo", has_web_search_key: false });
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });
    await waitFor(() => expect(result.current.runtime).not.toBeNull());
    act(() => result.current.setTargetName("旧路径研究问题"));
    await act(async () => { await result.current.submitRun(); });
    expect(mocks.getQuota).toHaveBeenCalledWith("legacy-space");
    expect(mocks.createRun).toHaveBeenCalledWith(expect.objectContaining({ workspace_id: "legacy-space" }));
    expect(mocks.navigate).toHaveBeenCalledWith("/runs/legacy");
    expect(fetch).not.toHaveBeenCalled();
  });
});
