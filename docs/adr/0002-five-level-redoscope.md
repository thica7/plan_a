# ADR-0002: Five-Level RedoScope

Status: Accepted

## Context

QA findings must trigger focused regeneration without rerunning the whole
analysis when only a narrow branch is bad.

## Decision

Keep the five redo scopes:

- `writer_only`
- `comparator`
- `analyst`
- `collector`
- `full`

## Consequences

QA can route failures to the smallest useful repair unit. Phase 2 smoke verifies
all five scopes remain routable.
