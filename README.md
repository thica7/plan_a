# Competiscope v2

Plan A is a competitive intelligence workbench with a FastAPI backend, a
React/Vite console, graph-driven run orchestration, RAG/KB ingestion, enterprise
data boundaries, and Docker-first deployment scaffolding.

## Quick Start

Docker deployment:

```powershell
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\docker_deploy.ps1 -Build
```

Then open `http://localhost:8080`. See `docs/docker_deployment.md` for the
deployment contract and production notes.

Windows one-command development startup:

```powershell
.\scripts\dev_start.ps1
```

This starts local Postgres, Temporal, Temporal UI, the FastAPI backend, the
Temporal worker, and the Vite frontend. To stop or inspect the local stack:

```powershell
.\scripts\dev_stop.ps1
.\scripts\dev_status.ps1
```

The backend runs on `http://localhost:8000`. The frontend runs on
`http://localhost:5173` and proxies `/api` to the backend. Temporal exposes gRPC
on `127.0.0.1:7233` and UI on `http://localhost:8233` when the full stack is
running.

For the lighter RAG/KB demo path, Qdrant remains in `docker-compose.yml` and the
backend uses `QDRANT_URL=http://qdrant:6333` plus
`KB_DB_PATH=/app/runs/knowledge_docker.db`.

## Real API Mode

Create a root `.env` from `.env.example`, then set the provider keys you need:

```text
DEMO_MODE=false
ARK_API_KEY=your_key
ARK_MODEL=your_model_or_endpoint_id
PPLX_API_KEY=your_perplexity_key
BACKUP_LLM_API_KEY=your_backup_key
BACKUP_LLM_MODEL=your_backup_model
```

Leave Competitors on `Auto-discover` to provide only a topic; the planner will
search and select direct competitors before evidence collection. When
`PPLX_API_KEY` is present, collector subagents prefer official source registry
candidates, then Perplexity `web_search` results, fetch and hash returned pages,
and fall back to LLM-generated evidence candidates when search is unavailable.

## Current Slice

- FastAPI backend with run, stream, HITL, health, metrics, skills, runtime,
  trace, crawl, knowledge, KB, revision, enterprise, eval, and workflow routers.
- RAG/KB ingestion with crawl sources, document parsing, SimHash deduplication,
  retrieval presets, Qdrant vector support, and retrieval trace recording.
- Enterprise boundary for workspace, project, competitor, evidence, claim,
  report version, audit log, auth/RBAC, compliance, and Postgres storage.
- Temporal thin shell for retry-safe workflow wrapping and report approval
  signals.
- Observability coverage for local traces, decision replay, OpenTelemetry export,
  Langfuse mirroring, and compliance redaction.
- React + Vite + TypeScript console with run, history, crawl, search, knowledge,
  enterprise, evidence, competitor, report, trace, and revision views.
- Docker Compose stack with Nginx, frontend, backend, Qdrant, Postgres, Temporal,
  Temporal UI, and a Temporal worker.

## Useful Commands

```bash
make test-backend
make test-frontend
make sync-openapi
make secret-scan
make m0-check
```

Enterprise and workflow smoke checks:

```bash
docker compose up -d postgres temporal temporal-ui
make smoke-enterprise-postgres
make smoke-temporal-thin-shell
make smoke-temporal-server
```

## Project Layout

```text
backend/      FastAPI app, schema, agents, orchestration, RAG, enterprise code
frontend/     React/Vite console and generated OpenAPI client types
docs/         Architecture, deployment, ADR, contract, and eval notes
docker/       Nginx reverse proxy config
data/         Seed data and golden sets
eval/         RAG evaluation data
third_party/  Vendored runtime helpers, including webfetch_v2
```
