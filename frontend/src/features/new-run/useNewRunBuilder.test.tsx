import { act, renderHook } from "@testing-library/react";
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

  it("defaults new runs to Chinese output", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });

    await act(async () => {
      await result.current.submitRun();
    });

    expect(mocks.createRun).toHaveBeenCalledWith(
      expect.objectContaining({ output_language: "zh-CN" }),
    );
  });

  it("submits explicit English output language", async () => {
    const { result } = renderHook(() => useNewRunBuilder(), { wrapper });

    act(() => {
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

    act(() => {
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
