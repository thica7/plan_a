import type { CollaborationMode, CompetitorLayer, ResearchDepth } from "../../api/types";

export const defaultWorkspaceId = "default-workspace";
export const dynamicScenarioId = "dynamic_adaptive";

export type LayerSelection = "auto" | Extract<CompetitorLayer, "L1" | "L2" | "L3">;
export type CompetitorMode = "auto" | "manual";
export type ExecutionMode = "demo" | "real";
export type OutputLanguage = "zh-CN" | "en-US";
export type { CollaborationMode, ResearchDepth };

export const depthBudgets = {
  quick: { competitors: 2, slices: 6, sources: 2, llmCalls: 60 },
  standard: { competitors: 5, slices: 12, sources: 3, llmCalls: 120 },
  deep: { competitors: 8, slices: 24, sources: 5, llmCalls: 160 },
} as const satisfies Record<ResearchDepth, {
  competitors: number; slices: number; sources: number; llmCalls: number;
}>;
