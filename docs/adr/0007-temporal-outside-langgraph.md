# ADR-0007: Temporal Outside LangGraph

Status: Accepted

## Context

Temporal is strong at long-running business workflows, retries, schedules,
approval waits, and operational recovery. LangGraph is strong at single-run
agent reasoning graphs.

## Decision

Temporal wraps LangGraph later as an outer workflow layer. It does not replace
the inner LangGraph agent DAG.

## Consequences

Phase 1-3 stay LangGraph-first. Phase 4 introduces a thin
`CompetitiveIntelWorkflow` that calls the existing graph as an activity, with
idempotent evidence, claim, and report writes.

The Phase 4 worker registers exactly one outer workflow first:

- `CompetitiveIntelWorkflow`
- `create_competitive_intel_run`
- `run_competitive_intel_langgraph`
- `load_competitive_intel_projection`

This keeps Temporal responsible for workflow durability and retry boundaries,
while `RunService` and LangGraph remain responsible for planner, collector,
analyst, comparator, QA, redo, and HITL behavior inside a single run.

The first API integration point is `POST /api/workflows/competitive-intel`,
which submits the same request shape as direct run creation and returns `202`
with deterministic workflow/run IDs. Direct `/api/runs` remains available while
the Temporal path is verified.

`backend/scripts/smoke_temporal_server.py` is the strict Phase 4 server smoke:
it requires a running Temporal Server, starts an in-process worker, executes
`CompetitiveIntelWorkflow` on an isolated smoke task queue, and verifies the
resulting enterprise projection.
