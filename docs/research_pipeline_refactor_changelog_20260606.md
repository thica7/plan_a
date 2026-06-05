# Research Pipeline Refactor Changelog

## 2026-06-06 - Step 1: Typed Research Contracts

Commit: pending

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
