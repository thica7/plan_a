import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RawSource } from "../../api/types";
import type { SourceTokenGroup } from "./sourceTokens";
import { buildSourceAuditRows, isKbSource, ReportSourceTrace } from "./ReportSourceTrace";

const kbSource: RawSource = {
  id: "enterprise-evidence-pricing-001",
  competitor: "Cursor",
  covered_competitors: ["Cursor"],
  dimension: "pricing",
  source_type: "webpage_verified",
  title: "Cursor pricing",
  url: "https://cursor.com/pricing",
  snippet: "Cursor pricing details.",
  content_hash: "hash-001",
  confidence: 0.92,
  candidate_origin: "rag_kb",
  candidate_rank: null,
  candidate_confidence: 0.91,
  fetch_method: "enterprise_projection",
  quality_score: 0.92,
  failure_reason: null,
  metadata: {
    kb_sync: true,
    kb_document_status: "active",
    kb_document_version: 3,
    kb_raw_source_id: "collector-raw-pricing-001",
    kb_collector_run_id: "collector-run-1",
    kb_fetched_at: "2026-06-10T04:00:00.000Z",
    kb_last_seen_at: "2026-06-18T04:00:00.000Z",
    kb_freshness_score: 0.82,
  },
  extracted_at: "2026-06-18T04:00:00.000Z",
};

describe("ReportSourceTrace KB provenance", () => {
  it("builds compact audit rows for KB-reused evidence", () => {
    expect(isKbSource(kbSource)).toBe(true);
    expect(buildSourceAuditRows(kbSource)).toEqual([
      { label: "Origin", value: "KB reused" },
      { label: "Fetch", value: "enterprise_projection" },
      { label: "Candidate", value: "91%" },
      { label: "KB status", value: "active" },
      { label: "KB document", value: "v3" },
      { label: "KB raw source", value: "collector-raw-pricing-001" },
      { label: "Collector run", value: "collector-run-1" },
      { label: "Fetched", value: "2026-06-10" },
      { label: "Last seen", value: "2026-06-18" },
      { label: "Freshness", value: "82%" },
    ]);
  });

  it("renders KB audit metadata on source cards", () => {
    const groups: SourceTokenGroup[] = [
      {
        sourceId: kbSource.id,
        tokens: [kbSource.id, "collector-raw-pricing-001"],
        count: 2,
        source: kbSource,
      },
    ];

    render(
      <ReportSourceTrace
        activeSourceId={null}
        citationLabels={new Map([[kbSource.id, "S1"]])}
        citedSourceGroups={groups}
        citedSourceIds={new Set([kbSource.id])}
        missingSourceGroups={[]}
        onSourceJump={vi.fn()}
        sources={[kbSource]}
        totalCitationCount={2}
      />,
    );

    expect(screen.getAllByText(/KB reused/).length).toBeGreaterThan(0);
    expect(screen.getByText("KB document")).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.getByText("KB raw source")).toBeInTheDocument();
    expect(screen.getByText("collector-raw-pricing-001")).toBeInTheDocument();
    expect(screen.getByText("Collector run")).toBeInTheDocument();
    expect(screen.getByText("collector-run-1")).toBeInTheDocument();
    expect(screen.getByText("Freshness")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
  });
});