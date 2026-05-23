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
