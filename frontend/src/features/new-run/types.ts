import type { CompetitorLayer } from "../../api/types";

export const defaultWorkspaceId = "default-workspace";
export const defaultCompetitors = "Perplexity, Claude, Gemini";
export const dynamicScenarioId = "dynamic_adaptive";

export type LayerSelection = "auto" | Extract<CompetitorLayer, "L1" | "L2" | "L3">;
export type CompetitorMode = "auto" | "manual";
export type ExecutionMode = "demo" | "real";
