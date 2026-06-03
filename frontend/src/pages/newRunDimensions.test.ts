import { describe, expect, it } from "vitest";
import type { ScenarioPack } from "../api/types";
import {
  coreDimensions,
  isDimensionLocked,
  lockedDimensionsForScenario,
  mergeDimensions,
} from "./newRunDimensions";

describe("New Run dimension helpers", () => {
  it("locks the default schema dimensions when no scenario is selected", () => {
    const locked = lockedDimensionsForScenario(null);

    expect(locked).toEqual(coreDimensions);
    expect(isDimensionLocked("pricing", locked)).toBe(true);
    expect(isDimensionLocked("security", locked)).toBe(false);
  });

  it("locks the selected ScenarioPack required dimensions", () => {
    const l3Pack = scenarioPack({
      required_dimensions: ["feature", "persona", "market"],
      optional_dimensions: ["pricing", "integrations", "security"],
    });

    const locked = lockedDimensionsForScenario(l3Pack);

    expect(locked).toEqual(["feature", "persona", "market"]);
    expect(isDimensionLocked("market", locked)).toBe(true);
    expect(isDimensionLocked("pricing", locked)).toBe(false);
  });

  it("keeps required dimensions first and caps the run schema", () => {
    const merged = mergeDimensions(
      ["pricing", "feature", "persona", "market"],
      ["security", "integrations", "feature"],
      ["review", "benchmark", "latency", "sdk"],
    );

    expect(merged).toEqual([
      "security",
      "integrations",
      "feature",
      "pricing",
      "persona",
      "market",
      "review",
      "benchmark",
    ]);
  });
});

function scenarioPack(overrides: Partial<ScenarioPack>): ScenarioPack {
  return {
    id: "l3_market_landscape",
    name: "Market landscape",
    description: "Category-level landscape.",
    competitor_layer: "L3",
    required_dimensions: [],
    optional_dimensions: [],
    analyst_questions: [],
    evidence_requirements: [],
    qa_rule_ids: [],
    is_dynamic: false,
    ...overrides,
  };
}
