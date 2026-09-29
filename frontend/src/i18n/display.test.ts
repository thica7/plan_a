import { describe, expect, it } from "vitest";
import { dimensionDescription, displayLabel, displayScope, runtimeDiagnostic } from "./display";

describe("display labels", () => {
  it.each([
    ["evidence_count", "证据数量", "Evidence count"],
    ["real_source_rate", "真实来源比例", "Real source rate"],
    ["report_structure_score", "报告结构得分", "Report structure score"],
    ["report_length_score", "报告长度得分", "Report length score"],
  ])("localizes the known quality metric %s", (key, chinese, english) => {
    expect(displayLabel(key, "zh-CN")).toBe(chinese);
    expect(displayLabel(key, "en-US")).toBe(english);
  });

  it.each([
    ["Evidence is ready for review.", "证据已就绪，请审核。"],
    ["QA review is ready.", "质检已就绪，请审核。"],
    ["Scoped redo started: collector.", "已开始定向重做：资料采集。"],
    ["Scoped redo started: analyst.", "已开始定向重做：资料分析。"],
    ["Scoped redo started: writer_only.", "已开始定向重做：仅重写报告。"],
    ["Scoped redo started: comparator.", "已开始定向重做：竞品比较。"],
    ["Scoped redo started: full.", "已开始定向重做：完整修订。"],
    ["Runtime command accepted HITL decision: accept.", "已接收人工审核决定：接受。"],
    ["Runtime command accepted HITL decision: modify_plan.", "已接收人工审核决定：修改计划。"],
    ["Runtime command accepted HITL decision: force_pass.", "已接收人工审核决定：人工通过。"],
    ["Runtime command accepted HITL decision: redo.", "已接收人工审核决定：重做。"],
  ])("localizes the stable system message %s", (message, chinese) => {
    expect(runtimeDiagnostic(message, "zh-CN")).toBe(chinese);
    expect(runtimeDiagnostic(message, "en-US")).toBe(message);
  });

  it("keeps unknown or embedded diagnostic text verbatim", () => {
    for (const message of [
      "Scoped redo started: custom_agent.",
      "Runtime command accepted HITL decision: custom_decision.",
      "User wrote: Scoped redo started: collector.",
      "Scoped redo started: collector. Additional user text.",
    ]) {
      expect(runtimeDiagnostic(message, "zh-CN")).toBe(message);
    }
  });

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
