# Backend

FastAPI application for Competiscope v2.

Run locally with the project Conda environment:

```bash
conda run -n bd-competiscope-v2 uvicorn app.main:app --reload --port 8000 --app-dir backend
```

Foundation checks:

```bash
conda run -n bd-competiscope-v2 pytest backend/tests -q
conda run -n bd-competiscope-v2 python backend/scripts/smoke_minimal_run.py
conda run -n bd-competiscope-v2 python backend/scripts/smoke_llm.py
conda run -n bd-competiscope-v2 python backend/scripts/smoke_search.py
conda run -n bd-competiscope-v2 python backend/scripts/smoke_fetch.py
conda run -n bd-competiscope-v2 python backend/scripts/smoke_temporal_thin_shell.py
```

Enterprise store:

```bash
# default enterprise mode
ENTERPRISE_STORE_BACKEND=postgres
ENTERPRISE_DATABASE_URL=postgresql://competiscope:competiscope@127.0.0.1:55432/competiscope?connect_timeout=5

# explicit lightweight fallback
ENTERPRISE_STORE_BACKEND=memory
```

`EnterpriseMemoryStore` and `EnterprisePostgresStore` implement the same repository boundary,
but Postgres is the default enterprise path. Use memory only for isolated local tests.

Evidence quality labels are `unreviewed`, `accepted`, `rejected`, and `stale`.
Rejected and stale evidence are excluded from QA support and competitor scoring.

Phase 4 prerequisite fields are already in the enterprise store: runs persist an
`idempotency_key`, and evidence records track `canonical_url`,
`first_seen_run_id`, `last_seen_run_id`, and `seen_count` for retry-safe
Temporal wrapping later.

Temporal thin shell:

```bash
TEMPORAL_ADDRESS=127.0.0.1:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=competitive-intel
conda run -n bd-competiscope-v2 python backend/scripts/run_temporal_worker.py
```

`CompetitiveIntelWorkflow` calls the existing LangGraph run through activities;
it does not replace the inner graph.

The API route `POST /api/workflows/competitive-intel` submits the same payload
shape as `POST /api/runs`, returns `202 Accepted`, and reports the deterministic
workflow/run IDs without waiting for the long-running analysis to finish.

`ReportApprovalWorkflow` is the Phase 4 approval prototype. Start it with
`POST /api/workflows/report-approval`, then send manual approval decisions with
`POST /api/workflows/report-approval/{report_version_id}/approve` or
`POST /api/workflows/report-approval/{report_version_id}/reject`.

`ScheduledScanWorkflow` is the Phase 5 recurring-monitoring entry point. Start it
with `POST /api/workflows/scheduled-scan`; the workflow scans selected
workspace projects and writes an in-app notification retrievable from
`GET /api/enterprise/notifications`.

`MonitorWorkflow` is the Phase 5 continuous project monitor. Start it with
`POST /api/workflows/monitor`; each cycle runs the existing project analysis and
writes `anomaly_alert` notifications when report/evidence/claim signals change.

Phase 5 quota governance is active at the workspace boundary. Use
`GET /api/enterprise/workspaces/{workspace_id}/usage` for monthly run/token/cost
usage, `PATCH /api/enterprise/workspaces/{workspace_id}/quota` to adjust quota
policy, and `GET /api/enterprise/workspaces/{workspace_id}/quota-decision` to
see whether new runs are allowed. Exhausted workspaces emit `quota_warning`
notifications and `quota_enforcement=block` rejects new runs.

Real Temporal server smoke:

```bash
docker compose up -d postgres temporal temporal-ui
conda run -n bd-competiscope-v2 python backend/scripts/smoke_temporal_server.py
```

The server smoke defaults to an isolated per-run smoke task queue; set
`TEMPORAL_TASK_QUEUE` only when intentionally testing a named queue.
