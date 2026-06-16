# Writer Evidence Pack and Segmented Writer Design

## Context

Recent expanded-report work increased report depth, source collection breadth, community triangulation, and the writer target length. That improved evidence richness, but `run-58dd1b8df825ffcba52fbdd1433b5956` exposed a new failure mode: the initial writer call exceeded the 600 second timeout before any report was saved.

The run did not fail because of QA or collector coverage. It collected 82 raw sources, passed collect QA and analyst QA, completed comparator and reflector, then failed inside the initial writer call. Reconstructing the writer input showed:

- `Writer Context JSON`: about 512k characters.
- Source digest portion: about 428k characters.
- Grounding prompt: about 20k characters.
- Largest single source digest: about 63k characters for one OpenAI pricing source.

The largest source was not huge because its snippet was huge. It was huge because it had 65 normalized pricing fields and each field repeated a long pricing quote. Existing compaction removes noisy keys and limits individual field values, but it does not aggregate repeated normalized fields or enforce an overall writer input budget.

## Problem

The current writer input path mixes three responsibilities:

1. A complete source audit trail.
2. A source-level digest for writing.
3. A facts-and-claims package for report synthesis.

That worked while reports and source sets were smaller. It now causes the writer prompt to receive too much repeated raw evidence at once. The system previously avoided truncation to prevent thin reports, so tests intentionally require all raw sources and all KB slices to be exposed. That prevents source loss, but it also prevents the writer from scaling when source count and normalized fields grow.

The root problem is not that the project has too much information. The root problem is that repeated source text is being passed to the writer as if it were distinct writing context.

## Goals

- Preserve information richness and auditability.
- Keep every accepted raw source represented in writer-visible data.
- Prevent repeated quotes, repeated normalized fields, and noisy source metadata from dominating the writer prompt.
- Make writer input size observable in run events and traces.
- Route large evidence sets through segmented writing instead of one monolithic writer call.
- Avoid reintroducing writer fallback reports. If writer generation fails, the system should fail with a precise reason or preserve an existing report only in repair flows that already have one.

## Non-Goals

- Do not reduce collector breadth.
- Do not remove community evidence, survey evidence, interview evidence, or official source evidence.
- Do not hard-cap by dropping sources from the writer-visible package.
- Do not return to short reports.
- Do not change the release gate policy as part of this work.

## Design Summary

Introduce a `WriterEvidencePack` between `RunDetail` and the writer prompt.

The pack is not a subset of sources. It is a structured full-coverage projection of all accepted sources:

- `source_registry` lists every accepted raw source once.
- `groups` organize evidence by competitor and dimension.
- `facts` contain deduplicated structured facts with merged source IDs.
- `quotes` contain representative quotes, deduplicated across repeated normalized fields.
- `conflicts` preserve unresolved official/community or source/source disagreement.
- `coverage` records source counts, represented source counts, dropped source count, compaction counts, and warnings.

The initial writer consumes the evidence pack instead of the current full source digest. Complete raw sources remain in `RunDetail`, database storage, traceable source IDs, and support/audit appendix generation.

## Architecture

### 1. Raw Source Storage Remains Complete

No accepted `RawSource` is deleted, hidden, or rewritten for storage. Existing raw source fields, snippets, normalized fields, metadata, URLs, and source IDs remain available in `RunDetail` and persisted run data.

This keeps debugging, audit, source appendix, and future retrieval paths intact.

### 2. Writer Evidence Pack Builder

Add a builder, preferably outside the large writer mixin, such as:

- `backend/packages/agents/writer/evidence_pack.py`

The builder should accept `RunDetail` and return a serializable pack. It should not call the LLM.

Responsibilities:

- Build one registry entry per raw source.
- Extract normalized facts from source metadata.
- Deduplicate repeated fact values and repeated quotes.
- Merge source IDs for equivalent facts.
- Preserve conflicts instead of overwriting them.
- Emit telemetry about input size and compaction.

### 3. Source Registry

Every accepted raw source must appear once in `source_registry`.

Each registry item should include:

- `id`
- `competitor`
- `covered_competitors`
- `dimension`
- `source_type`
- `title`
- `url`
- `confidence`
- `candidate_origin`
- `quality_score`
- `short_source_note`
- `has_normalized_fields`
- `has_community_clusters`

The registry is intentionally compact. It proves coverage without duplicating full snippets.

### 4. Evidence Groups

Evidence groups should be keyed by competitor and dimension:

- `competitor`
- `dimension`
- `source_ids`
- `official_source_ids`
- `community_source_ids`
- `user_research_source_ids`
- `facts`
- `quotes`
- `conflicts`
- `confidence_summary`
- `coverage_notes`

This gives writer the correct grain for report sections: pricing, feature, persona, community themes, SWOT, matrix interpretation, and deep dives.

### 5. Normalized Field Aggregation

Normalized fields should be converted into facts, not dumped one field object at a time.

Pricing facts should preserve:

- `kind`
- `competitor`
- `model_type`
- `tier_name`
- `price`
- `billing_cycle`
- `usage_limit`
- `enterprise_condition`
- `source_ids`
- `confidence`
- `quote_ids`

Feature facts should preserve:

- `feature_name`
- `capability`
- `limitation`
- `integration`
- `workflow`
- `source_ids`
- `confidence`
- `quote_ids`

Persona and user research facts should preserve:

- `segment`
- `role`
- `use_case`
- `pain_point`
- `adoption_blocker`
- `switching_trigger`
- `sentiment`
- `source_ids`
- `confidence`
- `quote_ids`

Equivalent facts should be merged by normalized semantic key. Merged facts must retain all source IDs.

### 6. Quote Deduplication

Long quotes should not repeat across dozens of normalized fields.

The builder should create a quote registry:

- `quote_id`
- `text`
- `source_ids`
- `used_by_fact_ids`
- `confidence`

Repeated quote text should appear once, with merged `source_ids` and `used_by_fact_ids`. Facts should reference quote IDs instead of embedding the quote text repeatedly.

For the OpenAI pricing pattern, 65 pricing fields with the same long quote should become many structured price facts plus one representative quote entry, not 65 duplicated quote blobs.

### 7. Community Triangulation Projection

Community claim clusters should remain writer-visible, but projected compactly:

- `claim`
- `normalized_value`
- `confidence`
- `source_ids`
- `official_source_ids`
- `conflict_values`
- `authority_signal`
- `official_commitment`

Community evidence can have high confidence when multiple independent sources converge. The pack should preserve that convergence instead of treating community sources as noise.

### 8. Conflict Preservation

If official, community, survey, interview, or snippet-only evidence disagree, the pack should not collapse the disagreement into one fact.

Conflicts should include:

- `claim_area`
- `official_position`
- `community_position`
- `other_positions`
- `source_ids_by_position`
- `confidence_by_position`
- `resolution_status`

The writer should use conflicts to write caveats, not silently choose one side.

### 9. Input Budget and Telemetry

Budgets are observability and routing thresholds, not source-dropping rules.

Recommended initial thresholds:

- Single source projected digest target: 8k characters.
- Competitor-dimension group target: 12k characters.
- Initial writer context target: 120k to 160k characters.

When thresholds are exceeded, the builder should aggregate and deduplicate further. If the final pack still exceeds the writer context target, the run should route to segmented writer generation.

Emit a writer-preflight event before the LLM call:

- `writer_evidence_pack_chars`
- `source_registry_count`
- `represented_source_count`
- `raw_source_count`
- `dropped_source_count`
- `largest_source_projection_chars`
- `largest_group_chars`
- `deduped_quote_count`
- `deduped_fact_count`
- `segmented_writer_required`

`dropped_source_count` should be zero for accepted sources. If it is not zero, that is a blocker-level implementation bug.

### 10. Segmented Writer

When the pack is large, use segmented generation instead of one monolithic call.

Recommended sections:

- Decision summary and competitive findings.
- User review themes, persona analysis, and community themes.
- Competitor deep dives.
- SWOT and matrix interpretation.
- Layer-specific battlecard/workflow/market section.
- Support appendix, evidence QA, source quality notes, and next validation tasks.

Each segment should receive:

- Global plan context.
- Source registry.
- Relevant competitor-dimension groups.
- Required citations and source IDs.
- Section-specific minimum depth.

The assembler should join sections and run existing hardening and QA logic. The assembled report must still satisfy required section and core depth gates.

### 11. Failure Handling

Initial writer generation should not use fallback report content.

If segmented writer fails:

- Fail with the segment name and error.
- Preserve telemetry showing pack size and selected groups.
- Do not emit a fake report.

Repair flows with a previous report may continue to preserve the previous report when existing anti-regression logic allows it.

## Data Flow

Current:

`RunDetail.raw_sources -> _writer_source_digest(all sources) -> Writer Context JSON -> single report_writer LLM call`

New:

`RunDetail.raw_sources -> WriterEvidencePackBuilder -> writer_preflight telemetry -> single writer or segmented writer`

The full raw source list remains available for audit and persistence:

`RunDetail.raw_sources -> persisted run detail -> report source appendix / debugging / future retrieval`

## Testing Strategy

Add focused unit tests before implementation:

1. A source with 65 normalized pricing fields and repeated quote compacts below the single-source target while preserving all price facts.
2. Every accepted raw source appears in `source_registry`.
3. Equivalent facts merge source IDs instead of dropping sources.
4. Repeated quotes become one quote registry entry.
5. Conflicting official/community facts produce a conflict entry.
6. Writer preflight emits input size telemetry.
7. Large evidence pack routes to segmented writer.
8. Segmented writer receives only relevant groups for each section plus the full source registry.
9. No accepted source is dropped from the pack.
10. Existing writer repair anti-regression behavior still preserves previous reports when appropriate.

## Rollout Plan

Phase 1: Evidence pack builder and tests.

Phase 2: Replace initial writer context source digest with evidence pack while keeping existing single-call writer path for small packs.

Phase 3: Add writer preflight telemetry.

Phase 4: Add segmented writer routing for large packs.

Phase 5: Audit recent failed runs against telemetry and compare report richness against known good reports.

## Acceptance Criteria

- `run-58dd1b8df825ffcba52fbdd1433b5956` style input reconstructs to a writer evidence pack far smaller than the current 512k context while representing all 82 raw sources.
- Repeated OpenAI pricing quote text appears once in quote registry, not 65 times.
- Writer input telemetry is visible in run events.
- Large runs do not fail solely because the initial writer prompt exceeds 600 seconds.
- Report depth does not regress against recent expanded-report expectations.
- Source auditability remains intact: every claim still cites existing source IDs and every accepted source remains traceable.
