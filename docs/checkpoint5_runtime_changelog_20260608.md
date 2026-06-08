# Checkpoint 5 Runtime Changelog

Last updated: 2026-06-08

## 2026-06-08 - C5.1 Runtime Command Layer

Implemented the first Runtime Command Layer slice.

Changed:

- Added `backend/packages/runtime/commands.py` with typed command/result
  contracts for create run, report revision, and report publication.
- Added `backend/packages/runtime/service.py` to own create-run orchestration
  routing, report manual revision, report publication, RBAC checks, release gate
  enforcement, memory feedback capture, and audit/replay correlation IDs.
- Changed `/api/runs` so Temporal cutover and direct LangGraph run creation are
  delegated through `RuntimeCommandService`.
- Changed report manual revision and report publish endpoints so protected
  report lifecycle transitions are delegated through `RuntimeCommandService`.
- Changed `get_runtime_command_service` into a composed FastAPI dependency so
  tests and runtime overrides receive the active store, memory, workflow, and
  run service dependencies.
- Updated architecture boundary tests so routers are guarded as thin command
  adapters and runtime owns orchestration decisions.

Validation:

- `ruff check` passed for runtime, affected routers, deps, and focused tests.
- Focused pytest passed for architecture boundaries, Temporal create-run
  headers, model-policy blocking, report publish approval gating, and manual
  report revision audit/memory behavior.

Next C5.1 follow-up:

- Move HITL resume/redo and report approval request/approve/reject/archive into
  runtime commands.
- Add command-level events to Decision Replay/SSE once the remaining commands
  are centralized.
