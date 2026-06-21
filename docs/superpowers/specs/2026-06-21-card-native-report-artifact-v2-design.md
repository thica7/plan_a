# Card-Native Report Artifact v2 Design

## Status

Canonical design. This supersedes:

- `docs/superpowers/specs/2026-06-21-hybrid-report-artifact-v2-design.md`
- `docs/superpowers/plans/2026-06-21-hybrid-report-artifact-v2.md`
- `docs/superpowers/specs/2026-06-21-report-artifact-v2-dual-layer-design.md`
- `docs/superpowers/plans/2026-06-21-report-artifact-v2-dual-layer.md`

The previous hybrid design had the right destination, but its implementation
plan placed card builders after the existing run data in `business_intel`. That
does not satisfy the required ownership boundary. This design makes cards
native to analyst and comparator while preserving the current project pipeline.

## Current Code Reality

The project already has partial structure:

- Analyst writes `CompetitorKnowledge`, `KnowledgeClaim`, `ReviewThemeSummary`,
  and `CompetitorKB` in `backend/packages/agents/analysts/logic.py`.
- Comparator writes `ComparisonMatrix`, `ComparisonCell`, SWOT refreshes, and
  `winner_by_dimension` in `backend/packages/agents/comparator/logic.py`.
- Writer uses `WriterEvidencePack`, schema-contract segmented Markdown,
  publication contract checks, section repair, and Markdown hardening in
  `backend/packages/agents/writer/logic.py`.
- API run details expose `RunDetail.report_md`, `competitor_knowledge`, and
  `comparison_matrix` in `backend/packages/schema/api_dto.py`.
- Enterprise projection converts `detail.report_md` into
  `ReportVersionRecord.report_md` in `backend/packages/enterprise/projection.py`.
- Release gate currently evaluates and may repair `report_md` through
  `apply_release_gate_warning_report_repair()` in
  `backend/packages/orchestrator/service.py`.
- Frontend report display currently reads one report Markdown string through
  run detail and enterprise report version models.

The durable fix must evolve these existing boundaries. It must not add a
post-hoc card builder that runs after analyst and comparator have already lost
their reasoning context.

## Goal

Build the terminal report architecture:

```text
RawSource / normalized fields / community clusters
  -> Analyst-owned ClaimCardBundle
  -> Comparator-owned DecisionCardBundle
  -> SectionBriefBundle
  -> Natural Segment Writer
  -> Deterministic Assembler / Publication Contract
  -> ReportArtifactV2
```

This must satisfy both requirements:

1. Third-scheme reasoning boundary:
   - Collector gathers raw sources and light normalized extraction only.
   - Analyst turns evidence into claim cards.
   - Comparator turns cross-competitor claim cards into decision cards.
   - Writer consumes cards and briefs; it does not invent facts or
     recommendations.
   - Python owns report structure, citation hygiene, core/support separation,
     and failure routing.
   - Redo changes claim cards, decision cards, or section prose by explicit
     target. It does not rewrite the whole report without a decision-level
     reason.
2. Full-project dual-layer report product:
   - DB/API distinguish core report, support appendix, audit log, structured
     artifact, and compatibility Markdown.
   - Writer emits a structured report artifact, not only one large Markdown
     string.
   - QA/release gate validate core business conclusions separately from
     support and audit material.
   - Frontend report view supports Report, Evidence, QA, and Audit layers.
   - Export supports core-only and full-audit outputs.
   - Old runs read through a legacy `report_md` adapter.

## Non-Goals

- Do not rewrite collector/fetch/source identity in this project.
- Do not remove existing `CompetitorKnowledge`, `ComparisonMatrix`, or
  `report_md` fields immediately. They remain compatibility views.
- Do not revive pure typed report JSON as the writer main path.
- Do not make release gate silently edit V2 core prose.
- Do not migrate historical run rows eagerly. Use an adapter for old runs.

## Design Principles

### Preserve Natural Writing, Move Judgment Upstream

The writer keeps natural segmented writing because the stable-quality reports
came from prose generation, not from rigid typed JSON. The boundary changes:
writer receives allowed claims, allowed decisions, required questions, and
forbidden overreach. It writes a professional argument but cannot create a new
fact, recommendation, winner, pricing claim, risk posture, or why-not rationale.

### Cards Are Native Outputs, Not Post-Processing

`ClaimCard` is produced by analyst while source context is still local to a
competitor and dimension. `DecisionCard` is produced by comparator while matrix
signals and cross-competitor tradeoffs are still local. A deterministic adapter
can translate legacy `KnowledgeClaim` and `ComparisonMatrix` into cards only
for old runs and temporary migration tests.

### Existing Models Become Compatibility Views

`KnowledgeClaim` stays useful as a compact claim view for current KB,
enterprise claim records, and legacy UI. `ComparisonMatrix` stays useful as a
matrix view and old report input. After this design, both should be derived from
or synchronized with card-native data, not treated as the highest-fidelity
reasoning source.

### Report Artifact Owns Publication

`ReportArtifactV2` is the publication product. `report_md` is a render cache for
old consumers. Any new API, frontend, export, QA, and release-gate logic must
prefer artifact fields when present.

## Data Contracts

### ClaimCard

Analyst-owned atomic or gap-aware claim.

Required fields:

- `id`
- `run_id`
- `competitor`
- `dimension`
- `claim_type`
- `claim`
- `source_ids`
- `confidence`
- `evidence_strength`: `strong`, `moderate`, `weak`, `insufficient`
- `support_level`: `official`, `triangulated_community`, `single_source`,
  `simulated`, `inferred`, `gap`
- `scope`
- `caveats`
- `conflicts`
- `applicability`
- `produced_by`: always `analyst`
- `producer_stage`: analyst branch id or `analyst_join`
- `derived_from`: source ids, normalized field ids, or legacy claim ids
- `metadata`

Rules:

- A factual card with `evidence_strength != insufficient` must cite at least
  one source id.
- A gap card may have no source ids, but must set `support_level="gap"` and
  explain the missing evidence.
- Simulated survey/interview cards must be labeled `support_level="simulated"`.
  They can support persona/user-signal sections, but cannot become official
  proof of product facts.
- Conflicting evidence must stay on the card as `conflicts`; analyst must not
  hide conflicts by averaging them away.

### ClaimCardBundle

Analyst-owned branch output.

Required fields:

- `run_id`
- `competitor`
- `dimension`
- `cards`
- `source_ids`
- `coverage`
- `gap_count`
- `generated_at`
- `producer_context`

Location:

- Add to `RunDetail` as `claim_card_bundles: list[ClaimCardBundle]`.
- Keep `CompetitorKnowledge` populated for compatibility.
- Add helper accessors that select cards by competitor, dimension, and source.

Analyst integration:

- `backend/packages/agents/analysts/logic.py` remains the main producer.
- `_real_analyst_branch_step()` and the existing merge path must emit
  `ClaimCardBundle` for each competitor/dimension branch.
- `_merge_structured_knowledge_slice()` can continue to populate
  `CompetitorKnowledge`, but it must not be the only durable reasoning output.
- The existing `_structured_claims_for_dimension()` path becomes a compatibility
  projection from claim cards or a temporary source for legacy adapter tests.

### DecisionCard

Comparator-owned recommendation or cross-competitor judgment.

Required fields:

- `id`
- `run_id`
- `decision_type`: `dimension_winner`, `overall_recommendation`,
  `risk_adjusted_recommendation`, `why_not`, `battlecard_position`,
  `swot_interpretation`
- `subject`
- `recommendation`
- `posture`: `strong`, `tentative`, `watch`, `avoid`, `insufficient_evidence`
- `rationale`
- `claim_card_ids`
- `source_ids`
- `winner`
- `alternatives`
- `why_not`
- `risk_factors`
- `evidence_strength`
- `confidence`
- `produced_by`: always `comparator`
- `producer_stage`: `comparator`
- `metadata`

Rules:

- A decision card must cite claim card ids. It may cite source ids only through
  those claim cards.
- A strong recommendation requires strong or triangulated claim-card support
  across the relevant dimensions.
- A comparator fallback can produce only tentative or insufficient-evidence
  decision cards.
- Writer cannot change `posture`, `winner`, or `why_not`. A change requires
  comparator redo or explicit decision-card repair.

### DecisionCardBundle

Comparator-owned run output.

Required fields:

- `run_id`
- `cards`
- `matrix_snapshot`
- `coverage_by_dimension`
- `recommendation_card_id`
- `generated_at`
- `producer_context`

Location:

- Add to `RunDetail` as `decision_card_bundle: DecisionCardBundle | None`.
- Keep `ComparisonMatrix` populated for compatibility.
- `ComparisonMatrix.winner_by_dimension` becomes a compact view that must align
  with dimension-winner decision cards.

Comparator integration:

- `backend/packages/agents/comparator/logic.py` remains the main producer.
- `_real_comparator_step()` still builds `ComparisonMatrix`, then builds
  `DecisionCardBundle` from claim cards, matrix cells, majority vote,
  fallback status, and SWOT signals.
- `_matrix_majority_vote()` remains useful as one input to decision cards, but
  the decision card stores risk-adjusted rationale and why-not alternatives.

### SectionBrief

Writer-facing contract generated from claim and decision cards.

Required fields:

- `id`
- `section_key`
- `layer`: `core`, `support`, `audit`
- `required_questions`
- `allowed_claim_card_ids`
- `allowed_decision_card_ids`
- `allowed_source_ids`
- `must_include`
- `must_not_claim`
- `tone`
- `minimum_depth`
- `citation_policy`
- `repair_targets`

Rules:

- Core briefs reference decision and claim cards.
- Support briefs render evidence tables, card summaries, source quality, RAG,
  and caveats.
- Audit briefs render trace, QA, redo, release-gate decisions, fallback usage,
  and model/runtime status.
- Section briefs are deterministic. They are not free-form LLM outputs.

### ReportArtifactV2

Publication product.

Required fields:

- `artifact_version`: `2`
- `run_id`
- `core_report`: markdown layer plus section metadata
- `support_appendix`: markdown layer plus section metadata
- `audit_log`: markdown layer plus event/quality metadata
- `claim_card_bundles`
- `decision_card_bundle`
- `section_briefs`
- `quality`
- `render_cache`:
  - `core_markdown`
  - `support_markdown`
  - `audit_markdown`
  - `full_markdown`
- `legacy`

Rules:

- `full_markdown` is assembled from core, support, and audit.
- `report_md` equals `full_markdown` only for compatibility.
- New consumers must read artifact fields first.
- The core report must not include support checklist, release-gate audit rows,
  raw trace dumps, or internal implementation labels.

## Pipeline Changes

### Collector

Current collector responsibilities stay intact:

- find official, community, and simulated sources;
- preserve raw source details;
- attach normalized fields and community clusters;
- set source confidence and metadata.

Collector must not produce final claims or recommendations. It can produce
light extracted facts as source metadata, but analyst decides whether those
facts become claim cards.

### Analyst

Current analyst responsibilities expand:

1. Consume raw sources per competitor/dimension.
2. Build `ClaimCardBundle`.
3. Populate compatibility `CompetitorKnowledge` and `CompetitorKB`.
4. Emit agent message `claim_card_bundle_ready`.
5. Route analyst redo to specific competitor/dimension card bundles.

If a dimension has weak or missing evidence, analyst emits explicit gap cards
instead of letting writer discover the absence later.

Refactor allowance:

- If adding card production inside the current large
  `backend/packages/agents/analysts/logic.py` makes the file harder to reason
  about, extract focused helpers under `backend/packages/agents/analysts/cards.py`.
- The extracted helper is still analyst-owned. It is not a generic post-hoc
  builder in `business_intel`.

### Comparator

Current comparator responsibilities expand:

1. Consume claim card bundles and compatibility matrix inputs.
2. Build `ComparisonMatrix` for existing UI/report compatibility.
3. Build `DecisionCardBundle`.
4. Emit agent message `decision_card_bundle_ready`.
5. Route comparator redo to specific decision cards or dimensions.

Decision cards must explicitly distinguish:

- paper winner by dimension;
- risk-adjusted recommendation;
- why not each major alternative;
- evidence strength behind the recommendation;
- whether the recommendation is strong or tentative.

Refactor allowance:

- If `backend/packages/agents/comparator/logic.py` becomes too mixed, extract
  `backend/packages/agents/comparator/decision_cards.py`.
- The extracted helper is comparator-owned and receives claim cards plus matrix
  signals. It must not call writer logic.

### Writer

Writer keeps natural segmented Markdown generation but loses reasoning
ownership.

Writer input becomes:

- `SectionBriefBundle`;
- allowed claim cards;
- allowed decision cards;
- bounded evidence snippets for cited cards;
- language and style instructions;
- previous section prose only for scoped repair.

Writer output becomes:

- section fragments for core/support/audit briefs;
- no direct mutation of recommendations;
- no direct publication artifact assembly.

The existing schema-contract segmented writer can be retained as the authoring
engine, but its segment payloads must be generated from section briefs. Current
Markdown heading repair and section backfill remain legacy safeguards, not the
V2 structure source.

### Deterministic Assembler And Publication Contract

Assembler owns:

- H2/H3/H4 headings;
- section order;
- section markers;
- citation placement rules;
- core/support/audit layer split;
- render caches;
- final `ReportArtifactV2`.

Publication contract validates artifact structure, not only Markdown:

- every cited source belongs to an allowed card;
- every core claim maps to a claim card or decision card;
- every recommendation maps to a decision card;
- support/audit content cannot leak into core;
- internal fields such as `source_registry`, `allowed_source_ids`,
  `represented_by`, and raw segment JSON cannot appear in rendered report text.

### QA And Release Gate

V2 release gate scope:

- Core gate: business claims, recommendation consistency, evidence strength,
  citation validity, and language/readability of core report.
- Support gate: source/card coverage, evidence gap completeness, card trace
  integrity.
- Audit gate: redo trace, fallback visibility, quality accounting consistency,
  event/revision count consistency.

For V2 artifacts, release gate must not call
`apply_release_gate_warning_report_repair()` on core Markdown. It may:

- write quality metadata;
- add audit findings;
- produce redo tasks;
- mark execution completed with quality warnings;
- block publication when blockers remain.

### Redo Routing

Existing redo scopes remain:

- `collector`
- `analyst`
- `comparator`
- `writer_only`
- `full`

They gain structured targets:

- `source_id`
- `claim_card_id`
- `decision_card_id`
- `section_key`
- `artifact_layer`

Routing rules:

- Weak/missing evidence -> collector or analyst card redo.
- Wrong or drifting recommendation -> comparator decision-card redo.
- Thin or unclear prose with valid cards -> writer section redo.
- Heading/citation/layer issue -> assembler/publication contract repair.
- Audit mismatch -> audit/quality-accounting repair.
- Full rewrite only when upstream fact or decision basis changed broadly.

## Persistence And API

### RunDetail

Add:

- `claim_card_bundles: list[ClaimCardBundle]`
- `decision_card_bundle: DecisionCardBundle | None`
- `section_briefs: list[SectionBrief]`
- `report_artifact: ReportArtifactV2 | None`

Keep:

- `report_md`
- `competitor_knowledge`
- `comparison_matrix`

Compatibility rule:

- If `report_artifact` exists, `report_md` is a compatibility alias for
  `report_artifact.render_cache.full_markdown`.
- If `report_artifact` does not exist, legacy consumers read `report_md`.

### ReportVersionRecord

Add:

- `core_report_md`
- `support_appendix_md`
- `audit_log_md`
- `full_report_md`
- `report_artifact`

Keep:

- `report_md`

Compatibility rule:

- V2 `report_md` equals `full_report_md`.
- Legacy rows with only `report_md` are adapted into a synthetic artifact at
  read time.

### Postgres Migration

Modify `backend/db/postgres/001_enterprise_core.sql`:

- add `core_report_md TEXT NOT NULL DEFAULT ''`
- add `support_appendix_md TEXT NOT NULL DEFAULT ''`
- add `audit_log_md TEXT NOT NULL DEFAULT ''`
- add `full_report_md TEXT NOT NULL DEFAULT ''`
- add `report_artifact JSONB NOT NULL DEFAULT '{}'::jsonb`

The migration must be idempotent and must not rewrite old report bodies.

### Enterprise Store And Projection

Projection changes:

- `build_enterprise_projection()` reads `detail.report_artifact` first.
- V2 report versions store layer fields and artifact JSON.
- Legacy projection path still normalizes source tokens from `detail.report_md`.
- `ClaimRecord` can continue to be populated from claim cards and compatibility
  `KnowledgeClaim` during migration.

Store changes:

- in-memory store preserves artifact fields;
- Postgres store writes and reads artifact fields;
- report version links still expose claim and evidence ids for existing
  workbench panels.

## Frontend And Export

### Frontend Report View

The run report view must expose:

- `Report`: core report only.
- `Evidence`: support appendix, claim cards, decision cards, source trace.
- `QA`: quality findings, release gate issues, card validation status.
- `Audit`: workflow trace, fallback usage, redo decisions, revision accounting.

Rules:

- V2 reports default to `Report`.
- Legacy reports keep the current single Markdown view through adapter data.
- Card IDs are visible in evidence/audit layers, not as noisy implementation
  text in core report.

### API Types And SSE

Frontend API types must model:

- `ClaimCard`
- `ClaimCardBundle`
- `DecisionCard`
- `DecisionCardBundle`
- `SectionBrief`
- `ReportArtifactV2`
- layered report Markdown fields on report versions

SSE report updates may include `report_artifact`. If present, frontend stores
the artifact and renders layers from it.

### Export

Report export supports:

- `scope=core`: core report only.
- `scope=full`: core + support + audit.
- `scope=support`: support appendix only.
- `scope=audit`: audit log only.

Default export for business users is `core`. Full audit export is explicit.

## Legacy And Cleanup

### Legacy Adapter

Create an adapter that converts old rows into a synthetic V2 shape:

- `core_report.markdown = report_md`
- `support_appendix.markdown = ""`
- `audit_log.markdown = ""`
- `render_cache.full_markdown = report_md`
- `legacy.source = "report_md"`

This adapter is read-only. It does not mutate old rows.

### Old Writer Modules

Keep during migration:

- segmented natural writing;
- citation sanitizer;
- publication contract checks that can validate artifact output;
- anti-regression checks that compare core report and decision cards.

Demote to legacy or remove from V2 main path:

- pure typed final report JSON as a primary writer path;
- required-section Markdown backfill as a V2 structure source;
- release-gate Markdown warning repair for V2 artifacts;
- post-hoc `business_intel` card builders as main producers.

## Acceptance Criteria

### Architecture

- Analyst produces claim card bundles during analyst execution.
- Comparator produces decision card bundle during comparator execution.
- Writer consumes section briefs and card-scoped evidence.
- Assembler produces `ReportArtifactV2`.
- `report_md` is not the publication source of truth for V2 runs.

### Product

- DB/API expose core, support, audit, full, and artifact fields.
- Frontend exposes Report, Evidence, QA, and Audit layers.
- Export supports core-only and full-audit scopes.
- Legacy runs still render.

### Quality

- Release gate validates core report plus cards.
- Support/audit material does not generate false business-claim warnings.
- V2 release gate does not edit core Markdown.
- Redo can target claim cards, decision cards, sections, layers, or legacy
  scopes.
- Recommendation changes require decision-card changes.
- Writer-only redo cannot change recommendation posture unless comparator
  produced a new decision card.

### Traceability

- Every core factual claim maps to a claim card or decision card.
- Every decision card maps to claim cards.
- Every claim card maps to sources or an explicit evidence gap.
- Fallback module status is visible in audit.
- Event, revision, QA, and release-gate counts agree in the artifact quality
  account.

## Implementation Decomposition

The implementation plan should be split into phases:

1. Schema and legacy adapter.
2. Analyst native claim cards.
3. Comparator native decision cards.
4. Section briefs and writer input contract.
5. Deterministic artifact assembler and publication contract.
6. Enterprise projection, store, Postgres migration, and API.
7. Release gate and redo routing.
8. Frontend layers and export scopes.
9. End-to-end verification with real runs.

Each phase must be independently testable and committed separately.

## Final Decision

The active direction is not "pure typed JSON writer" and not "free natural
segments with repair patches." The active direction is card-native upstream
reasoning plus natural writer expression plus deterministic artifact
publication.

This design is the canonical target for the next implementation plan.
