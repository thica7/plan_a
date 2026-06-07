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

## 2026-06-07 - Step 14: Single Search Result Adapter Unification

Commit: this commit

Scope:

- Changed `_source_from_search_result()` from a direct capture/RawSource builder
  into a single-candidate `run_research_pipeline()` adapter.
- Kept real-run behavior strict: a search result must pass capture, extraction,
  field admission, and RawSource quality checks before becoming verified
  evidence.
- Preserved demo-mode compatibility with an explicit
  `web_search_result` fallback when verified web evidence is not required.
- Removed the last collector-local direct use of `capture_candidate()` and
  `raw_source_from_capture()` from search-result collection.

Why:

- Ensures skill-tool fallback, cross-competitor fallback, and main collector
  paths share the same discovery/capture/extract/admit boundary.
- Prevents future drift where one collector path accepts a page that the Clean
  Research Pipeline would reject.
- Keeps demo behavior intentionally separate from real evidence admission.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/agents/collectors backend/packages/research backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q`

## 2026-06-07 - Step 15: Research Quality Metrics

Commit: this commit

Scope:

- Added pipeline metrics for rejected captures, failed captures, rejected
  evidence items, accepted evidence rate, field support rate, repairable gaps,
  and blocking gaps.
- Kept metrics inside `research.pipeline` so downstream collectors and release
  layers can observe data quality without duplicating evaluation logic.
- Added unit assertions that end-to-end research runs expose accepted evidence
  and field-support metrics.

Why:

- Makes Clean Research Pipeline measurable against the plan's success criteria:
  field support, capture health, gap pressure, and repair readiness.
- Gives future real-run review a data-side explanation before inspecting writer
  or release-gate behavior.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/research backend/tests/unit/test_research_pipeline.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py -q`

## 2026-06-07 - Step 16: Release Gate Repair Contract And Claim Admission

Commit: this commit

Scope:

- Enriched release-gate findings with competitor, dimension, claim, evidence,
  weakness type, required action, and acceptance rule metadata before they
  become `QualityGap` records.
- Added `RepairTask.required_action` so repair tasks can distinguish
  add-evidence, rewrite-claim, downgrade-claim, delete-claim, rewrite-report,
  rerun-scope, and human-review paths.
- Propagated claim/evidence IDs and required action into RedoScope rationale so
  trace and UI review show exactly what a release-gate repair is trying to fix.
- Added release-claim admission during enterprise projection: weak or synthetic
  evidence can remain as evidence/history, but claims without verified webpage
  support are marked `deprecated` and excluded from the report-version release
  claim scope.
- Kept release-gate-generated `release_gate.*` repair issues out of
  `run_qa_findings` metadata so final gate repair tasks do not recursively
  become run-level QA blockers on later projections.
- Changed unresolved run-level QA metadata from one aggregate release-gate
  blocker into per-finding release-gate issues that preserve original
  competitor, dimension, field path, redo scope, and rationale.
- Recorded release-claim admission counts and excluded-claim reasons in
  `ReportVersion.quality_metadata`.

Why:

- Fixes the gap where Clean Research Pipeline could report no branch gaps while
  Release Gate still blocked the report with generic claim-level redo scopes.
- Keeps synthetic survey/interview material available for research context
  without letting it become a publishable enterprise claim by default.
- Moves the system from "Release Gate only blocks" toward "Release Gate produces
  actionable repair or downgrade instructions."

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/research backend/packages/business_intel/release_gate.py backend/packages/enterprise/projection.py backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_enterprise_projection.py backend/tests/unit/test_business_intel.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_enterprise_projection.py backend/tests/unit/test_business_intel.py -q`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_run_service.py -q -k "release_gate"`

## 2026-06-07 - Step 17: Release Gate Severity Semantics And Homepage Scope

Commit: this commit

Scope:

- Changed Release Gate publish semantics so only blocker findings block release;
  warning-level run QA and BusinessQA findings remain visible as repair/caveat
  signals without forcing `completed_with_blockers`.
- Preserved original run-level QA severity when projecting
  `run_qa_findings_unresolved` into release-gate issues.
- Split BusinessQA summary issues into blocker, warning, and info variants so
  warning rules have a useful non-blocking meaning.
- Added report-version homepage verification snapshots to enterprise projection.
- Made Release Gate enrich scoped competitors from the report-version homepage
  snapshot before running BusinessQA, so homepage verification is evaluated
  against the frozen run/report scope instead of only mutable project records.

Why:

- Aligns the gate with the intended enterprise semantics: blockers require
  repair or human review; warnings become caveats, downgrade signals, or
  follow-up repair tasks.
- Removes false `homepage_verified` blockers when the run plan already verified
  competitor homepages but the scoped competitor records do not carry that
  metadata in a replay/test path.
- Allows a real run with clean source identity, verified evidence, and no hard
  QA blockers to pass while still exposing weak/single-source claims as
  actionable warnings.

Validation:

- Replayed `run-ab672db7a58e8e2a5d25a4f20650d124` through the new projection and
  release-gate logic: `status=pass`, `gate_blockers=0`, `gate_warns=16`,
  `excluded_claim_count=2`.
- `conda run -n bd-competiscope-v2 ruff check backend/packages/business_intel/release_gate.py backend/packages/enterprise/projection.py backend/tests/unit/test_business_intel.py backend/tests/unit/test_enterprise_projection.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_business_intel.py backend/tests/unit/test_enterprise_projection.py -q`

## 2026-06-07 - Step 18: Pass-With-Warnings Follow-Up Persistence

Commit: this commit

Scope:

- Kept `release_gate.*` warning findings visible in `RunDetail.qa_findings`
  even when Release Gate allows the report to pass.
- Left blocker behavior unchanged: blocker release-gate issues still trigger
  scoped redo and `completed_with_blockers`.
- Added `ReportVersion.quality_metadata.release_gate` with release status,
  readiness, issue summaries, actionable repair tasks, and redo scopes.
- Stored follow-up tasks for non-blocking warnings without triggering automatic
  redo when `gate.allowed=True`.

Why:

- After warning semantics were corrected, allowed-with-warnings runs still need
  visible caveats and follow-up repair tasks.
- Prevents a pass state from hiding weak/single-source claims that should be
  reviewed, downgraded, or strengthened later.
- Gives report history, decision replay, and UI surfaces a stable place to read
  release-gate follow-up work.

Validation:

- `conda run -n bd-competiscope-v2 ruff check backend/packages/orchestrator/service.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_run_service.py -q -k "release_gate"`

## 2026-06-07 - Step 19: Evidence Quote Quality Boundary

Commit: this commit

Scope:

- Added a shared research extraction quote-quality boundary for pricing,
  feature, and persona extractors.
- Removed first-page-text fallback quotes when no reliable business term is
  found, preventing navigation headers and generic page chrome from becoming
  EvidenceItems.
- Reused the same quote quality policy in evidence admission so extracted
  quotes and accepted evidence have one consistent standard.
- Changed Final QA report wording so warning-only runs render as
  `passed with warnings` instead of `blocked for review`.

Why:

- The latest real run had enough verified pages and no missing source tokens,
  but report quality was pulled down by noisy snippets such as navigation,
  install commands, and truncated page text.
- Release Gate and run status could pass with warnings while the report body
  still said blocked, creating an avoidable reviewer-facing contradiction.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/research/extraction/quality.py backend/packages/research/extraction/pricing.py backend/packages/research/extraction/feature.py backend/packages/research/extraction/persona.py backend/packages/research/evidence/admission.py backend/packages/agents/qa/logic.py backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py::test_final_qa_sync_replaces_stale_clean_report_claim backend/tests/unit/test_run_service.py::test_final_qa_sync_adds_rag_gap_fill_for_collector_warnings -q`

## 2026-06-07 - Step 20: Source Text To Claim Boundary

Commit: this commit

Scope:

- Added a shared `research.evidence.text` helper for source business snippets
  and deterministic claim text.
- Routed deterministic analyst fallback claims through the shared helper.
- Stopped no-clean-snippet sources from generating structured pricing,
  feature, or persona claims with source IDs.
- Routed writer source digests through the same helper and marked omitted
  snippets with `snippet_quality=omitted_no_clean_business_snippet`.

Why:

- After quote admission was tightened, downstream analyst and writer paths still
  had direct access to raw `RawSource.snippet` text.
- This made it possible for noisy page chrome to survive into deterministic
  claims or writer context even when extraction/admission had a cleaner policy.
- The new boundary keeps source text handling consistent across collection,
  claim fallback, and report generation.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/research/evidence/text.py backend/packages/research/evidence/__init__.py backend/packages/agents/analysts/logic.py backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py -q -k "deterministic_structured_knowledge_payload or deterministic_payload_does_not_claim_from_noisy_snippet or writer_source_digest_omits_noisy_snippet or deterministic_feature_payload or deterministic_pricing_payload or structured_pricing_payload or structured_feature_payload"`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_research_pipeline.py -q`

## 2026-06-07 - Step 21: Text Quality QA Gate

Commit: this commit

Scope:

- Split explicit text-noise detection from strict source quote validation so
  report and claim text can be checked without requiring dimension keywords.
- Added `text_quality` as a first-class `QCIssue.detected_by` category.
- Added final QA checks for noisy report lines and noisy structured claim text.
- Routed report text quality failures to `writer_only` redo and structured
  claim text failures to targeted `analyst` redo.

Why:

- Cleaner source snippets and deterministic claim helpers reduce noise, but the
  enterprise QA layer still needs to catch any remaining navigation chrome,
  install-command fragments, encoding artifacts, or truncated webpage text that
  leaks into publishable report or claim text.
- Making this a QA category keeps it visible in trace/replay/release review
  instead of hiding it under generic schema or citation failures.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/research/extraction/quality.py backend/packages/research/evidence/text.py backend/packages/research/evidence/__init__.py backend/packages/schema/models.py backend/packages/orchestrator/scoping.py backend/packages/agents/qa/logic.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py -q -k "qa_ or final_qa or phantom_citation or text_noise"`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_research_pipeline.py -q`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_graph_send.py -q`

## 2026-06-07 - Step 22: Normalized Business Fields

Commit: this commit

Scope:

- Added typed normalized pricing, feature, and persona field models to the
  Clean Research Pipeline result contract.
- Generated normalized business fields only from accepted EvidenceItems.
- Persisted per-source normalized fields through `RawSource.metadata`, so the
  source identity path and business-field path stay aligned.
- Routed analyst deterministic fallback and writer source context through the
  same normalized source summary boundary before falling back to raw snippets.

Why:

- The prior anti-garbage work removed noisy source text, but pricing, feature,
  and persona facts still depended on downstream text heuristics.
- Checkpoint 1 requires business report sections to consume stable fields such
  as model type, tier, price, feature slot, support level, persona segment, use
  case, and evidence quote.
- Keeping normalized fields on `ResearchResult` and `RawSource.metadata`
  prevents writer-only patching and gives analyst, writer, release review, and
  UI surfaces one shared source of truth.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/research backend/packages/schema/models.py backend/packages/agents/writer/logic.py backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_research_pipeline.py -q`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py -q`

## 2026-06-07 - Step 23: Release Gate Warning Repair Section

Commit: this commit

Scope:

- Added a release repair module that converts non-blocking Release Gate
  findings and RepairTasks into explicit report-section targets.
- Added deterministic report-section replacement for
  `## Release Gate Follow-up Repairs`, inserted before Final QA when present.
- Recorded warning repair metadata on ReportVersion quality metadata:
  before/after warning counts, target section, action, rationale, claim IDs,
  evidence IDs, and acceptance rule.
- Re-evaluated Release Gate after a warning-repair section rewrite when an
  enterprise store is available, then saved current issues/tasks/redo scopes.

Why:

- Release Gate warnings already produced follow-up tasks, but the report body
  did not explain why a warning was retained or what exact section/action would
  close it.
- Checkpoint 1 requires warning/follow-up findings to drive a targeted repair
  artifact instead of being hidden in metadata or generic QA warnings.
- The section replacement is idempotent, so repeated projection syncs do not
  append duplicate repair sections or create a warning loop.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/business_intel/release_repair.py backend/packages/orchestrator/service.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py -q -k "release_gate"`

## 2026-06-07 - Step 24: Matrix Field Truncation Cleanup

Commit: this commit

Scope:

- Changed persona comparison matrix list rendering to include complete
  use-case and pain-point items instead of truncating inside a field value.
- Changed generic matrix text compaction to truncate on word boundaries when a
  hard cap is still required.
- Added a regression test proving persona matrix cells preserve complete list
  items without ellipsis for normal-sized standardized fields.

Why:

- The fresh Checkpoint 1 real run passed the quality gate, but remaining warn
  findings included persona cells that appeared truncated mid-entry.
- That warning was partly self-inflicted by the comparator's compact display
  format, not only by source quality.
- Preserving complete structured fields keeps QA from flagging report/matrix
  artifacts caused by our own serialization layer.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/agents/comparator/logic.py backend/tests/unit/test_run_service.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py -q -k "comparison_matrix"`

## 2026-06-07 - Step 25: Checkpoint 1 Final Real-Run Audit

Commit: this commit

Scope:

- Ran a final fresh real quality audit with auto warning redo enabled.
- Preserved the final generated audit card under `docs/reports/`.
- Added a strict Checkpoint 1 acceptance report mapping the run metrics to the
  Checkpoint 1 acceptance checklist.
- Updated the master plan so the next active work is Checkpoint 2.

Fresh run:

- `run-ad9d5ddc52517a6005739ffc404df17f`
- Quality verdict: pass.
- Regression gate: pass.
- Raw sources: 32.
- Enterprise evidence: 32.
- Enterprise claims: 26.
- Verified source rate: 1.0.
- Citation validity rate: 1.0.
- QA blocker count: 0.

Remaining warnings:

- Persona evidence depth and field completeness.
- Pricing billing-cycle/usage-limit completeness.
- Feature source coverage for Cursor IDE/tool slots.

These are retained as non-blocking quality follow-ups and mapped to
Checkpoint 2 H3/H4/H6/H7 rather than treated as unfinished Checkpoint 1
source-identity or report-status work.

## 2026-06-07 - Step 26: Unified Quality Finding Contract

Commit: this commit

Scope:

- Added `QualityFinding` and `QualityFindingBundle` as the shared quality issue
  contract for Checkpoint 2.
- Added adapters for RuntimeQA `QCIssue`, BusinessQA/ReleaseGate
  `BusinessQAFinding`, EvidenceGap, RedTeam, ClaimValidator, Research
  `QualityGap`, and EvalOps regression-gate issues.
- Extended the enterprise `QualityAgentMatrix` and `QualityAgentMatrixEntry`
  schema with `findings` and `finding_ids` while preserving existing matrix
  scores, summaries, metadata, and `suggested_redos`.
- Wired `/enterprise/projects/{project_id}/quality-matrix` so BusinessQA,
  ClaimValidator, EvidenceGap, RedTeam, and ReleaseGate entries expose the same
  typed finding shape.

Why:

- Checkpoint 2 requires QA, RedTeam, EvidenceGap, ReleaseGate, ClaimValidator,
  and EvalOps to speak one issue language before Gap Fill, claim validation, and
  the quality matrix can close loops cleanly.
- The previous matrix showed agent-level counts, but not a unified per-finding
  contract with competitor, dimension, field path, evidence ids, claim ids,
  required action, acceptance rule, and redo scope.
- Keeping this as an adapter layer avoids forcing `QCIssue`, `QualityGap`, or
  ReleaseGate schemas to absorb each other's responsibilities.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/schema/quality.py backend/packages/quality backend/packages/schema/enterprise.py backend/packages/schema/__init__.py backend/app/routers/enterprise.py backend/tests/unit/test_quality_findings.py backend/tests/unit/test_enterprise_store.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_quality_findings.py -q`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py::test_enterprise_router_exposes_projection -q`

## 2026-06-07 - Step 27: Quality-Driven Gap Fill Closure

Commit: this commit

Scope:

- Added `QualityFinding -> EvidenceGapReport` and Research
  `QualityGap -> EvidenceGapReport` conversion helpers.
- Added `fill_quality_finding_gaps()` as a typed entry point from unified
  quality findings into existing Gap Fill.
- Extended Gap Fill result and metadata with retrieval providers, source
  candidate ids, captured page ids, admitted evidence ids, and per-gap
  resolved/unresolved status.
- Added online gap-fill source lineage metadata for source candidate id,
  captured page id, provider, capture status, and evidence admission status.
- Preserved the existing local RAG and online gap-fill flow instead of
  introducing a second repair mechanism.

Why:

- Checkpoint 2 H4 requires gap repair to be driven by typed quality findings
  and to record enough retrieval/admission detail for trace, decision replay,
  and release review.
- The previous Gap Fill path already tracked query, chunks, rerank scores, and
  draft report creation, but it did not expose a direct unified-finding input
  or explicit admitted-evidence/resolution metadata.
- Keeping this inside the existing RAG Gap Fill module avoids scattering
  repair orchestration back into collector or release-gate code.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/rag backend/packages/schema/enterprise.py backend/tests/unit/test_gap_retrieval.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_gap_retrieval.py -q`

## 2026-06-07 - Step 28: User Research Material Import

Commit: this commit

Scope:

- Added typed survey/interview/manual research import contracts:
  `UserResearchMaterial`, `UserResearchImportRequest`, and
  `UserResearchImportResult`.
- Added a dedicated survey importer that redacts imported text before creating
  `RawSource` and `SurveyEvidenceBundle` records.
- Added `RunService.import_user_research_materials()` and
  `POST /runs/{run_id}/user-research` so real research materials can be
  attached to an existing run without being mixed into collector code.
- Updated persona knowledge merging so repeated imports merge `source_ids`
  into existing persona claims and segments instead of duplicating or dropping
  claims.
- Preserved `RawSource.metadata` through enterprise projection and marked only
  imported real user research as release-claim evidence; simulated survey
  evidence remains synthetic.

Why:

- Checkpoint 2 H3 requires persona evidence to come from imported survey,
  interview, or transcript material, not only generated `survey_simulated`
  sources.
- The import path needs to be auditable and citable: the same source id must
  appear in `RawSource`, persona `KnowledgeClaim.source_ids`, enterprise
  `EvidenceRecord.raw_source_id`, report metadata, and trace output.
- Real imported materials may contain PII, so redaction must happen before
  source admission and before trace logging.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/schema/survey.py backend/packages/schema/__init__.py backend/packages/agents/survey backend/packages/orchestrator/service.py backend/app/routers/runs.py backend/packages/enterprise/projection.py backend/packages/enterprise/store.py backend/tests/unit/test_survey_interview_agent.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_survey_interview_agent.py -q`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_projection.py backend/tests/unit/test_enterprise_store.py backend/tests/unit/test_source_reconciliation.py -q`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_business_intel.py -q`

## 2026-06-07 - Step 29: High-Risk Claim Validation Status

Commit: this commit

Scope:

- Extended claim validation results with H6-specific risk fields:
  `validation_status`, `high_risk`, `risk_reasons`, `recommended_action`, and
  `rationale`.
- Added validation status counts and high-risk coverage counters to
  `ClaimValidationReport`.
- Added deterministic high-risk classification and conflicting-evidence
  detection while preserving the existing `status` field for release-gate
  compatibility.
- Included the new H6 fields in unified ClaimValidator `QualityFinding`
  metadata and quality decision events.
- Updated release-gate claim validation messages to show risk status and
  recommended action.

Why:

- Checkpoint 2 H6 requires high-risk claims to have explicit validation status,
  evidence support, rationale, and a route to repair, downgrade, delete, or
  human review.
- The previous ClaimValidator already had self-consistency scores and issue
  routing, but its status vocabulary was too coarse for high-score review.
- Keeping the legacy `status` avoids destabilizing existing release-gate and
  quality-matrix behavior while adding the clearer H6 layer.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/schema/enterprise.py backend/packages/business_intel/claim_validator.py backend/packages/business_intel/release_gate.py backend/packages/quality/findings.py backend/packages/orchestrator/service.py backend/tests/unit/test_business_intel.py backend/tests/unit/test_quality_findings.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_business_intel.py backend/tests/unit/test_quality_findings.py -q`

## 2026-06-07 - Step 30: Quality Matrix Finding Groups

Commit: this commit

Scope:

- Added `QualityFindingGroup` to the enterprise schema and exposed matrix-level
  `groups`.
- Grouped unified quality findings by competitor, dimension, source agent,
  severity, and required action.
- Kept source-agent groups visible for every quality matrix entry so passing
  projects still show the complete agent review surface.
- Added tests for H7 grouping axes and the quality matrix router response.

Why:

- Checkpoint 2 H7 requires QA, RedTeam, EvidenceGap, ReleaseGate, and
  ClaimValidator outputs to be visible through one schema and reviewable by
  meaningful business axes.
- Keeping groups derived from `QualityFinding` avoids another parallel issue
  model and keeps RedoScope/source/claim links intact.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/app/routers/enterprise.py backend/packages/schema/enterprise.py backend/packages/schema/__init__.py backend/tests/unit/test_enterprise_store.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py::test_quality_finding_groups_cover_h7_axes backend/tests/unit/test_enterprise_store.py::test_enterprise_router_exposes_projection -q`

## 2026-06-07 - Step 31: Checkpoint 2 Quality Metrics

Commit: this commit

Scope:

- Extended run quality comparison with Checkpoint 2 H9 metrics:
  `gap_resolution_rate`, `field_support_rate`, `validated_claim_rate`, and
  `warning_count`.
- Kept `/runs/{run_id}/quality-comparison` and `/evals/enterprise` as the
  regression-gate surfaces instead of adding a duplicate EvalOps endpoint.
- Updated regression detection to use normalized score deltas, which correctly
  handles lower-is-better metrics such as QA blockers and warnings.
- Added field-support regression coverage to complement existing citation
  validity and blocker-count gate tests.

Why:

- Checkpoint 2 needs baseline/current numbers for the evidence repair loop,
  field coverage, claim validation, and warning count, not only source/citation
  metrics.
- Exposing these as ordinary `RunQualityMetric` records keeps backend,
  frontend, scripts, and EvalOps consumers on the same schema.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/business_intel/report_quality.py backend/tests/unit/test_report_quality.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_report_quality.py backend/tests/unit/test_evalops.py -q`

## 2026-06-07 - Step 32: Checkpoint 2 Warning Action Closure

Commit: `6417811 fix(eval): explain checkpoint warning actions`

Scope:

- Fixed `warning_count` so release-gate warnings synchronized into
  `qa_findings` are not counted a second time from release-gate quality
  metadata.
- Updated the real-run comparison card to render all quality metrics instead
  of hiding later Checkpoint 2 metrics behind a 16-row limit.
- Added a Retained Warning Actions section to the comparison report. Each
  retained warning is converted through the unified `QualityFinding` adapter
  and shown with a typed reason code, typed required action, acceptance rule,
  and next action.
- Added tests for release-gate warning de-duplication and retained warning
  action rendering.

Why:

- The final Checkpoint 2 acceptance rule allows retained warnings only when
  every warning has an explicit typed unresolved reason and next action.
- The previous comparison card showed natural-language QA diagnostics but did
  not prove that the warnings were connected to the unified H7 quality schema.
- The previous warning metric double-counted release-gate warnings after they
  were synchronized into `qa_findings`, making the final comparison look worse
  than the actual retained-warning set.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/business_intel/report_quality.py backend/scripts/compare_real_run_quality.py backend/tests/unit/test_report_quality.py backend/tests/unit/test_compare_real_run_quality_script.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_report_quality.py backend/tests/unit/test_compare_real_run_quality_script.py -q`

## 2026-06-07 - Step 33: Release-Gate Warning Wrapper De-Dupe

Commit: `a25332d fix(eval): dedupe release gate warning wrappers`

Scope:

- Tightened warning-count semantics so release-gate
  `run_qa_findings_unresolved` wrappers are not counted as separate warnings
  when the original runtime QA warning is already retained.
- Kept release-gate-only findings, especially claim-validation follow-ups, in
  the retained warning count and action table.
- Updated the real-run comparison report so Retained Warning Actions does not
  duplicate release-gate wrappers for the same original QA finding.

Why:

- The final Checkpoint 2 acceptance should measure unique retained quality
  issues, not both an original runtime warning and the release gate wrapper
  that reports the same unresolved warning.
- This lets `warning_count` represent the real follow-up workload while still
  preserving the stricter release-gate and claim-validation checks.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/business_intel/report_quality.py backend/scripts/compare_real_run_quality.py backend/tests/unit/test_report_quality.py backend/tests/unit/test_compare_real_run_quality_script.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_report_quality.py backend/tests/unit/test_compare_real_run_quality_script.py -q`

## 2026-06-07 - Step 34: Checkpoint 2 Final Real-Run Acceptance

Commit: this commit

Scope:

- Ran a fresh real-mode acceptance comparison after the Checkpoint 2 H3/H4/H6/H7/H9
  implementation steps.
- Recorded the result in
  `docs/reports/checkpoint2_real_run_acceptance_20260607.md`.
- Updated `docs/checkpoint2_execution_plan.md` with the final run id, score,
  gate result, metrics, warning-count branch, and verification commands.

Final accepted run:

- Run ID: `run-7b96eddb0b1a7613a9d5074bb5443fb6`
- Status: `completed`
- Quality verdict: `pass`
- Regression gate: `pass`
- Target score: 95
- Baseline score: 76
- Delta score: +19
- Citation validity rate: 1.0
- Verified source rate: 1.0
- Real source rate: 1.0
- Field support rate: 1.0
- Validated claim rate: 1.0
- QA blocker count: 0
- Warning count: 13 versus baseline 18; accepted through the lower-warning
  branch. Every retained warning is also listed with a typed reason code,
  typed required action, and acceptance rule.

Validation:

- `conda run -n bd-competiscope-v2 python backend/scripts/compare_real_run_quality.py --topic "AI coding assistant enterprise buying comparison" --competitors Cursor "GitHub Copilot" --dimensions pricing feature persona --execution-mode real --format markdown --timeout-seconds 600 --output docs/reports/checkpoint2_real_run_acceptance_20260607.md`

## 2026-06-07 - Step 35: Approval-Gated Report Publishing

Commit: `0f80127 feat(reports): enforce approval gated publishing`

Scope:

- Added a report lifecycle helper that owns approval request, approval/rejection
  decision, publish metadata, ReleaseGate snapshots, and transition audit shape.
- Blocked plain report upsert from moving report versions into `in_review`,
  `approved`, `rejected`, or `published`; review decisions now go through the
  approval activity/workflow and publication goes through the publish endpoint.
- Required approval activities to move reports through `in_review` before
  approval or rejection, and kept ReleaseGate enforcement on approval and
  publish.
- Added approval/publish audit records with actor, status transition,
  approval workflow metadata, publication metadata, and ReleaseGate snapshot.
- Updated router and Temporal workflow tests so the enterprise path is
  draft -> in_review -> approved/rejected -> published instead of direct
  status mutation.

Why:

- Checkpoint 3 needs enterprise workflow control, not arbitrary status writes.
- Approval and publishing must be explainable during audit: who requested
  review, who approved or rejected, what gate result was used, and when the
  report was published.
- Blocking direct upsert keeps the product boundary clean and prevents bypassing
  ReleaseGate or human approval.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/enterprise/report_lifecycle.py backend/packages/enterprise/store.py backend/packages/enterprise/postgres.py backend/packages/workflows/activities.py backend/packages/workflows/report_approval.py backend/app/routers/enterprise.py backend/tests/unit/test_enterprise_store.py backend/tests/unit/test_temporal_workflows.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py::test_enterprise_router_exposes_projection backend/tests/unit/test_enterprise_store.py::test_enterprise_router_blocks_report_approval_status_when_gate_fails backend/tests/unit/test_enterprise_store.py::test_enterprise_router_blocks_direct_publish_status_without_approval backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_update_report_version_status backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_use_report_scope_not_stale_project_competitors backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_block_weak_report_version backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_can_reject_report_version -q`

## 2026-06-07 - Step 36: Audited Manual Report Revision Loop

Commit: `ce811d4 feat(reports): audit manual report revisions`

Scope:

- Added a report-version audit event for manual report revisions with source
  version, source status, editor, note, and line-diff summary.
- Captured manual report revision MemoryAgent feedback through the existing
  memory audit path so reviewer corrections are visible as audit-grade product
  events.
- Added a focused router test proving rejected reports can be revised into a
  new draft without overwriting the rejected version.
- Verified the revised draft cannot be directly approved or published; it must
  return through the approval workflow.
- Verified report diff uses the rejected source version as the base for the
  manual revision.

Why:

- Human correction is only enterprise-grade when it leaves a review trail:
  previous version, new draft, reviewer note, memory feedback, and audit log.
- The corrected draft should not weaken governance by becoming publishable
  without a fresh approval pass.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/app/routers/enterprise.py backend/tests/unit/test_enterprise_store.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py::test_enterprise_router_exposes_projection backend/tests/unit/test_enterprise_store.py::test_enterprise_router_blocks_report_approval_status_when_gate_fails backend/tests/unit/test_enterprise_store.py::test_enterprise_router_blocks_direct_publish_status_without_approval backend/tests/unit/test_enterprise_store.py::test_manual_report_revision_after_rejection_creates_audited_draft backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_update_report_version_status backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_use_report_scope_not_stale_project_competitors backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_block_weak_report_version backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_can_reject_report_version -q`

## 2026-06-07 - Step 37: Unified Artifact Contract For Research Materials

Commit: `dabf250 feat(artifacts): unify research artifact contract`

Scope:

- Promoted `report_version_id`, `retention_policy`, and
  `compliance_metadata` to first-class artifact contract fields.
- Added research artifact types for `survey_response`, `interview_record`, and
  `manual_transcript` so imported research materials are no longer stored as
  generic web snapshots.
- Propagated the new fields through local/external artifact storage,
  SourceSnapshot capture, EnterpriseStore, Postgres store, Postgres schema, API
  routes, report export, compliance export, and the project knowledge graph.
- Added route-level scope checks so artifact report-version linkage cannot
  cross workspace, project, or evidence boundaries.
- Extended H10 tests to cover web snapshots, imported survey/interview
  artifacts, report-version artifact lookup, KnowledgeGraph linkage, retention
  policy, and compliance metadata.

Why:

- Enterprise review needs artifact records that can be traced directly to the
  report version, source/evidence, retention rule, and compliance state.
- Keeping interview/survey/manual materials in the same artifact contract avoids
  a parallel user-research storage path.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/schema/enterprise.py backend/packages/artifacts/store.py backend/packages/enterprise/source_snapshots.py backend/packages/enterprise/store.py backend/packages/enterprise/postgres.py backend/packages/enterprise/knowledge_graph.py backend/app/routers/enterprise.py backend/app/routers/trace.py backend/tests/unit/test_artifacts.py backend/tests/unit/test_enterprise_schema.py backend/tests/unit/test_enterprise_postgres_schema.py backend/tests/unit/test_h10_governance.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_artifacts.py backend/tests/unit/test_enterprise_schema.py::test_artifact_schema_links_storage_to_evidence backend/tests/unit/test_enterprise_postgres_schema.py::test_phase5_artifact_schema_is_present backend/tests/unit/test_h10_governance.py::test_source_snapshot_assets_external_s3_pointer_and_source_registry backend/tests/unit/test_h10_governance.py::test_manual_survey_snapshot_creates_research_evidence backend/tests/unit/test_h10_governance.py::test_knowledge_graph_read_model_links_sources_claims_and_reports backend/tests/unit/test_h10_governance.py::test_h10_enterprise_routes_are_callable -q`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py::test_enterprise_router_exposes_projection -q`

## 2026-06-07 - Step 38: RBAC And Workspace Isolation Negative Coverage

Commit: this commit

Scope:

- Expanded enterprise router isolation tests from project-only coverage to
  project, report version, evidence search, artifact read/list/write, source
  registry, memory feedback, and audit logs.
- Proved workspace-scoped users from workspace A cannot read workspace B
  resources even when they know resource ids.
- Proved viewer cannot write project or artifact resources, reviewer can review
  evidence quality but cannot directly revise reports, analyst can create
  artifacts, and admin is still denied cross-workspace audit reads.

Why:

- Checkpoint 3 needs enterprise governance evidence, not just role tables and
  happy-path permissions.
- These tests make the current application-layer isolation boundary explicit
  while leaving live Postgres RLS integration verification as a later hardening
  step.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/tests/unit/test_enterprise_store.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py::test_enterprise_router_enforces_rbac_workspace_scope -q`
