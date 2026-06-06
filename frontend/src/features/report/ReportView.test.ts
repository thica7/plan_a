import { describe, expect, it } from "vitest";
import type { RawSource } from "../../api/types";
import {
  buildCitationLabels,
  collectSourceTokenGroups,
  extractSourceTokens,
  linkSourceTokens,
  resolveSourceId,
  sourceTypeLabel,
} from "./ReportView";

const source: RawSource = {
  id: "raw-pricing-001",
  competitor: "Cursor",
  covered_competitors: ["Cursor"],
  dimension: "pricing",
  source_type: "webpage_verified",
  title: "Cursor pricing",
  url: "https://cursor.com/pricing",
  snippet: "Cursor pricing details.",
  content_hash: "hash-001",
  confidence: 0.92,
  extracted_at: "2026-06-03T00:00:00.000Z",
};

describe("ReportView source token parsing", () => {
  const sourceMap = new Map([[source.id, source]]);

  it("links direct, aliased, and missing source tokens to trace targets", () => {
    const markdown = [
      "Direct [source:raw-pricing-001].",
      "Alias [source:evidence-001].",
      "Missing [source:ghost].",
    ].join("\n");
    const labels = buildCitationLabels(
      collectSourceTokenGroups(markdown, sourceMap, { "evidence-001": "raw-pricing-001" }),
    );

    expect(linkSourceTokens(markdown, sourceMap, { "evidence-001": "raw-pricing-001" }, labels)).toContain(
      "[S1](#source-raw-pricing-001)",
    );
    expect(linkSourceTokens(markdown, sourceMap, { "evidence-001": "raw-pricing-001" }, labels)).toContain(
      "[S1](#source-raw-pricing-001)",
    );
    expect(linkSourceTokens(markdown, sourceMap, { "evidence-001": "raw-pricing-001" }, labels)).toContain(
      "[missing 1](#missing-source-ghost)",
    );
  });

  it("groups repeated aliases and suffixed source tokens by resolved raw source id", () => {
    const groups = collectSourceTokenGroups(
      "Claim [source:evidence-001] and quote [source:raw-pricing-001#pricing] plus [source:ghost].",
      sourceMap,
      { "evidence-001": "raw-pricing-001" },
    );

    const resolved = groups.find((group) => group.sourceId === "raw-pricing-001");
    const missing = groups.find((group) => group.sourceId === "ghost");

    expect(resolved?.count).toBe(2);
    expect(resolved?.tokens).toEqual(["evidence-001", "raw-pricing-001#pricing"]);
    expect(resolved?.source?.title).toBe("Cursor pricing");
    expect(missing?.count).toBe(1);
    expect(missing?.source).toBeUndefined();
    expect(buildCitationLabels(groups).get("raw-pricing-001")).toBe("S1");
    expect(buildCitationLabels(groups).get("ghost")).toBe("missing 1");
  });

  it("extracts and resolves normalized source ids", () => {
    expect(extractSourceTokens("A [source:raw-pricing-001#quote] B [source:evidence-001]")).toEqual([
      "raw-pricing-001#quote",
      "evidence-001",
    ]);
    expect(resolveSourceId("raw-pricing-001#quote", sourceMap, {})).toBe("raw-pricing-001");
    expect(resolveSourceId("evidence-001", sourceMap, { "evidence-001": "raw-pricing-001" })).toBe(
      "raw-pricing-001",
    );
  });

  it("labels manual research source types as research evidence", () => {
    expect(sourceTypeLabel("manual_note")).toBe("research");
    expect(sourceTypeLabel("manual")).toBe("research");
    expect(sourceTypeLabel("manual_transcript")).toBe("research");
  });
});
