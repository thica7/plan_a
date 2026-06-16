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
- `kb_signals` preserve every current competitor KB slice or deterministically merge it into facts/signals with provenance.
- `matrix` preserves the existing comparison matrix digest.
- `coverage` records source counts, represented source counts, dropped source count, compaction counts, and warnings.

The initial writer and writer section-repair paths consume the evidence pack instead of the current full source digest. Complete raw sources remain in `RunDetail`, database storage, traceable source IDs, and support/audit appendix generation.

## Architecture

### 1. Raw Source Storage Remains Complete

No accepted `RawSource` is deleted, hidden, or rewritten for storage. Existing raw source fields, snippets, normalized fields, metadata, URLs, and source IDs remain available in `RunDetail` and persisted run data.

This keeps debugging, audit, source appendix, and future retrieval paths intact.

### 2. Writer Evidence Pack Builder

Add a builder, preferably outside the large writer mixin, such as:

- `backend/packages/agents/writer/evidence_pack.py`

The builder should accept `RunDetail` and return a serializable result. It should not call the LLM and should not emit run events directly.

The result shape should be:

- `pack`
- `metrics`
- `warnings`

The writer orchestration layer emits telemetry from `metrics` and `warnings`.

Responsibilities:

- Build one registry entry per raw source.
- Extract normalized facts from source metadata.
- Extract compact unstructured signals from clean snippets when structured projections do not fully represent salient snippet content.
- Project current competitor KB slices and structured competitor knowledge into writer-visible signals.
- Preserve the comparison matrix digest in compact form.
- Deduplicate repeated fact values and repeated quotes.
- Merge source IDs for equivalent facts.
- Preserve conflicts instead of overwriting them.
- Return telemetry about input size and compaction.

The builder should use explicit Pydantic models or dataclasses, not untyped ad hoc dictionaries. The top-level pack should include `schema_version` so future pack shape changes do not break old run inspection or tests.

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
- `represented_by`
- `no_signal_reason`

The registry is intentionally compact. It proves coverage without duplicating full snippets.

`represented_by` is a list of pack object IDs showing how the source is writer-visible beyond the registry row, such as fact IDs, quote IDs, conflict IDs, community cluster IDs, unstructured signal IDs, or KB signal IDs. A source represented only by a registry row is not sufficiently represented for writing.

If a source has no clean business snippet, no normalized fields, no community clusters, and no usable metadata, the registry item may set `no_signal_reason` instead of inventing a weak writing signal. This should be rare and visible in telemetry.

### 4. Unstructured Source Signals

Sources must still contribute writing context when normalized fields or community clusters do not cover the useful clean snippet content. This includes sources without normalized fields and mixed sources that have structured fields plus unique snippet-only caveats, persona detail, review language, limits, or adoption signals.

For each such source, the builder should derive deterministic residual `unstructured_signals` from the clean business snippet:

- `source_id`
- `competitor`
- `dimension`
- `source_type`
- `signal_summary`
- `salient_terms`
- `confidence`
- `quote_ids`

`signal_summary` should use existing snippet-cleaning behavior and stay compact. It must not call the LLM. The goal is to preserve useful source meaning without dumping the full raw snippet.

These signals should be attached to the relevant competitor-dimension group so persona, review, feature, and pricing sections do not lose snippet-only or non-normalized evidence.

### 5. KB and Structured Knowledge Projection

The current writer context exposes `competitor_kbs` through `kb_slices` and also exposes structured `competitor_knowledge` summaries. The evidence pack must preserve those writer-visible inputs.

For each competitor and dimension:

- Every current KB slice finding must either appear as a `kb_signal` or be deterministically merged into an equivalent fact/signal.
- Merged KB findings must retain provenance using stable IDs such as `kb:{competitor}:{dimension}:{index}`.
- The pack metrics must include `kb_slice_count`, `represented_kb_slice_count`, and `dropped_kb_slice_count`.
- `dropped_kb_slice_count` must be zero unless the source text is empty or duplicate and its merged target is recorded.

Structured `competitor_knowledge` should remain writer-visible through compact projections:

- pricing model summary
- feature tree summary
- feature claims
- persona claims
- review summary when present

The implementation may keep compact comparison matrix and competitor knowledge digests outside `WriterEvidencePack` only if the writer context still includes them and tests prove they were not lost. It must not silently replace the current writer context with raw-source projection only.

### 6. Evidence Groups

Evidence groups should be keyed by competitor and dimension:

- `competitor`
- `dimension`
- `source_ids`
- `official_source_ids`
- `community_source_ids`
- `user_research_source_ids`
- `facts`
- `unstructured_signals`
- `kb_signals`
- `quotes`
- `conflicts`
- `confidence_summary`
- `coverage_notes`

This gives writer the correct grain for report sections: pricing, feature, persona, community themes, SWOT, matrix interpretation, and deep dives.

### 7. Normalized Field Aggregation

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

Equivalent facts should be merged by deterministic normalized keys, not by an LLM. The key should be explicit per fact type. For example, pricing keys should include normalized competitor, model or tier, price, billing cycle, and usage unit where present. Feature and persona keys should use normalized names, claim kind, and dimension-specific values. Merged facts must retain all source IDs and quote IDs.

Conflicting facts must not be merged merely because they share a broad key. They should become conflict entries.

### 8. Quote Deduplication

Long quotes should not repeat across dozens of normalized fields.

The builder should create a quote registry:

- `quote_id`
- `excerpt`
- `full_text_source_ids`
- `source_ids`
- `used_by_fact_ids`
- `confidence`
- `raw_quote_chars`

Repeated quote text should appear once, with merged `source_ids` and `used_by_fact_ids`. Facts should reference quote IDs instead of embedding the quote text repeatedly.

The writer-visible quote should be a bounded excerpt, not unbounded raw quote text. Full quote text stays in persisted raw sources and source metadata. The quote registry should use a deterministic normalized text key, such as whitespace-normalized text plus a hash, to merge exact repeated quotes.

For the OpenAI pricing pattern, 65 pricing fields with the same long quote should become many structured price facts plus one representative quote entry, not 65 duplicated quote blobs.

Telemetry should include `largest_quote_projection_chars` and `deduped_quote_count`.

### 9. Community Triangulation Projection

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

### 10. Conflict Preservation

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

### 11. Input Budget, Compaction, and Telemetry

Budgets are observability and routing thresholds, not source-dropping rules.

Recommended initial thresholds:

- Single source projected digest target: 8k characters.
- Competitor-dimension group target: 12k characters.
- Segment input target: 60k to 90k characters.
- Initial single-call writer context target: 120k to 160k characters.

When thresholds are exceeded, the builder should apply deterministic compaction levels in order:

1. Merge duplicate facts and repeated quotes.
2. Replace long quote text with bounded excerpts and quote IDs.
3. Merge equivalent KB findings into facts/signals with KB provenance.
4. Convert residual clean snippets into compact `unstructured_signals`.
5. Split oversized groups across segmented writer calls.

These invariants must never be violated:

- no accepted raw source is removed from `source_registry`
- every accepted raw source has at least one `represented_by` item beyond the registry row or an explicit `no_signal_reason`
- no represented source ID is dropped from a merged fact, signal, quote, conflict, or KB signal
- conflicting values are preserved as conflicts, not merged away
- full raw evidence remains available in persisted run data

If a pack or segment cannot fit without violating those invariants, fail fast before the LLM call with a precise preflight error and telemetry. Do not silently truncate facts, drop sources, or emit a fallback report.

Emit a writer-preflight event before the LLM call:

- `writer_evidence_pack_chars`
- `source_registry_count`
- `represented_source_count`
- `raw_source_count`
- `dropped_source_count`
- `no_signal_source_count`
- `kb_slice_count`
- `represented_kb_slice_count`
- `dropped_kb_slice_count`
- `largest_source_projection_chars`
- `largest_group_chars`
- `largest_quote_projection_chars`
- `deduped_quote_count`
- `deduped_fact_count`
- `preflight_warnings`
- `segmented_writer_required`

`dropped_source_count` should be zero for accepted sources. If it is not zero, that is a blocker-level implementation bug.

### 12. Segmented Writer

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
- Required citations and allowed source IDs for that segment.
- Section-specific minimum depth.

Each segment should have preflight telemetry:

- `segment_name`
- `segment_input_chars`
- `segment_source_count`
- `segment_group_count`
- `segment_allowed_source_ids`
- `segment_retry_count`

If a segment times out or returns empty content, retry that segment once with the same evidence pack and a clearer continuation instruction. If it fails again, fail the run or preserve the previous report only when the existing repair anti-regression path already allows preservation. Do not use fake fallback content.

The assembler should join sections and run existing hardening and QA logic. The assembled report must still satisfy required section and core depth gates.

Post-assembly validation must check:

- every citation uses a source ID in the global source registry
- citations in a generated section come from the segment's allowed source IDs
- required sections are present
- core depth gates still pass

If validation fails, route through existing repair logic with evidence-pack context.

### 13. Writer Repair Integration

The existing section repair path also builds `Writer Context JSON`. It must use the same evidence pack builder and should pass only the relevant groups for the section being repaired, plus the full source registry.

Section repair must not reintroduce the current full source digest. Otherwise a report that succeeds initially can still time out or regress during repair.

Line repair remains deterministic and does not need evidence-pack LLM context unless it escalates to section repair.

### 14. Source Appendix Generation

The evidence/source appendix should not require passing full raw snippets back into an LLM prompt. It should be generated from the compact source registry and, when needed, deterministic raw source metadata outside the main writer call.

The appendix should list enough information for audit:

- source ID
- title
- URL
- source type
- competitor and dimension
- confidence
- represented-by IDs

Full raw snippets and normalized fields remain inspectable in persisted run detail, not duplicated into the writer prompt.

### 15. Backward Compatibility

Existing runs do not have a stored evidence pack. Report viewing should continue to use persisted `report_md`, `raw_sources`, and existing run detail fields.

Evidence packs are generated at writer time for new runs and redo runs. If an old run is manually repaired, the builder should construct the pack from the old run's existing `RunDetail` fields.

### 16. Failure Handling

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

`RunDetail.raw_sources + competitor_kbs + competitor_knowledge + comparison_matrix -> WriterEvidencePackBuilder -> writer_preflight telemetry -> single writer, segmented writer, or section repair writer`

The full raw source list remains available for audit and persistence:

`RunDetail.raw_sources -> persisted run detail -> report source appendix / debugging / future retrieval`

## Testing Strategy

Add focused unit tests before implementation:

1. A source with 65 normalized pricing fields and repeated quote compacts below the single-source target while preserving all price facts.
2. Every accepted raw source appears in `source_registry`.
3. Equivalent facts merge source IDs instead of dropping sources.
4. Repeated quotes become one quote registry entry.
5. Conflicting official/community facts produce a conflict entry.
6. A non-normalized snippet-only source produces an `unstructured_signal`, not only a source registry row.
7. A mixed source with normalized fields plus unique clean snippet content produces residual `unstructured_signals`.
8. Every current KB slice appears as a `kb_signal` or is deterministically merged with KB provenance.
9. Unique long quotes are bounded as writer excerpts while full text remains in persisted raw source data.
10. Writer preflight emits input size telemetry.
11. Oversized packs fail preflight rather than silently dropping facts or sources.
12. Large evidence pack routes to segmented writer.
13. Segmented writer receives only relevant groups for each section plus the full source registry.
14. Segment outputs are citation-validated against segment allowed source IDs.
15. Section repair uses evidence-pack context and does not call the old full source digest path.
16. No accepted source is dropped from the pack; unusable/noisy sources are counted with explicit `no_signal_reason`.
17. Existing writer repair anti-regression behavior still preserves previous reports when appropriate.

## Rollout Plan

Phase 1: Evidence pack builder and tests.

Phase 2: Add KB slice, structured knowledge, matrix, residual snippet, and quote-budget projections.

Phase 3: Replace initial writer context source digest with evidence pack while keeping existing single-call writer path for small packs.

Phase 4: Add writer preflight telemetry and preflight failure handling.

Phase 5: Replace writer section-repair context with section-scoped evidence pack context.

Phase 6: Add segmented writer routing, segment telemetry, segment retry, and segment citation validation.

Phase 7: Add deterministic source appendix generation from the registry/raw-source metadata.

Phase 8: Audit recent failed runs against telemetry and compare report richness against known good reports.

## Acceptance Criteria

- `run-58dd1b8df825ffcba52fbdd1433b5956` style input reconstructs to a writer evidence pack far smaller than the current 512k context while representing all 82 raw sources.
- Repeated OpenAI pricing quote text appears once in quote registry, not 65 times.
- Snippet-only and non-normalized sources appear as compact unstructured signals, not just registry rows.
- Sources with no usable writer signal are explicitly marked with `no_signal_reason`, not silently dropped.
- Mixed structured/unstructured sources preserve residual clean snippet content when it carries unique writing signal.
- Every current KB slice remains writer-visible or is merged with explicit KB provenance.
- Writer input telemetry is visible in run events.
- Large runs do not fail solely because the initial writer prompt exceeds 600 seconds.
- Writer section repair does not use the old full source digest path.
- Segmented writer validates citations against segment-supplied source IDs.
- Source appendix generation does not require full raw snippets in the writer prompt.
- Report depth does not regress against recent expanded-report expectations.
- Source auditability remains intact: every claim still cites existing source IDs and every accepted source remains traceable.
