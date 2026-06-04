# Identity Contract

This project uses `packages.identity` as the only production entry point for
resource and event identifiers. Business modules may build content hashes for
dedupe or integrity checks, but they must not hand-roll persistent IDs with
`uuid4()`, `hashlib.sha256(...).hexdigest()[:N]`, or ad-hoc formatted strings.

## ID Families

| Family | Function | Stability | Format |
| --- | --- | --- | --- |
| Run | `new_run_id`, `compute_run_id_for_idempotency_key` | Runtime unique or idempotency-stable | `run-*` |
| Workflow | `compute_workflow_id`, `compute_workflow_idempotency_key` | Stable per workflow input | `<workflow-prefix>-*`, `workflow:*` idempotency keys |
| LangGraph thread | `compute_graph_thread_id` | Stable per run/purpose/scope | `graph-thread-*` |
| Raw source | `compute_raw_source_id` | Stable for same source type, competitor, dimension, URL/content | `raw-source-*` |
| Evidence | `compute_evidence_id` | Stable enterprise evidence identity | SHA-256 hex |
| Claim | `compute_claim_id` | Stable per evidence-backed claim | SHA-256 hex |
| Report version | `compute_report_version_id`, `compute_gap_fill_report_version_id` | Stable per version basis | `report-version-*` |
| Project | `compute_project_id` | Stable per workspace/topic/competitor set | `project-*` |
| Competitor | `compute_competitor_id` | Stable per workspace/name | `competitor-*` |
| Source registry | `compute_source_registry_id` | Stable per workspace/domain/source type | `source-registry-*` |
| Artifact | `compute_artifact_id` | Stable per stored artifact content | `artifact-*` |
| Survey respondent | `compute_survey_respondent_id` | Stable per run/competitor/dimension respondent slot | `survey-respondent-*` |
| Evidence gap | `compute_evidence_gap_id` | Stable per gap semantics | `evidence-gap-*` |
| Schema suggestion | `compute_schema_suggestion_id` | Stable per dimension/gap set | `schema-suggestion-*` |
| QA/release/red-team | `compute_business_qa_finding_id`, `compute_release_gate_issue_id`, `compute_red_team_finding_id` | Stable per finding semantics | typed prefixes |
| Recommendation | `compute_recommendation_id` | Stable per recommendation semantics | `recommendation-*` |
| Trace | `compute_trace_id`, `compute_otel_span_id`, `new_subagent_context_id` | Stable per run/span or runtime trace context | W3C-compatible hex, `<run>:<agent>:<subagent>:*` |
| Decision replay | `stable_prefixed_id("decision", ...)` | Stable per replay source | `decision-*` |
| Memory | `compute_feedback_id`, `compute_memory_candidate_id` | Stable per feedback/candidate semantics | `feedback-*`, `memory-*` |

## Source Identity Rules

`RawSource.id` is no longer a random collector-local string. Collectors, survey
evidence, online gap fill, seed corpus, and snapshots generate it with
`compute_raw_source_id`.

`EvidenceRecord.id` remains the enterprise-stable evidence identity generated
from canonical URL, content hash, competitor ID, and dimension. Reports should
prefer EvidenceRecord IDs for durable citations; RawSource IDs are preserved as
aliases through `source_reconciliation`.

Source-like objects have one source of truth:

- `RawSource.id` identifies collection-stage material.
- `EvidenceRecord.raw_source_id` references the matching `RawSource.id`.
- `EvidenceRecord.id` identifies the enterprise evidence projection.
- report `[source:...]` tokens are reconciled against both Evidence IDs and
  RawSource aliases before display, release gates, and gap fill.

## Allowed Non-ID Hashes

The following are content or vector hashes, not resource IDs:

- fetched page `content_hash`
- extracted fact `content_hash`
- embedding hash/vector buckets
- report body hash used for workflow state comparison
- model prompt/schema hashes

These may still use hashing locally because they describe content integrity, not
object identity.

## Interface Rule

When adding a new persisted resource, event, workflow, or cross-run reference:

1. Add or reuse a function in `packages.identity`.
2. Document the function and format in this file.
3. Add a unit test in `backend/tests/unit/test_identity_contract.py`.
4. Do not create IDs directly in routers, agents, workflows, stores, or
   business-intel modules.
