import { describe, expect, it } from "vitest";
import type { EvidenceRecord } from "../../api/types";
import { buildReportSourceBundle } from "./sourceBundle";

describe("buildReportSourceBundle", () => {
  it("uses RawSource ids as canonical report source ids", () => {
    const bundle = buildReportSourceBundle([evidenceRecord()]);

    expect(bundle.sources).toHaveLength(1);
    expect(bundle.sources[0].id).toBe("raw-pricing-001");
    expect(bundle.aliases["evidence-001"]).toBe("raw-pricing-001");
    expect(bundle.aliases["legacy-pricing"]).toBe("raw-pricing-001");
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

    expect(bundle.sources.map((source) => source.id)).toEqual(["raw-pricing-001"]);
    expect(bundle.aliases["raw-feature-002"]).toBeUndefined();
  });

  it("preserves KB collector provenance from enterprise evidence metadata", () => {
    const bundle = buildReportSourceBundle([
      evidenceRecord({
        raw_source_id: "evidence-kb-pricing-001",
        metadata: {
          kb_sync: true,
          kb_raw_source_id: "collector-raw-pricing-001",
          kb_collector_candidate_origin: "web_fetch",
          kb_collector_fetch_method: "browser_fetch",
          kb_collector_confidence: 0.91,
        },
      }),
    ]);

    expect(bundle.aliases["collector-raw-pricing-001"]).toBe("evidence-kb-pricing-001");
    expect(bundle.sources[0].candidate_origin).toBe("web_fetch");
    expect(bundle.sources[0].fetch_method).toBe("browser_fetch");
    expect(bundle.sources[0].candidate_confidence).toBe(0.91);
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
