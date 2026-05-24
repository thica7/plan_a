# Architecture

Competiscope v2 follows Plan A:

1. `planner` produces an `AnalysisPlan`.
2. `collector_dispatch` fans out by competitor and skill dimension.
3. Collector subagents run isolated ReAct loops and return structured `RawSource` values.
4. Analyst subagents merge slices into `CompetitorKB`.
5. `comparator` creates a cross-competitor `ComparisonMatrix`.
6. `reflector` creates self-found gaps before QA.
7. `writer` renders the report.
8. `qa` assigns `RedoScope` values so the orchestrator can retry only the smallest useful scope.

This repository currently contains the first vertical slice: contract, run lifecycle, SSE events, skill loading, and the frontend console.

