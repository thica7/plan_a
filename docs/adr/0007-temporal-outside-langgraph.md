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
