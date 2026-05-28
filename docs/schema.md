# Knowledge Schema

Every competitor is normalized into `CompetitorKnowledge`.

Core schema sections:

- `feature_tree`: feature categories, nested feature nodes, and cited claims.
- `pricing_model`: pricing tiers, billing cycle, limits, and cited pricing notes.
- `user_personas`: persona segments, roles, company size, pain points, use cases, and cited claims.

Traceability rule:

- Every `KnowledgeClaim` must include at least one `source_ids` entry.
- QA treats missing source IDs or unknown source IDs as blocker issues.
- Downstream `ComparisonCell.source_ids` and report citations must reference existing `RawSource.id` values.

Compatibility rule:

- `CompetitorKB` remains as a legacy slice view for comparison and report rendering.
- `CompetitorKnowledge` is the canonical structured schema used for QA.

## Enterprise Evidence Quality

The enterprise evidence store uses one canonical quality label enum:

- `unreviewed`: collected evidence that has not been manually checked.
- `accepted`: evidence approved for claims, reports, scoring, and QA.
- `rejected`: evidence that should not support claims or reports.
- `stale`: evidence that was once useful but needs replacement or refresh.

These labels intentionally replace earlier draft wording such as `good`,
`outdated`, `pending_review`, and `discarded`.

## Phase 4 Prerequisite Fields

Runs now carry `idempotency_key` so a future Temporal activity can retry run
creation without creating duplicate durable records. UI-created runs use a
unique generated key; workflow-created runs should pass an explicit key.

Evidence records now carry lifecycle fields:

- `canonical_url`: normalized URL used with `content_hash`, competitor, and
  dimension to derive stable `evidence_id`.
- `first_seen_run_id`: the first run that persisted the evidence.
- `last_seen_run_id`: the latest run that observed the evidence.
- `seen_count`: the number of distinct runs that observed the evidence.

These fields are the required idempotency base before adding Temporal around
the LangGraph run.
