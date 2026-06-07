# Checkpoint 4 Architecture Changelog

## 2026-06-07 - Step 1: Identity Resolver And Report Scope Contract

Scope:

- Promoted source/evidence citation resolution into
  `backend/packages/identity/source_resolver.py`.
- Kept `backend/packages/sources/references.py` as a compatibility export layer
  so existing imports continue to work while identity becomes the canonical
  owner.
- Exported source resolver symbols from `packages.identity`.
- Preserved the canonical identity split:
  - reports cite `RawSource.id`;
  - enterprise report scope stores `EvidenceRecord.id`;
  - aliases resolve through one deterministic resolver boundary.
- Added source identity metadata to source-snapshot artifacts:
  `evidence_id`, `raw_source_id`, and accepted `source_tokens`.
- Added `ReportScope` and `build_report_scope()` so release decisions have a
  testable scope object rather than only a tuple of records.
- Added report-scope metadata explaining:
  - report-version-only release policy;
  - project history and memory as advisory context;
  - scoped competitors/evidence/claims;
  - excluded historical project competitors.
- Added report-scope metadata to ReleaseGate quality metadata when the run
  service attaches gate results.

Why:

- Checkpoint 4 is about preventing architecture drift, especially around source
  identity and project history.
- Source tokens, evidence records, artifacts, and release gates now point back
  to the same identity contract.
- ReleaseGate scope can now explain why stale project competitors or old
  evidence do not silently block the current report version.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/identity backend/packages/sources backend/packages/enterprise/source_snapshots.py backend/packages/enterprise/report_scope.py backend/packages/orchestrator/service.py backend/tests/unit/test_source_reconciliation.py backend/tests/unit/test_h10_governance.py backend/tests/unit/test_enterprise_store.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_source_reconciliation.py backend/tests/unit/test_h10_governance.py::test_source_snapshot_assets_external_s3_pointer_and_source_registry backend/tests/unit/test_h10_governance.py::test_manual_survey_snapshot_creates_research_evidence backend/tests/unit/test_enterprise_store.py::test_report_release_gate_scope_uses_version_competitors_not_stale_project_links -q`

## 2026-06-07 - Step 2: ReAct Collector Uses Research Pipeline Admission

Scope:

- Changed collector ReAct `finish` output from direct `RawSource` creation into
  `SourceCandidate` proposals.
- Routed ReAct-proposed URLs through Clean Research Pipeline capture,
  extraction, field-level admission, and RawSource assembly before they can
  enter `detail.raw_sources`.
- Applied the same boundary to the branch-level LLM fallback path: LLM output
  proposes seed candidates, and the research pipeline decides whether accepted
  evidence exists.
- Added explicit `ResearchBrief.include_trusted_sources` and
  `include_homepage_candidates` flags so seed-only admission really avoids
  registry/homepage discovery instead of relying on metadata.
- Removed the legacy `extract_facts` direct-admission trace from the ReAct
  finish path.
- Deduplicated evidence quote snippets so accepted field quotes do not produce
  repeated RawSource snippets when multiple fields cite the same sentence.

Why:

- ReAct can remain a model-driven candidate proposer, but Checkpoint 4 requires
  source discovery/capture/extraction/admission to stay inside the research
  pipeline boundary.
- This prevents a second collector-specific evidence admission path from
  drifting away from `SourceCandidate -> CapturedPage -> ExtractionResult ->
  EvidenceItem -> RawSource`.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/agents/collectors/logic.py backend/packages/research backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py::test_collector_react_runner_searches_fetches_and_finishes backend/tests/unit/test_run_service.py::test_collector_react_finish_fetches_uninspected_urls -q`

## 2026-06-07 - Step 3: Quality Finding Matrix Contract

Scope:

- Added `report_section` and `repairable` to the unified `QualityFinding`
  schema.
- Made `repairable` deterministic from `redo_scope` or actionable
  `required_action` values.
- Updated adapters for RuntimeQA, BusinessQA/ReleaseGate, EvidenceGap, RedTeam,
  ClaimValidator, ResearchPipeline `QualityGap`, and EvalOps to populate a
  reviewable report section.
- Added tests proving the main quality agents share one display/repair contract
  without collapsing their native schemas.

Why:

- C4.4 requires one product surface for quality review while keeping each agent's
  native finding semantics.
- Frontend quality matrix and release review can now rely on typed fields for
  section targeting and repairability instead of parsing finding messages.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/schema/quality.py backend/packages/quality backend/tests/unit/test_quality_findings.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_quality_findings.py backend/tests/unit/test_enterprise_store.py::test_quality_finding_groups_cover_h7_axes -q`
