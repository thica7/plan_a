# API Contract

All backend routes are mounted under `/api`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/runs` | Create a competitive analysis run |
| `GET` | `/runs` | List known runs |
| `GET` | `/runs/{run_id}` | Fetch run detail |
| `GET` | `/runs/{run_id}/stream` | Subscribe to run SSE events |
| `GET` | `/runs/{run_id}/trace` | Fetch persisted run event trace |
| `POST` | `/runs/{run_id}/resume` | Resume after a HITL interrupt |
| `POST` | `/runs/{run_id}/redo` | Start a manual scoped redo after QA findings |
| `POST` | `/workflows/competitive-intel` | Start the Phase 4 Temporal wrapper for a competitive analysis run |
| `GET` | `/skills` | List available analysis dimensions |
| `GET` | `/runtime` | Fetch non-secret runtime capability flags |
| `GET` | `/health` | Check config, skill registry, and SQLite readiness |
| `POST` | `/smoke/llm` | Real LLM smoke test using backend-held ARK credentials |
| `POST` | `/smoke/search` | Real Perplexity search smoke test |
| `POST` | `/smoke/fetch` | Real page fetch smoke test |

SSE event names are defined in `backend/app/events.py` and mirrored by `frontend/src/api/sse_types.ts`.
