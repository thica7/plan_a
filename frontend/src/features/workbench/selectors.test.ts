import { describe, expect, it } from "vitest";
import type { CompetitorRecord, EvidenceRecord, ReportVersionRecord } from "../../api/types";
import {
  buildCompetitorMap,
  buildEvidenceMap,
  buildWorkbenchReportSources,
  filterWorkbenchEvidence,
} from "./selectors";

describe("workbench selectors", () => {
  it("builds stable lookup maps for competitors and evidence", () => {
    const competitor = competitorRecord();
    const evidence = evidenceRecord();

    expect(buildCompetitorMap([competitor]).get("competitor-openai")?.name).toBe("OpenAI");
    expect(buildEvidenceMap([evidence]).get("evidence-pricing")?.raw_source_id).toBe("raw-source-pricing");
  });

  it("filters evidence by evidence fields and competitor display name", () => {
    const competitors = buildCompetitorMap([
      competitorRecord(),
      competitorRecord({ id: "competitor-anthropic", name: "Anthropic", normalized_name: "anthropic" }),
    ]);
    const pricing = evidenceRecord();
    const feature = evidenceRecord({
      competitor_id: "competitor-anthropic",
      dimension: "feature",
      id: "evidence-feature",
      raw_source_id: "raw-source-feature",
      snippet: "Claude supports enterprise admin controls.",
      source_type: "webpage_verified",
      title: "Claude enterprise features",
    });

    expect(filterWorkbenchEvidence([pricing, feature], competitors, "anthropic")).toEqual([feature]);
    expect(filterWorkbenchEvidence([pricing, feature], competitors, "pricing")).toEqual([pricing]);
    expect(filterWorkbenchEvidence([pricing, feature], competitors, "")).toEqual([pricing, feature]);
  });

  it("builds report sources using the active report version scope", () => {
    const competitors = buildCompetitorMap([competitorRecord()]);
    const included = evidenceRecord();
    const excluded = evidenceRecord({
      id: "evidence-feature",
      raw_source_id: "raw-source-feature",
      dimension: "feature",
    });

    const bundle = buildWorkbenchReportSources(
      [included, excluded],
      competitors,
      reportVersion({ evidence_ids: ["evidence-pricing"] }),
    );

    expect(bundle.sources.map((source) => source.id)).toEqual(["raw-source-pricing"]);
    expect(bundle.aliases["evidence-pricing"]).toBe("raw-source-pricing");
    expect(bundle.aliases["raw-source-feature"]).toBeUndefined();
  });
});

function competitorRecord(overrides: Partial<CompetitorRecord> = {}): CompetitorRecord {
  return {
    aliases: [],
    created_at: "2026-06-09T00:00:00.000Z",
    homepage_url: "https://openai.com",
    id: "competitor-openai",
    layer: "L1",
    metadata: {},
    name: "OpenAI",
    normalized_name: "openai",
    updated_at: "2026-06-09T00:00:00.000Z",
    workspace_id: "workspace-1",
    ...overrides,
  };
}

function evidenceRecord(overrides: Partial<EvidenceRecord> = {}): EvidenceRecord {
  return {
    captured_at: "2026-06-09T00:00:00.000Z",
    competitor_id: "competitor-openai",
    content_hash: "hash-pricing",
    dimension: "pricing",
    freshness_score: 0.9,
    id: "evidence-pricing",
    metadata: {},
    project_id: "project-1",
    quality_label: "accepted",
    raw_source_id: "raw-source-pricing",
    reliability_score: 0.92,
    run_id: "run-1",
    snippet: "OpenAI API pricing information.",
    source_type: "webpage_verified",
    title: "OpenAI pricing",
    url: "https://openai.com/pricing",
    workspace_id: "workspace-1",
    ...overrides,
  };
}

function reportVersion(overrides: Partial<ReportVersionRecord> = {}): ReportVersionRecord {
  return {
    claim_ids: [],
    competitor_layer: "L1",
    competitor_set_hash: "hash",
    created_at: "2026-06-09T00:00:00.000Z",
    evidence_ids: [],
    id: "report-version-1",
    parent_version_id: null,
    project_id: "project-1",
    published_at: null,
    quality_metadata: {},
    report_md: "# Report",
    run_id: "run-1",
    status: "draft",
    topic_normalized: "most powerful llm",
    version_number: 1,
    workspace_id: "workspace-1",
    ...overrides,
  };
}
