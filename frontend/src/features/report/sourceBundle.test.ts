import { describe, expect, it } from "vitest";
import type { EvidenceRecord } from "../../api/types";
import { buildReportSourceBundle } from "./sourceBundle";

describe("buildReportSourceBundle", () => {
  it("uses EvidenceRecord ids as canonical report source ids", () => {
    const bundle = buildReportSourceBundle([evidenceRecord()]);

    expect(bundle.sources).toHaveLength(1);
    expect(bundle.sources[0].id).toBe("evidence-001");
    expect(bundle.aliases["raw-pricing-001"]).toBe("evidence-001");
    expect(bundle.aliases["legacy-pricing"]).toBe("evidence-001");
  });

  it("filters to scoped report evidence ids", () => {
    const included = evidenceRecord();
    const excluded = evidenceRecord({
      id: "evidence-002",
      raw_source_id: "raw-feature-002",
      dimension: "feature",
    });

    const bundle = buildReportSourceBundle([included, excluded], {
      scopedEvidenceIds: ["evidence-001"],
    });

    expect(bundle.sources.map((source) => source.id)).toEqual(["evidence-001"]);
    expect(bundle.aliases["raw-feature-002"]).toBeUndefined();
  });
});

function evidenceRecord(overrides: Partial<EvidenceRecord> = {}): EvidenceRecord {
  return {
    id: "evidence-001",
    workspace_id: "workspace-1",
    project_id: "project-1",
    run_id: "run-1",
    raw_source_id: "raw-pricing-001",
    competitor_id: "competitor-cursor",
    dimension: "pricing",
    source_type: "webpage_verified",
    title: "Cursor pricing",
    url: "https://cursor.com/pricing",
    snippet: "Cursor pricing details.",
    content_hash: "hash-001",
    reliability_score: 0.92,
    freshness_score: 0.88,
    quality_label: "accepted",
    captured_at: "2026-06-04T00:00:00.000Z",
    metadata: { raw_source_aliases: ["legacy-pricing"] },
    ...overrides,
  };
}
