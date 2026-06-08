import type { CompetitorLayer, ScenarioPack } from "../../api/types";

export const coreDimensions = ["pricing", "feature", "persona"];
const maxRunDimensions = 8;

export interface StarterPreset {
  id: string;
  name: string;
  topic: string;
  competitorLayer: Extract<CompetitorLayer, "L1" | "L2" | "L3">;
  scenarioId: string;
  competitors: string[];
  dimensions: string[];
}

export const starterPresets: StarterPreset[] = [
  {
    id: "l1-ai-coding-battlecard",
    name: "L1 battlecard",
    topic: "AI coding assistant competitive battlecard",
    competitorLayer: "L1",
    scenarioId: "l1_pricing_pack",
    competitors: ["Cursor", "GitHub Copilot", "Windsurf"],
    dimensions: ["pricing", "feature", "persona", "security"],
  },
  {
    id: "l2-enterprise-workflow-risk",
    name: "L2 workflow risk",
    topic: "Enterprise AI search workflow and switching risk",
    competitorLayer: "L2",
    scenarioId: "l2_adjacent_workflow",
    competitors: ["Perplexity Enterprise", "Glean", "Microsoft Copilot"],
    dimensions: ["feature", "integrations", "security", "persona", "pricing"],
  },
  {
    id: "l3-market-landscape",
    name: "L3 landscape",
    topic: "Large language model application platform market landscape",
    competitorLayer: "L3",
    scenarioId: "l3_market_landscape",
    competitors: ["OpenAI", "Anthropic", "Google Gemini", "DeepSeek"],
    dimensions: ["market", "feature", "pricing", "benchmark", "persona"],
  },
];

export function lockedDimensionsForScenario(pack: ScenarioPack | null) {
  return pack?.required_dimensions.length ? pack.required_dimensions : coreDimensions;
}

export function isDimensionLocked(dimension: string, lockedDimensions: string[]) {
  return lockedDimensions.some((item) => item === dimension);
}

export function scenarioCompetitorPreset(pack: ScenarioPack | null) {
  return pack?.seed_competitors.map((item) => item.trim()).filter(Boolean).join(", ") ?? "";
}

export function starterPresetDimensions(preset: StarterPreset) {
  return mergeDimensions(preset.dimensions, [], []);
}

export function mergeDimensions(current: string[], required: string[], optional: string[]) {
  const merged: string[] = [];
  const seen = new Set<string>();
  for (const dimension of [...required, ...current, ...optional]) {
    const key = dimension.trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    merged.push(dimension);
    if (merged.length >= maxRunDimensions) break;
  }
  return merged;
}
