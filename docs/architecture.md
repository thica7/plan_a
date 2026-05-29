# Architecture

Competiscope v2 follows Plan A with a LangGraph DAG, isolated subagent contexts,
schema-first outputs, scoped QA redo, and persistent observability.
Both real and demo execution modes use the same graph topology; demo mode swaps
LLM/search work for stable fixture node implementations.

## Runtime DAG

1. `planner` creates or verifies `AnalysisPlan` and can discover competitors for topic-only runs.
2. `planner_hitl` is an explicit graph checkpoint for plan review and uses LangGraph `interrupt()` with `Command(resume=...)`; if the reviewer does not respond before `HITL_TIMEOUT_SECONDS`, the backend auto-resumes with `accept`.
3. `collector_dispatch` emits structured collector tasks through LangGraph `Send` for `competitor x dimension`.
4. `collector` runs isolated ReAct branches through `packages/agents/collectors/logic.py` and skill tool helpers, then returns `RawSource[]`.
5. `collect_join` normalizes, deduplicates, and optionally adds cross-competitor sources.
6. `collect_qa` blocks on missing or invalid evidence and routes back to `collector_dispatch`.
7. `analyst_dispatch` emits structured analyst tasks through LangGraph `Send` for `competitor x slice`.
8. `analyst` runs citation-checked ReAct branches through `packages/agents/analysts/logic.py` and writes `CompetitorKnowledge`.
9. `analyst_join` merges KB slices for QA and downstream comparison.
10. `analyst_qa` blocks on missing structured claims or invalid citations and routes back to `analyst_dispatch`.
11. `comparator` creates `ComparisonMatrix`.
12. `reflector` creates self-found gaps before final QA.
13. `writer` renders a cited markdown report with deterministic fallback.
14. `qa` assigns `QCIssue.redo_scope`.
15. `qa_hitl` is an explicit graph checkpoint for force-pass or redo review. A redo decision returns a graph state with `RedoScope.kind`, and LangGraph conditional edges route back to `writer`, `comparator`, `analyst_dispatch`, `collector_dispatch`, or `planner`.

## Persistence

- `runs/run_journal.db`: run snapshots and SSE events.
- `runs/graph_checkpoints.db`: LangGraph checkpoints.
- `runs/kb_cache.db`: `(competitor, dimension, content_hash) -> CompetitorKnowledge slice`.
- `runs/traces.db`: trace spans, agent messages, and tool-call messages.

## Contracts

- Agent collaboration uses `AgentMessage` envelopes with `queued/consumed` status; tool activity is linked through `ToolCallMessage.source_message_id` when applicable.
- Phase 4 introduces a Temporal outer shell, not a replacement for LangGraph. `CompetitiveIntelWorkflow` creates an idempotent run, executes the existing LangGraph pipeline as an activity, and loads the persisted enterprise projection as the workflow result.
- `ReportApprovalWorkflow` is the Phase 4 approval prototype: it marks a report version `in_review`, waits for manual `approve` or `reject` signals, and persists the resulting report status without blocking an activity on a human wait.
- Phase 5 starts the recurring-monitoring layer with `ScheduledScanWorkflow`: it resolves workspace projects, runs project scans through the existing LangGraph activity boundary, aggregates per-project outcomes, and writes an in-app notification record for the workspace.
- `MonitorWorkflow` extends Phase 5 into continuous project monitoring: each cycle runs the existing project analysis, compares the new report snapshot against the prior report version, and records an `anomaly_alert` notification when the report body, evidence count, claim count, or scan status changes materially.
- Phase 5 quota governance derives monthly workspace run/token/cost usage from durable run metrics. `quota_enforcement=block` rejects new runs when usage is exhausted; warning/exceeded states are also surfaced through `quota_warning` notifications.
- HITL uses native LangGraph interrupt/resume semantics, not a service-level Future wait; manual post-run redo is separated onto `POST /runs/{run_id}/redo`.
- Knowledge claims use `KnowledgeClaim.source_ids`; QA checks unknown or missing citations.
- Core knowledge schemas are `FeatureTree`, `PricingModel`, and `UserPersonaModel`.
- Redo routing uses `RedoScope.kind` plus `target_subagent` and `target_competitor(s)`.
- Skill tools are physical modules under `packages/tools`: `web_search`, `robots`, `fetch_page`, `extract_facts`, `official_docs`, `review_site`, and `survey_simulator`.

## Backend Module Boundaries

- `packages/orchestrator/service.py`: lifecycle, events, persistence, trace plumbing, redo orchestration.
- `packages/orchestrator/audit.py`: revision/audit record construction and convergence metrics.
- `packages/orchestrator/graph.py`: LangGraph topology and `Send` fan-out.
- `packages/llm/json_extract.py`: JSON-object extraction for schema-first LLM responses.
- `packages/skills/base.py`: YAML skill loading primitives used by the skill registry.
- `packages/agents/planner/logic.py`: planning and competitor discovery.
- `packages/agents/collectors/logic.py`: collector ReAct, search/fetch/extract, collect join.
- `packages/agents/collectors/skill_tools.py`: skill allowlist tool execution for official docs, reviews, and interview-style records.
- `packages/agents/analysts/logic.py`: analyst ReAct, structured KB merge, KB cache integration.
- `packages/agents/analysts/citation_tools.py`: source inspection and citation validation tools.
- `packages/agents/comparator/logic.py`: `ComparisonMatrix` generation.
- `packages/agents/reflector/logic.py`: self-found coverage/confidence gaps.
- `packages/agents/writer/logic.py`: report generation, fallback, citation hardening.
- `packages/agents/qa/logic.py`: collect/analyst/final QA, redo-scope assignment support.
