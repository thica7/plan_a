# Reference Resolver Contract

The project separates identity generation from reference resolution:

- `packages.identity` creates canonical IDs.
- `packages.sources` resolves and normalizes source/report citations.
- `packages.refs` resolves domain references such as competitors, dimensions,
  report versions, and quality finding keys.

## Source And Report Boundary

Reports may be drafted with raw collector tokens such as `[source:raw-source-*]`
or older aliases. Before a `ReportVersionRecord` is saved, the backend must call
`normalize_report_version_sources`.

That boundary does three things:

1. Resolve Evidence IDs, RawSource IDs, chunk suffixes, and aliases through
   `SourceResolutionIndex`.
2. Rewrite known source tokens in `report_md` to canonical `EvidenceRecord.id`
   tokens.
3. Ensure `ReportVersion.evidence_ids` contains every evidence item cited by
   the normalized report.

Frontend report views may still show RawSource-shaped cards for readability, but
they should treat backend source reconciliation metadata as the source of truth.

## Candidate And Evidence Boundary

Collector candidates are not evidence until they pass the evidence admission
gate:

1. `homepage_hints` may only contain verified homepages from a trusted resolver.
   Synthetic domains and LLM-provided hints are candidates, not verified
   homepages.
2. Real-mode URL evidence must be fetched successfully before it becomes a
   `RawSource` for analyst, writer, or report citations.
3. Failed fetches, search snippets, and unverified homepage-derived pages must be
   recorded as trace diagnostics such as `source_candidate_rejected`, not saved
   as report-scoped evidence.
4. `web_search_result` may remain useful for demo, diagnostics, and quality
   regression fixtures, but real-mode report claims should cite
   `webpage_verified` or explicit user-research/manual evidence types.

## Domain References

Use the dedicated resolver helpers instead of local string normalization:

- competitors: `CompetitorResolver`, `normalize_competitor_key`
- dimensions: `normalize_dimension_refs`, `normalize_dimension_ref`
- reports: `sort_report_versions`, `select_report_version`
- quality findings: `quality_finding_key`, `quality_entry_keys`
- audit relationship resources: `audit_relationship_resource_id`

Do not add new ad-hoc `lower()`, `casefold()`, `replace(" ", "_")`, or
`resource_id=f"{a}:{b}"` logic for cross-layer business references. Add a typed
resolver helper first, then call it from the boundary layer.

## Quality Matrix

The quality matrix remains the aggregation view for `BusinessQA`,
`ClaimValidator`, `EvidenceGap`, `RedTeam`, `BenchmarkAgent`, `ReleaseGate`, and
`MemoryAgent`. Each entry should include `metadata.quality_finding_keys` when it
contains blockers or warnings, so different agents can point to the same
underlying evidence/claim problem without inventing incompatible IDs.
