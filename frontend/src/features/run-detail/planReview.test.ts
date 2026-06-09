import { describe, expect, it } from "vitest";
import {
  canApplyPlanDimensions,
  fallbackHitlMessage,
  hitlStageFromCurrentNode,
  normalizePlanDimension,
  parsePlanDimensionsInput,
} from "./planReview";

describe("plan review dimension helpers", () => {
  it("normalizes reviewer dimension input with the backend key shape", () => {
    expect(normalizePlanDimension(" Market Landscape ")).toBe("market_landscape");
    expect(parsePlanDimensionsInput("Pricing, feature, pricing, buyer persona")).toEqual([
      "pricing",
      "feature",
      "buyer_persona",
    ]);
  });

  it("only enables apply when reviewer dimensions actually change", () => {
    const current = ["pricing", "feature", "persona"];

    expect(canApplyPlanDimensions(" pricing, feature, persona ", current)).toBe(false);
    expect(canApplyPlanDimensions("pricing, feature, persona, review", current)).toBe(true);
    expect(canApplyPlanDimensions("feature, pricing, persona", current)).toBe(true);
    expect(canApplyPlanDimensions("", current)).toBe(false);
  });

  it("restores the visible HITL review stage from persisted current_node", () => {
    expect(hitlStageFromCurrentNode("planner_hitl")).toBe("planner");
    expect(hitlStageFromCurrentNode("qa_hitl")).toBe("qa");
    expect(hitlStageFromCurrentNode("writer")).toBeNull();
    expect(fallbackHitlMessage("planner")).toBe("Planner is ready for review.");
    expect(fallbackHitlMessage("qa")).toBe("QA review is ready.");
  });
});
