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

Commit: `refactor(research): add extract evaluate repair stages`

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

Commit: pending

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

## 2026-06-06 - Step 6: Release Gate Repair Bridge

Commit: pending

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

## 2026-06-06 - Step 5: Pipeline Entry Point And Refactor Documentation

Commit: pending

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
