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
    kb_document_id: "kb-doc-pricing-v3",
    kb_document_status: "active",
    kb_document_version: 3,
    kb_chunk_id: "kb-chunk-pricing-7",
    kb_retrieval_query: "Cursor pricing AI coding assistant comparison pricing model and seat limits",
    kb_hit_score: 0.87,
    kb_rerank_score: 0.93,
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
      { label: "KB document", value: "kb-doc-pricing-v3" },
      { label: "KB version", value: "v3" },
      { label: "KB chunk", value: "kb-chunk-pricing-7" },
      {
        label: "KB query",
        value: "Cursor pricing AI coding assistant comparison pricing model and seat limits",
      },
      { label: "KB hit", value: "87%" },
      { label: "KB rerank", value: "93%" },
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
    expect(screen.getByText("kb-doc-pricing-v3")).toBeInTheDocument();
    expect(screen.getByText("KB version")).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.getByText("KB chunk")).toBeInTheDocument();
    expect(screen.getByText("kb-chunk-pricing-7")).toBeInTheDocument();
    expect(screen.getByText("KB query")).toBeInTheDocument();
    expect(screen.getByText(/AI coding assistant comparison/)).toBeInTheDocument();
    expect(screen.getByText("KB hit")).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
    expect(screen.getByText("KB rerank")).toBeInTheDocument();
    expect(screen.getByText("93%")).toBeInTheDocument();
    expect(screen.getByText("KB raw source")).toBeInTheDocument();
    expect(screen.getByText("collector-raw-pricing-001")).toBeInTheDocument();
    expect(screen.getByText("Collector run")).toBeInTheDocument();
    expect(screen.getByText("collector-run-1")).toBeInTheDocument();
    expect(screen.getByText("Freshness")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
  });

  it("summarizes KB sync chunk lists when no single retrieval chunk exists", () => {
    expect(
      buildSourceAuditRows({
        ...kbSource,
        metadata: {
          kb_sync: true,
          kb_document_id: "kb-doc-enterprise",
          kb_chunk_ids: ["chunk-1", "chunk-2", "chunk-3", "chunk-4"],
        },
      }),
    ).toEqual([
      { label: "Origin", value: "KB reused" },
      { label: "Fetch", value: "enterprise_projection" },
      { label: "Candidate", value: "91%" },
      { label: "KB document", value: "kb-doc-enterprise" },
      { label: "KB chunks", value: "chunk-1, chunk-2, chunk-3 +1" },
    ]);
  });
});
