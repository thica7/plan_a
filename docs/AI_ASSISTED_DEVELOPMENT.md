# AI Assisted Development

This project uses AI assistance as an implementation accelerator, with the
repository tests, typed schemas, deterministic IDs, and human review as the
source of truth.

## Phase 1 Guardrails

- Keep enterprise records schema-first with Pydantic DTOs.
- Preserve stable IDs for evidence, claims, report versions, projects, and
  competitor sets across reruns.
- Store enterprise projections outside the run detail while keeping the legacy
  run detail during the transition.
- Record audit events for run creation, project and competitor upserts, evidence
  and claim persistence, report version persistence, and projection completion.
- Verify every Phase 1 change with backend tests plus at least one smoke script.

## Current Verification Commands

```bash
conda run -n bd-competiscope-v2 ruff check backend
conda run -n bd-competiscope-v2 pytest backend/tests -q
conda run -n bd-competiscope-v2 python backend/scripts/eval_baseline.py
conda run -n bd-competiscope-v2 python backend/scripts/smoke_enterprise_postgres.py
```

## Human Review Points

- Schema migrations must be reviewed before a Postgres environment is reused.
- New agent behavior must keep typed inputs and outputs at the AgentExecutor
  boundary.
- Any source collection change must preserve citation validity and robots
  compliance checks.

## Architecture Decisions

The required Phase 1 ADR set is recorded under [docs/adr](./adr/README.md):

- ADR-0001: LangGraph over CrewAI
- ADR-0002: five-level RedoScope
- ADR-0003: L1/L2/L3 competitive model
- ADR-0006: real git history
- ADR-0007: Temporal outside LangGraph
- ADR-0011: enterprise skeleton first
