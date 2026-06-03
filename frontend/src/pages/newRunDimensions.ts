import type { ScenarioPack } from "../api/types";

export const coreDimensions = ["pricing", "feature", "persona"];
const maxRunDimensions = 8;

export function lockedDimensionsForScenario(pack: ScenarioPack | null) {
  return pack?.required_dimensions.length ? pack.required_dimensions : coreDimensions;
}

export function isDimensionLocked(dimension: string, lockedDimensions: string[]) {
  return lockedDimensions.some((item) => item === dimension);
}

export function scenarioCompetitorPreset(pack: ScenarioPack | null) {
  return pack?.seed_competitors.map((item) => item.trim()).filter(Boolean).join(", ") ?? "";
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
