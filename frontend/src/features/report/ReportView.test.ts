import { describe, expect, it } from "vitest";
import type { RawSource } from "../../api/types";
import {
  collectSourceTokenGroups,
  extractSourceTokens,
  linkSourceTokens,
  resolveSourceId,
  sourceTypeLabel,
} from "./ReportView";

const source: RawSource = {
  id: "evidence-001",
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
      "Direct [source:evidence-001].",
      "Alias [source:S1].",
      "Missing [source:ghost].",
    ].join("\n");

    expect(linkSourceTokens(markdown, sourceMap, { S1: "evidence-001" })).toContain(
      "[[source:evidence-001]](#source-evidence-001)",
    );
    expect(linkSourceTokens(markdown, sourceMap, { S1: "evidence-001" })).toContain(
      "[[source:S1]](#source-evidence-001)",
    );
    expect(linkSourceTokens(markdown, sourceMap, { S1: "evidence-001" })).toContain(
      "[[source:ghost]](#missing-source-ghost)",
    );
  });

  it("groups repeated aliases and suffixed source tokens by resolved evidence id", () => {
    const groups = collectSourceTokenGroups(
      "Claim [source:S1] and quote [source:evidence-001#pricing] plus [source:ghost].",
      sourceMap,
      { S1: "evidence-001" },
    );

    const resolved = groups.find((group) => group.sourceId === "evidence-001");
    const missing = groups.find((group) => group.sourceId === "ghost");

    expect(resolved?.count).toBe(2);
    expect(resolved?.tokens).toEqual(["S1", "evidence-001#pricing"]);
    expect(resolved?.source?.title).toBe("Cursor pricing");
    expect(missing?.count).toBe(1);
    expect(missing?.source).toBeUndefined();
  });

  it("extracts and resolves normalized source ids", () => {
    expect(extractSourceTokens("A [source:evidence-001#quote] B [source:S1]")).toEqual([
      "evidence-001#quote",
      "S1",
    ]);
    expect(resolveSourceId("evidence-001#quote", sourceMap, {})).toBe("evidence-001");
    expect(resolveSourceId("S1", sourceMap, { S1: "evidence-001" })).toBe("evidence-001");
  });

  it("labels manual research source types as research evidence", () => {
    expect(sourceTypeLabel("manual_note")).toBe("research");
    expect(sourceTypeLabel("manual")).toBe("research");
    expect(sourceTypeLabel("manual_transcript")).toBe("research");
  });
});
