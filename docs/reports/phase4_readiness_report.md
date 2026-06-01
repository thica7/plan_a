# Phase 4 Readiness Report

- Generated at: 2026-06-01T18:40:25.945132+00:00
- Require Temporal server: True
- Overall: PASS

| Check | Status | Detail |
|---|---:|---|
| temporal_cutover_config | ok | backend=temporal target_percent=100 reason=100% run traffic is routed through Temporal. |
| temporal_server_socket | ok | reachable address=127.0.0.1:7233 |
| postgres_schema_workspace_members | ok | marker=CREATE TABLE IF NOT EXISTS workspace_members |
| postgres_schema_source_registry | ok | marker=CREATE TABLE IF NOT EXISTS source_registry |
| postgres_schema_pgvector | ok | marker=CREATE EXTENSION IF NOT EXISTS vector |
| postgres_schema_evidence_embeddings | ok | marker=CREATE TABLE IF NOT EXISTS evidence_embeddings |
| postgres_schema_evidence_full_text | ok | marker=idx_evidence_search |
| rbac_same_workspace_read | ok | passed=True |
| rbac_cross_workspace_block | ok | passed=True |
| rbac_viewer_write_block | ok | passed=True |
| rbac_reviewer_quality_gate | ok | passed=True |
| workflow_create_idempotency | ok | run_id=run-79340cec9ff53e760d87faec228985f4 duplicate_run_id=run-79340cec9ff53e760d87faec228985f4 |
| langgraph_activity_idempotency | ok | status=completed event_count=25 |
| enterprise_projection | ok | report_version_id=report-run-79340cec9ff53e760d87faec228985f4-v1 evidence_count=2 claim_count=2 |
| source_registry_projection | ok | workspace_id=default-workspace source_count=1 |
| evidence_embedding_index | ok | workspace_id=default-workspace embedding_count=2 search_hit_count=2 |
| workspace_member_bootstrap | ok | workspace_id=default-workspace system_member_role=owner |

## Interpretation

This report validates the Phase 4 thin-shell contract: the same idempotency key produces the same run, rerunning the LangGraph activity does not append duplicate trace events, and the enterprise projection contains a report version with evidence and claims. It also checks the enterprise extension surface now expected at Phase 4 closeout: workspace members/RBAC, Source Registry, pgvector evidence embeddings, full-text evidence search, and the 100% Temporal run-entry cutover config.

Server reachability is reported separately because local development can run the deterministic activity checks without a Temporal Server. Use `--require-server` in release rehearsal to make server reachability a hard gate.
