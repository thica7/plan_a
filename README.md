# Competiscope v2

Competiscope v2 is a competitive intelligence workbench for running
source-grounded competitor research. It combines a FastAPI backend, a
React/Vite console, graph-driven agent orchestration, RAG/KB ingestion,
enterprise governance surfaces, and Docker-first deployment scaffolding.

The current main branch is focused on making competitive reports auditable:
collectors fetch and classify evidence before it reaches analysts, writers are
gated by structured source checks, and the UI exposes run, evidence, trace,
knowledge, and release-review surfaces for debugging real runs.

## What It Does

- Creates competitive intelligence runs from a topic, chosen competitors, and
  requested dimensions such as pricing, features, security, persona, market,
  integrations, and reviews.
- Plans graph-driven agent work across planner, collector, analyst, comparator,
  writer, QA, reflector, and redo paths.
- Collects web and KB evidence through trusted registries, web search, crawler
  sources, ReAct repair, and captured page fetches.
- Builds source-grounded reports with structured source tokens, evidence packs,
  release gates, and scoped redo loops.
- Maintains an enterprise workbench for evidence, claims, report versions,
  audit logs, source governance, compliance export, and runtime policy.
- Supports RAG/KB ingestion with crawl sources, document parsing, SimHash
  deduplication, retrieval presets, Qdrant vector support, and retrieval trace
  recording.

## Collector And Research Pipeline

The collector is no longer a simple "get N URLs" step. The current flow tries
to answer whether evidence can actually support the requested dimension.

- Discovery starts from competitor registry entries, homepage-derived canonical
  paths, web search results, KB hits, crawler sources, community signals, and
  targeted ReAct actions.
- Pricing collection protects official pricing, plans, billing, usage, and
  current plan-price support intents so canonical pricing candidates are not
  lost behind generic docs.
- Fetched pages are classified by source fitness, including
  `official_pricing`, `official_billing_docs`, `official_usage_limits`,
  `product_docs`, `changelog`, `community`, `third_party`, and
  `irrelevant_or_stale`.
- Pricing evidence must satisfy a coverage contract: an official pricing or
  billing source plus current plan-price support. Changelog and product docs
  can provide context, but they cannot be admitted as primary current pricing
  evidence.
- Candidate ledger entries track candidate status, origin, intent, fetch
  outcome, source fitness, and coverage diagnostics so failed runs can explain
  why a URL was selected, skipped, rejected, or sent into repair.
- ReAct is used as a targeted repair mechanism when source count is low,
  coverage fails, source fitness is wrong, or fetched evidence does not satisfy
  the dimension contract. Successful ReAct `fetch_page` calls are materialized
  into collector candidates even when the ReAct turn does not explicitly return
  finished sources.
- The default target is five verified sources per branch, configurable with
  `COLLECTOR_TARGET_VERIFIED_SOURCES_PER_BRANCH`.

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
- LangGraph-style orchestration with planner review, collector fan-out,
  comparator matrices, reflector gap detection, scoped redo, and writer repair.
- RAG/KB ingestion with crawl sources, document parsing, SimHash deduplication,
  retrieval presets, Qdrant vector support, and retrieval trace recording.
- Enterprise boundary for workspace, project, competitor, evidence, claim,
  report version, audit log, auth/RBAC, compliance, and Postgres storage.
- Temporal thin shell for retry-safe workflow wrapping and report approval
  signals.
- Observability coverage for local traces, decision replay, OpenTelemetry
  export, Langfuse mirroring, collector diagnostics, and compliance redaction.
- React + Vite + TypeScript console with run, history, crawl, search,
  knowledge, enterprise, evidence, competitor, report, trace, revision, and
  release-review views.
- Docker Compose stack with Nginx, frontend, backend, Qdrant, Postgres,
  Temporal, Temporal UI, and a Temporal worker.

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

## Reference Docs

- `docs/USER_GUIDE.md` for operator and developer workflows.
- `docs/architecture.md` and `docs/ARCHITECTURE_DIAGRAM.md` for system shape.
- `docs/RAG-KB/README.md` for RAG and knowledge-base notes.
- `docs/evidence_collection_contract.md` for source and evidence expectations.
- `docs/docker_deployment.md` for deployment details.
