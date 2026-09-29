import { describe, expect, it } from "vitest";
import { dimensionDescription, displayLabel, displayScope, runtimeDiagnostic } from "./display";

describe("display labels", () => {
  it("translates only the enum portion of a dimension and product scope", () => {
    expect(displayScope("pricing::GitHub Copilot", "zh-CN")).toBe("价格与成本 / GitHub Copilot");
    expect(displayScope("feature::pricing", "zh-CN")).toBe("功能体验 / pricing");
  });
  it("localizes known enums without altering unknown product names or source text", () => {
    expect(displayLabel("feature", "zh-CN")).toBe("功能体验");
    expect(displayLabel("draft", "zh-CN")).toBe("草稿");
    expect(displayLabel("real", "zh-CN")).toBe("真实数据");
    expect(displayLabel("collector", "zh-CN")).toBe("资料采集");
    expect(displayLabel("feature", "en-US")).toBe("Feature experience");
    expect(displayLabel("Cursor", "zh-CN")).toBe("Cursor");
    expect(displayLabel("This is source evidence.", "zh-CN")).toBe("This is source evidence.");
  });

  it("uses Chinese dimension guidance and preserves the original English description", () => {
    expect(dimensionDescription("feature", "Original feature description", "zh-CN")).toBe("核心功能、产品体验与使用能力");
    expect(dimensionDescription("feature", "Original feature description", "en-US")).toBe("Original feature description");
    expect(dimensionDescription("custom_dimension", "User-defined scope", "zh-CN")).toBe("User-defined scope");
    expect(dimensionDescription("constructor", "Custom source text", "zh-CN")).toBe("Custom source text");
  });

  it("localizes known runtime diagnostics and leaves unrecognized diagnostics intact", () => {
    const diagnostic = "Set PYDANTIC_AI_MODEL_BACKED_ENABLED=true to use model-backed quality agents.";
    expect(runtimeDiagnostic(diagnostic, "zh-CN")).toBe("尚未启用模型质量代理。");
    expect(runtimeDiagnostic(diagnostic, "en-US")).toBe(diagnostic);
    expect(runtimeDiagnostic("Unexpected provider failure: ABC", "zh-CN")).toBe("Unexpected provider failure: ABC");
    expect(runtimeDiagnostic("constructor", "zh-CN")).toBe("constructor");
  });
});
