# ADR-0011: Enterprise Skeleton First

Status: Accepted

## Context

The final plan moved enterprise data structure from a late migration into Phase
1 to avoid a run-centric demo that becomes expensive to productize.

## Decision

Build the enterprise skeleton first:

- Postgres schema as the durable target
- Workspace, Project, Competitor, Run, Evidence, Claim, ReportVersion, AuditLog
- stable IDs for evidence, claims, competitor sets, and report grouping
- enterprise store boundary with memory allowed only as an explicit local fallback

## Consequences

The default enterprise path is Postgres. Local tests may still use the memory
store explicitly, but product and demo paths should run through Postgres.
