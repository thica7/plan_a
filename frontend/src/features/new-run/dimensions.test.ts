import { describe, expect, it } from "vitest";
import type { ScenarioPack } from "../../api/types";
import {
  coreDimensions,
  isDimensionLocked,
  lockedDimensionsForScenario,
  mergeDimensions,
  scenarioCompetitorPreset,
  starterPresetDimensions,
  starterPresets,
} from "./dimensions";

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

  it("formats ScenarioPack seed competitors for the manual competitor field", () => {
    const pack = scenarioPack({
      seed_competitors: ["Cursor", " GitHub Copilot ", "", "Windsurf"],
    });

    expect(scenarioCompetitorPreset(pack)).toBe("Cursor, GitHub Copilot, Windsurf");
    expect(scenarioCompetitorPreset(null)).toBe("");
  });

  it("ships one-click starter presets for L1, L2, and L3 demos", () => {
    expect(starterPresets.map((preset) => preset.competitorLayer)).toEqual([
      "L1",
      "L2",
      "L3",
    ]);
    expect(starterPresets.map((preset) => preset.scenarioId)).toEqual([
      "l1_pricing_pack",
      "l2_adjacent_workflow",
      "l3_market_landscape",
    ]);
    for (const preset of starterPresets) {
      expect(preset.competitors.length).toBeGreaterThanOrEqual(3);
      expect(preset.dimensions.length).toBeGreaterThanOrEqual(4);
      expect(starterPresetDimensions(preset)).toEqual(preset.dimensions);
    }
  });

  it("resets preset dimensions instead of carrying stale manual selections", () => {
    const preset = starterPresets[0];
    const staleSelection = ["market", "benchmark", "integrations"];

    expect(starterPresetDimensions(preset)).not.toEqual(
      mergeDimensions(preset.dimensions, [], staleSelection),
    );
    expect(starterPresetDimensions(preset)).toEqual([
      "pricing",
      "feature",
      "persona",
      "security",
    ]);
  });
});

function scenarioPack(overrides: Partial<ScenarioPack>): ScenarioPack {
  return {
    id: "l3_market_landscape",
    name: "Market landscape",
    description: "Category-level landscape.",
    competitor_layer: "L3",
    seed_competitors: [],
    required_dimensions: [],
    optional_dimensions: [],
    analyst_questions: [],
    evidence_requirements: [],
    qa_rule_ids: [],
    is_dynamic: false,
    ...overrides,
  };
}
