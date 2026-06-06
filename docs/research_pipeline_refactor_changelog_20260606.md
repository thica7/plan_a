# Research Pipeline Refactor Changelog

## 2026-06-06 - Step 1: Typed Research Contracts

Commit: `2f084d1 refactor(research): add typed pipeline contracts`

Scope:

- Added `backend/packages/research/` as the new clean research pipeline package.
- Added typed contracts for `ResearchBrief`, `SourceCandidate`, `CapturedPage`,
  `ExtractionResult`, `EvidenceItem`, `QualityGap`, `RepairTask`, and
  `ResearchResult`.
- Unified `tools.source_discovery.SourceCandidate` to use the new
  `research.models.SourceCandidate` contract instead of maintaining a second
  dataclass with the same name.
- Kept URL fields as plain strings at the research boundary so existing fetch,
  source identity, tests, and UI code do not need scattered `HttpUrl` conversions.
- Added competitor/dimension context to collector-created source candidates so
  candidate IDs and trace metadata stay stable and auditable.

Why:

- Establishes the clean pipeline vocabulary before moving behavior.
- Prevents duplicate source-candidate models from drifting apart.
- Keeps the first refactor step behavior-compatible while creating the typed
  contracts needed for discovery, capture, extraction, evaluation, and repair.

Validation:

- `ruff check backend/packages/research backend/packages/tools/source_discovery.py backend/packages/agents/collectors/logic.py backend/packages/agents/collectors/skill_tools.py`
- `pytest backend/tests/unit/test_run_service.py -q`

## 2026-06-06 - Step 2: Discovery, Capture, And Admission Boundaries

Commit: `afcf480 refactor(research): split discovery capture admission`

Scope:

- Added `research.discovery` with a single candidate frontier for trusted
  registry, homepage-derived, and search-result candidates.
- Added `rank_and_dedupe_candidates()` so origin priority, trusted-domain
  scoring, dimension hints, and URL dedupe live in one place.
- Added `research.capture.capture_candidate()` to turn a `SourceCandidate` into
  a typed `CapturedPage` without mixing in business evidence rules.
- Added `research.evidence.raw_source_from_capture()` and
  `source_quality_problem()` so evidence admission and RawSource lineage are
  owned by the research layer.
- Changed the collector source-quality adapter to call the new research
  admission function instead of owning the rule body directly.
- Added unit coverage for discovery separation, candidate ranking, capture
  output, RawSource lineage, and soft-404 rejection.

Why:

- Separates URL discovery, page capture, and evidence admission into clear
  stages.
- Starts shrinking collector responsibility without changing the public run
  contract.
- Creates the foundation for gap-driven repair to reuse the same discovery and
  capture stack.

Validation:

- `ruff check backend/packages/research backend/packages/agents/collectors/logic.py backend/tests/unit/test_research_pipeline.py`
- `pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q`

## 2026-06-06 - Step 3: Extraction, Evaluation, And Repair Tasks

Commit: `83b8aeb refactor(research): add extract evaluate repair stages`

Scope:

- Added `research.extraction` modules for pricing, feature-slot, and persona
  schema extraction from captured pages.
- Added `extract_page()` dimension dispatch so downstream collector integration
  has one typed extraction entry point.
- Added `research.evaluation.quality_gaps_from_extractions()` to convert
  extraction results into structured quality gaps instead of mixing warnings
  into collector control flow.
- Added `research.repair.repair_tasks_from_gaps()` to convert QA-warning and
  gap-driven findings into targeted discovery queries.
- Added tests for open-weight pricing not-applicability, feature-slot gap
  repair, persona schema repair, and dimension-based extraction dispatch.

Why:

- Keeps Clean Research Pipeline as the main architecture while making
  QA-warning/GAP-driven behavior a first-class evaluation and repair stage.
- Prevents objects like Llama from being forced into SaaS pricing tier
  schemas when the verified public source describes open-weight or license
  access.
- Gives future release-gate and redo logic a typed repair contract instead of
  scattered string warnings.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/research backend/tests/unit/test_research_pipeline.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q`

## 2026-06-06 - Step 4: Collector Adapter Integration

Commit: `57a95d6 refactor(collector): route collection through research pipeline`

Scope:

- Routed collector official-source discovery through `ResearchBrief`,
  `trusted_registry_candidates()`, and `homepage_candidates()`.
- Routed collector search-result candidates through
  `search_result_candidates()` so web search, Perplexity, and derived
  candidates share the same ranking/dedupe boundary.
- Changed `_source_from_search_result()` to capture pages with
  `capture_candidate()` and create `RawSource` records with
  `raw_source_from_capture()` instead of hand-writing duplicate RawSource
  construction logic.
- Updated skill-tool collection to use the same research discovery candidate
  contract as the main collector path.
- Hardened `capture_candidate()` for legacy fetch results and `None` returns,
  so fetch compatibility stays in capture rather than leaking back into
  collector logic.

Why:

- Makes Clean Research Pipeline the actual collector boundary, not just a
  parallel package.
- Reduces source identity drift by generating source candidates and RawSource
  lineage in one place.
- Keeps webfetch/basic-fetch compatibility behind the capture stage.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/agents/collectors backend/packages/research backend/tests/unit/test_research_pipeline.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q`

## 2026-06-06 - Step 11: Canonical Report Source Identity

Scope:

- Fixed the enterprise source reconciliation boundary that rewrote writer
  `RawSource.id` report citations into `EvidenceRecord.id` hash citations.
- Kept report markdown canonicalized to `RawSource.id` while preserving
  `ReportVersion.evidence_ids` as enterprise `EvidenceRecord.id` storage scope.
- Updated source reconciliation metadata so EvidenceRecord IDs are treated as
  accepted aliases, not the preferred report token.
- Moved source-origin priority constants into `research.discovery.constants` and
  made research package exports lazy to remove the discovery import cycle.
- Updated source reconciliation, enterprise projection, and RAG gap-fill tests
  around the RawSource citation contract.

Why:

- The report/source UI, release gate, gap fill, and enterprise projection now
  share one citation contract: reports cite RawSource IDs; storage links use
  EvidenceRecord IDs.
- Prevents 64-character enterprise hash IDs from leaking into report markdown
  and causing missing-source cards when the UI expects RawSource citations.
- Keeps the fix at the generation/projection boundary instead of adding
  frontend-only token rewriting.

Validation:

- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_source_reconciliation.py backend/tests/unit/test_enterprise_projection.py backend/tests/unit/test_business_intel.py backend/tests/unit/test_report_quality.py backend/tests/unit/test_gap_retrieval.py -q`
- `conda run -n bd-competiscope-v2 ruff check backend/packages/sources/references.py backend/packages/research backend/packages/tools/source_discovery.py backend/packages/tools/official_docs.py backend/tests/unit/test_source_reconciliation.py backend/tests/unit/test_enterprise_projection.py backend/tests/unit/test_gap_retrieval.py`

## 2026-06-06 - Step 6: Release Gate Repair Bridge

Commit: `fde00b5 feat(research): bridge release gate gaps to redo tasks`

Scope:

- Added `quality_gaps_from_release_gate()` to map `ReportReleaseGate.issues`
  into typed `QualityGap` objects.
- Added `repair_task_to_redo_scope()` and `repair_tasks_to_redo_scopes()` to
  convert pipeline repair tasks into scoped LangGraph redo requests.
- Added coverage proving release-gate blocker issues can flow through
  `QualityGap -> RepairTask -> RedoScope`.

Why:

- Turns release gate from a terminal blocker into a typed repair signal.
- Keeps the mapping deterministic and testable instead of parsing blocked
  report text in the collector or writer.
- Gives the next integration step a clean bridge into existing scoped redo.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/research backend/tests/unit/test_research_pipeline.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py -q`

## 2026-06-06 - Step 10: Closed Loop Documentation

Commit: `893efb8 docs(research): summarize closed loop implementation`

Scope:

- Added `docs/research_pipeline_closed_loop_summary_20260606.md`.
- Updated the earlier refactor summary follow-up list to reflect the completed
  release-gate repair bridge, field-level admission, cache metrics, and
  assembly output.
- Recorded the final validation commands and closed-loop commit sequence.

Why:

- Preserves the implementation contract for future development and deployment.
- Makes clear which layers were completed and which existing layers were
  intentionally not rewritten.
- Provides the requested human-readable change explanation after code
  completion.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/agents/collectors backend/packages/orchestrator/service.py backend/packages/research backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_enterprise_store.py::test_run_service_records_release_gate_notification_for_weak_report -q`

## 2026-06-06 - Step 9: Research Assembly Output

Commit: `4b95ffc feat(research): assemble branch evidence summaries`

Scope:

- Added `research.assembly.assemble_research_summary()` as the standard
  branch-level assembly output for accepted fields, rejected fields, gaps, and
  repair tasks.
- Added `ResearchResult.assembly` so the pipeline returns an evidence package,
  not only raw stage artifacts.
- Wired `run_research_pipeline()` to populate assembly output.
- Added test assertions that assembly carries branch key, accepted evidence
  counts, and field summaries.

Why:

- Closes the assembly layer without rewriting the existing report writer.
- Gives comparator/writer/release-gate follow-up work a stable research package
  to consume.
- Keeps report generation separate from evidence-field assembly.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/research backend/tests/unit/test_research_pipeline.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py -q`

## 2026-06-06 - Step 7: Release Gate To Auto-Redo Integration

Commit: `60567ff feat(orchestrator): auto redo blocked release gates`

Scope:

- Synced blocked release-gate issues into `RunDetail.qa_findings` as
  `release_gate.*` QCIssue records.
- Reused existing scoped redo selection and `_maybe_run_auto_redo()` instead of
  creating a second redo mechanism.
- Limited release-gate-triggered auto redo to real runs; demo runs still surface
  `completed_with_blockers` for review and presentation.
- Added service-level tests for release-gate repair issue sync, real-run auto
  redo dispatch, and demo-mode non-dispatch.

Why:

- Completes the core control loop from final release gate blocker back to typed
  scoped redo.
- Keeps HITL/manual review behavior intact because existing auto-redo policy and
  redo limits still apply.
- Avoids hidden demo behavior changes while enabling real-run self-repair.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/orchestrator/service.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_run_service.py -q`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_enterprise_store.py::test_run_service_records_release_gate_notification_for_weak_report -q`

## 2026-06-06 - Step 8: Field Admission And Capture Cache

Commit: `c7de5f8 feat(research): add field admission and capture cache`

Scope:

- Moved field-level `EvidenceItem` assembly into
  `research.evidence.evidence_items_from_extractions()`.
- Added confidence-based field admission status and rejection reasons.
- Added `CaptureCache` to reuse captured pages by canonical URL while rebinding
  candidate lineage IDs.
- Added pipeline metrics for accepted evidence items, capture cache hits,
  fetch count, and source saturation.
- Added tests for low-confidence field rejection, cache reuse with lineage
  rebinding, and the updated pipeline metrics path.

Why:

- Finishes the field-level evidence admission part of the clean pipeline.
- Keeps repeated fetch control in the capture layer instead of scattering URL
  caches through collectors.
- Makes source saturation observable at the pipeline boundary.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/research backend/tests/unit/test_research_pipeline.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py -q`

## 2026-06-06 - Step 9: Report Source Identity And Scope Contract

Commit: this commit

Scope:

- Kept report markdown, report source cards, and frontend anchors on canonical
  `RawSource.id` values.
- Treated `EvidenceRecord.id` as an enterprise-storage ID and
  backwards-compatible source-token alias, not a public report citation.
- Changed source-token alias resolution to return the canonical RawSource token.
- Made project evidence/claim listing include records linked through
  `ReportVersion.evidence_ids` and `ReportVersion.claim_ids`, even when
  lifecycle dedupe preserved a record from an earlier project.
- Made report release gate evaluation use the exact report-version
  evidence/claim scope and report competitor IDs, avoiding stale project
  competitor links from older runs.

Why:

- Fixes the class of bugs where Reports or RunDetail showed missing sources
  after evidence dedupe/projection because one layer displayed RawSource tokens
  and another layer scoped by EvidenceRecord IDs or project ownership.
- Preserves a clean split: RawSource is the explainable citation contract;
  EvidenceRecord is the enterprise governance and dedupe contract.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/app/routers/enterprise.py backend/packages/enterprise/projection.py backend/packages/enterprise/store.py backend/packages/enterprise/postgres.py backend/packages/orchestrator/service.py backend/packages/sources/references.py backend/tests/unit/test_enterprise_store.py backend/tests/unit/test_source_reconciliation.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_source_reconciliation.py backend/tests/unit/test_enterprise_store.py::test_enterprise_store_replaces_reused_project_competitor_scope backend/tests/unit/test_enterprise_store.py::test_enterprise_store_project_lists_include_report_version_links backend/tests/unit/test_enterprise_store.py::test_report_release_gate_scope_uses_version_competitors_not_stale_project_links -q`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_enterprise_store.py -q`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_business_intel.py -q`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_run_service.py::test_release_gate_sync_creates_scoped_qa_repair_issue backend/tests/unit/test_run_service.py::test_release_gate_auto_redo_uses_existing_scoped_redo_for_real_runs backend/tests/unit/test_run_service.py::test_release_gate_auto_redo_is_disabled_for_demo_runs -q`
- `pnpm.cmd --dir frontend test -- src/features/report/sourceBundle.test.ts src/features/report/ReportView.test.ts`

## 2026-06-06 - Step 5: Pipeline Entry Point And Refactor Documentation

Commit: `ab7e46d docs(research): document clean pipeline refactor`

Scope:

- Added `research.pipeline.run_research_pipeline()` as the explicit branch-level
  composition of discover, capture, extract, evidence item assembly, evaluate,
  and repair stages.
- Exported `run_research_pipeline()` from `packages.research`.
- Added an end-to-end unit test with fake search and fetch providers.
- Added `docs/research_pipeline_refactor_summary_20260606.md` to record module
  boundaries, data contracts, ID conventions, collector integration, and the
  QA-warning/GAP-driven repair flow.

Why:

- Makes the clean architecture readable from one entry point instead of only
  scattered modules.
- Preserves a written interface contract for future collector, release-gate,
  and redo integration.
- Documents that pipeline lineage IDs and canonical report citation IDs have
  different responsibilities.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/agents/collectors backend/packages/research backend/tests/unit/test_research_pipeline.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q`

## 2026-06-07 - Step 12: Capture And Evidence Admission Hardening

Commit: this commit

Scope:

- Added generic capture-level rejection reasons for soft 404, unreadable text,
  short empty captures, and navigation-only pages.
- Made `CapturedPage.status` use `rejected` for fetches that technically
  returned but are not usable research material.
- Added `admit_evidence_items()` as the explicit field-level evidence admission
  boundary, using capture status, page quality, field quotes, and extraction
  confidence before accepting an `EvidenceItem`.
- Changed `run_research_pipeline()` so evaluation and repair are driven by
  admitted evidence, not only by extractor output.
- Improved pricing extractor quotes for derived `pricing_model_type` fields so
  semantic labels like `api_usage_based` bind back to real page text.
- Added tests for soft-404 capture rejection and field quote admission.

Why:

- Keeps Clean Research Pipeline focused on data quality before writer/release
  layers consume the result.
- Prevents pages that fetch successfully but contain no usable source material
  from becoming accepted evidence.
- Makes QA/GAP-driven repair respond to typed evidence admission failures
  instead of loose natural-language warnings.

Validation:

- `pytest backend/tests/unit/test_research_pipeline.py -q`

## 2026-06-07 - Step 13: Collector Adapter Narrowing

Commit: this commit

Scope:

- Routed `_collect_official_sources()` and homepage fallback collection through
  `run_research_pipeline()` with seed candidates instead of maintaining a
  second hand-written candidate/fetch/source loop in collector logic.
- Added explicit search and repair switches to the collector research-pipeline
  adapter so compatibility entry points can stay seed-only while the main
  collector branch keeps gap-driven repair.
- Removed unused collector-local search-result ranking and candidate-to-source
  helpers that duplicated `research.discovery` and `research.capture`.
- Kept `_source_from_search_result()` as a compatibility adapter for skill-tool
  and cross-competitor fallback paths that still need a single-result bridge.

Why:

- Moves collector closer to the intended Clean Research Pipeline role: build a
  `ResearchBrief`, call the pipeline, and translate accepted results into the
  existing `RawSource` run contract.
- Avoids two parallel discovery/capture implementations that could drift in
  candidate ranking, source identity, or fetch quality handling.
- Preserves existing unit-test behavior for official-source collection without
  triggering an unexpected repair round.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/agents/collectors backend/packages/research backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q`
