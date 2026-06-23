# Competiscope v2

Competiscope v2 is a competitive intelligence workbench for running
source-grounded competitor research, evaluating evidence quality, and producing
auditable competitive reports.

It combines a FastAPI backend, a React/Vite console, graph-driven agent
orchestration, RAG/KB ingestion, enterprise governance surfaces, and
Docker-first deployment scaffolding.

## Core Capabilities

- Run competitive intelligence workflows from a topic, competitor set, and
  analysis dimensions such as pricing, features, security, persona, market,
  integrations, and reviews.
- Orchestrate planner, collector, analyst, comparator, writer, QA, reflector,
  and scoped redo stages through a graph-based pipeline.
- Collect evidence from trusted registries, web search, fetched web pages,
  crawler sources, community signals, manual inputs, and the knowledge base.
- Build source-grounded reports with evidence packs, structured source tokens,
  quality gates, release checks, and report versioning.
- Manage enterprise workspaces, projects, competitors, evidence, claims,
  reports, audit logs, governance policies, compliance exports, and RBAC.
- Ingest and retrieve knowledge through crawl sources, document parsers,
  SimHash deduplication, retrieval presets, Qdrant vector search, and retrieval
  trace logging.
- Inspect runs through frontend views for history, crawl, search, knowledge,
  evidence, reports, traces, revisions, governance, and release review.

## Architecture Overview

```text
frontend/        React, Vite, TypeScript console
backend/         FastAPI app, agents, orchestration, RAG, enterprise services
docs/            Architecture, deployment, contracts, ADRs, and user guides
docker/          Nginx reverse proxy config
data/            Seed data and golden sets
eval/            Evaluation datasets
third_party/     Vendored runtime helpers, including webfetch_v2
```

High-level runtime flow:

```text
New run
  -> planner
  -> collector branches
  -> analyst branches
  -> comparator
  -> writer
  -> QA / release gate
  -> scoped redo or final report
```

## Quick Start

Docker deployment:

```powershell
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\docker_deploy.ps1 -Build
```

Then open:

```text
http://localhost:8080
```

See `docs/docker_deployment.md` for deployment details.

## Local Development

Windows one-command startup:

```powershell
.\scripts\dev_start.ps1
```

This starts local Postgres, Temporal, Temporal UI, the FastAPI backend, the
Temporal worker, and the Vite frontend.

Useful commands:

```powershell
.\scripts\dev_status.ps1
.\scripts\dev_stop.ps1
```

Default local services:

```text
Backend:      http://localhost:8000
Frontend:     http://localhost:5173
Temporal UI:  http://localhost:8233
Temporal gRPC 127.0.0.1:7233
```

## Real API Mode

Create `.env` from `.env.example`, then configure the provider keys you need:

```text
DEMO_MODE=false
ARK_API_KEY=your_key
ARK_MODEL=your_model_or_endpoint_id
PPLX_API_KEY=your_perplexity_key
BACKUP_LLM_API_KEY=your_backup_key
BACKUP_LLM_MODEL=your_backup_model
```

When real API mode is enabled, the system can use live search, page fetching,
LLM-backed planning and writing, and evidence-grounded report generation.

## RAG / Knowledge Base

The project includes a knowledge ingestion and retrieval layer for grounding
reports in reusable evidence.

Supported capabilities include:

- crawl source ingestion
- document parsing
- chunking and SimHash deduplication
- Qdrant-backed vector retrieval
- retrieval presets
- retrieval trace recording
- KB-backed evidence reuse during runs

For the Docker KB path, Qdrant is included in `docker-compose.yml`, and the
backend uses:

```text
QDRANT_URL=http://qdrant:6333
KB_DB_PATH=/app/runs/knowledge_docker.db
```

## Evidence And Quality

Competiscope emphasizes auditable report generation:

- collected sources carry provenance and fetch metadata
- evidence is checked before it supports claims
- reports use structured source references
- QA and release gates surface blockers and warnings
- redo can be scoped to the failing stage instead of rerunning everything
- traces and audit logs are available for debugging run behavior

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

