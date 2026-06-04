# Identity Unification Log - 2026-06-04

## Objective

Unify production ID generation behind `packages.identity` instead of allowing
agents, routers, stores, workflows, and business-intel modules to create IDs
with local `uuid4`, `hashlib`, or formatted strings.

## Changes

- Added a broad identity contract in `backend/packages/identity/stable_ids.py`.
- Exported identity functions from `backend/packages/identity/__init__.py`.
- Converted run and UI idempotency generation to identity helpers.
- Converted LangGraph thread IDs for demo and scoped redo execution.
- Converted RawSource IDs in collectors, skill tools, survey/interview sources,
  seed corpus, online gap fill, demo sources, and source snapshots.
- Converted simulated survey respondent IDs.
- Converted ReportVersion IDs for normal projections and RAG gap-fill versions.
- Converted project, competitor, source registry, audit, artifact, memory,
  workflow, monitor, notification, trace, decision replay, evidence-gap,
  schema-suggestion, QA, release-gate, red-team, recommendation, KG edge, and
  retrieval chunk ID generation.
- Kept content hashes local where they represent integrity/dedupe hashes rather
  than object identity.

## Interface

New code must import ID helpers from `packages.identity`. The most common
interfaces are:

- `compute_raw_source_id(...)`
- `compute_evidence_id(...)`
- `compute_claim_id(...)`
- `compute_report_version_id(...)`
- `compute_gap_fill_report_version_id(...)`
- `compute_project_id(...)`
- `compute_competitor_id(...)`
- `compute_source_registry_id(...)`
- `compute_artifact_id(...)`
- `compute_workflow_id(...)`
- `compute_graph_thread_id(...)`
- `compute_run_id_for_idempotency_key(...)`
- `compute_survey_respondent_id(...)`
- `new_run_id()`
- `stable_prefixed_id(prefix, *parts, length=N)`
- `runtime_prefixed_id(prefix, length=N)`

## Follow-Up Guard

`backend/tests/unit/test_identity_contract.py` should be extended whenever a new
ID family is introduced. Production modules should not add local ID helper
functions unless they delegate to `packages.identity`.
