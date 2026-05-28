# ADR-0001: LangGraph Over CrewAI

Status: Accepted

## Context

The project needs deterministic, inspectable multi-agent orchestration with
fan-out/fan-in, scoped redo, HITL interrupts, checkpointing, and trace playback.

## Decision

Use LangGraph as the inner single-run agent graph. Do not replace it with CrewAI.

## Consequences

LangGraph remains the owner of agent DAG behavior. Higher-level workflow
durability is handled outside the graph later, through Temporal.
