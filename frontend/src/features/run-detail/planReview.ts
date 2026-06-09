export function normalizePlanDimension(value: string | undefined): string {
  if (!value) return "";
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function parsePlanDimensionsInput(value: string): string[] {
  const seen = new Set<string>();
  const dimensions: string[] = [];
  for (const item of value.split(",")) {
    const dimension = normalizePlanDimension(item);
    if (!dimension || seen.has(dimension)) continue;
    seen.add(dimension);
    dimensions.push(dimension);
  }
  return dimensions;
}

export function canApplyPlanDimensions(value: string, currentDimensions: string[]): boolean {
  const next = parsePlanDimensionsInput(value);
  if (next.length === 0) return false;
  const current = currentDimensions.map(normalizePlanDimension).filter(Boolean);
  if (next.length !== current.length) return true;
  return next.some((dimension, index) => dimension !== current[index]);
}

export type HitlReviewStage = "planner" | "qa";

export function hitlStageFromCurrentNode(currentNode: string | null | undefined): HitlReviewStage | null {
  if (currentNode === "planner_hitl") return "planner";
  if (currentNode === "qa_hitl") return "qa";
  return null;
}

export function fallbackHitlMessage(stage: HitlReviewStage): string {
  return stage === "planner" ? "Planner is ready for review." : "QA review is ready.";
}
