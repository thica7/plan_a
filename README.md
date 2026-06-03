# Competiscope v2

Plan A implementation scaffold: graph-driven competitive analysis with schema-first agent outputs, skill-based dimensions, scoped QA redo, and a React operations console.

## Quick Start

```bash
docker compose up -d postgres
make dev-backend
make dev-frontend
```

Windows one-command real-run startup:

```powershell
.\scripts\dev_start.ps1
```

This starts local Postgres, Temporal, Temporal UI, the FastAPI backend, the
Temporal worker, and the Vite frontend. The backend and worker are launched
with the `bd-competiscope-v2` conda environment's `python.exe`; the frontend is
launched with `node.exe` and Vite. To stop or inspect the local stack:

```powershell
.\scripts\dev_stop.ps1
.\scripts\dev_status.ps1
```

The backend runs on `http://localhost:8000`. The frontend runs on `http://localhost:5173` and proxies `/api` to the backend.
Temporal dev services expose gRPC on `127.0.0.1:7233` and UI on `http://localhost:8233`
when the full compose stack is running.
The enterprise store is Postgres-first by default and uses the local Docker
database at `127.0.0.1:55432`. Set `ENTERPRISE_STORE_BACKEND=memory` only for an
explicit lightweight local fallback.

## Real API Test

Create a local `.env` in the repository root:

```bash
ARK_API_KEY=your_key
ARK_MODEL=your_model_or_endpoint_id
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
PPLX_API_KEY=your_perplexity_key
PPLX_BASE_URL=https://api.perplexity.ai
WEB_SEARCH_PROVIDER=perplexity
DEMO_MODE=false
MAX_ITERATIONS=2
AUTO_REDO_ENABLED=true
AUTO_REDO_WARN_ENABLED=false
HITL_ENABLED=false
HITL_TIMEOUT_SECONDS=60
COLLECTOR_REACT_ENABLED=true
COLLECTOR_REACT_MAX_TURNS=3
ANALYST_REACT_ENABLED=true
ANALYST_REACT_MAX_TURNS=3
ENTERPRISE_STORE_BACKEND=postgres
ENTERPRISE_DATABASE_URL=postgresql://competiscope:competiscope@127.0.0.1:55432/competiscope?connect_timeout=5
TEMPORAL_ADDRESS=127.0.0.1:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=competitive-intel
```

Then restart the backend with `make dev-backend`. The New Run screen will show whether the backend detected `ARK_API_KEY` and `ARK_MODEL`; choose `Real API` to send real chat completion calls through the backend. The API key is never sent from the browser.
Leave Competitors on `Auto-discover` to provide only a topic; the planner will search and select direct competitors before evidence collection.
When `PPLX_API_KEY` is present, collector subagents prefer Perplexity `web_search` results, fetch and hash the returned pages, and fall back to LLM-generated evidence candidates if search is unavailable.

M0 smoke checks:

```bash
make m0-check
make smoke-llm
make smoke-search
make smoke-fetch
```

`m0-check` is offline-safe except for local package execution. The real smoke commands require the matching keys in `.env`; they print only non-secret metadata.

If port `8000` is occupied during local development, start the backend on another port and point Vite at it:

```powershell
conda run -n bd-competiscope-v2 uvicorn app.main:app --port 8010 --app-dir backend
cd frontend
$env:VITE_API_TARGET="http://localhost:8010"
pnpm dev
```

Enterprise Postgres smoke:

```bash
docker compose up -d postgres
make smoke-enterprise-postgres
make smoke-temporal-thin-shell
```

The smoke script uses `postgresql://competiscope:competiscope@127.0.0.1:55432/competiscope?connect_timeout=5`
unless `ENTERPRISE_DATABASE_URL` is set.
For a real Temporal workflow smoke, start Temporal first and then run:

```bash
docker compose up -d postgres temporal temporal-ui
make smoke-temporal-server
```

The Temporal server smoke uses a unique default smoke task queue on each run so
old test workflows cannot pollute the result.

## Current Slice

- FastAPI backend with `/api/runs`, `/api/runs/{id}/stream`, `/api/skills`, `/api/runtime`, and `/api/runs/{id}/resume`
- M0 health and smoke endpoints: `/api/health`, `/api/smoke/llm`, `/api/smoke/search`, and `/api/smoke/fetch`
- Pydantic schema additions for `RedoScope`, `QCIssue`, `ReflectionRecord`, `RevisionRecord`, structured KB, comparison matrix, and run DTOs
- YAML skill registry for the first dimensions
- LangGraph real-run DAG and scoped redo graph with SQLite checkpoints at `runs/graph_checkpoints.db`
- Concurrent collector and analyst dimension fan-out inside the LangGraph nodes
- Collect join normalizes and deduplicates `RawSource` evidence, including structured `covered_competitors`
- Independent collector and analyst subagent contexts with context IDs in trace metadata
- Bounded collector ReAct runner (`web_search -> fetch_page -> finish`) with deterministic fallback
- Bounded analyst ReAct runner (`inspect_sources -> validate_citations -> finish`) with one-shot fallback
- Verified source handling for collector ReAct finish URLs, multi-competitor source attribution, and matrix citation consistency QA
- React + Vite + TypeScript frontend shell with New Run, Run Detail, KB/matrix, trace, and revision views
- SSE event types shared conceptually between backend and frontend
- Real-run trace spans for LLM/search/fetch calls with latency and token estimates
- QA consistency checks for comparison matrices plus bounded scoped redo iterations
- Automatic scoped redo loop for blocker QA findings, bounded by `MAX_ITERATIONS` and disabled when HITL is active; warn-level redo is opt-in with `AUTO_REDO_WARN_ENABLED` or the New Run switch
- Optional HITL interrupts for planner and QA review, enabled with `HITL_ENABLED=true`
- Enterprise data boundary for Workspace, Project, Competitor, Evidence, Claim, ReportVersion, and AuditLog, with memory and Postgres store implementations
- Phase 4 prerequisites for retry-safe workflow wrapping: run `idempotency_key` plus evidence `canonical_url`, first/last seen run IDs, and `seen_count`
- Phase 4 Temporal thin shell: `CompetitiveIntelWorkflow` wraps the existing LangGraph run as retry-safe activities; start it through `POST /api/workflows/competitive-intel`, run the worker with `make temporal-worker`, and verify a real server with `make smoke-temporal-server`
- Phase 4 approval prototype: `ReportApprovalWorkflow` supports report approval start plus manual approve/reject signals through `/api/workflows/report-approval`
- Docker and Makefile scaffolding for the planned demo path

## Project Layout

```text
backend/    FastAPI app, schema, skill registry, orchestration service
frontend/   React/Vite app, API client, run pages, live swimlane view
docs/       Architecture and API contract notes
docker/     nginx reverse proxy config
```
