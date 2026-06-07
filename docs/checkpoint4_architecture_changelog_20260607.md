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
