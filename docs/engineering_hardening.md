# Engineering Hardening Checklist

This project defaults to a local demo posture. Before exposing it outside a trusted developer
machine, apply this checklist.

## Authentication

- Set `AUTH_ENABLED=true`.
- Configure either `AUTH_TOKEN_SUBJECTS` or `AUTH_BEARER_TOKENS`.
- Prefer `AUTH_TOKEN_SUBJECTS` when multiple users or workspaces are needed:

```json
{
  "token-a": {"user_id": "analyst-1", "role": "analyst", "workspace_id": "workspace-a"},
  "token-b": {"user_id": "viewer-1", "role": "viewer", "workspace_id": "workspace-a"}
}
```

When authentication is enabled, backend user role and workspace are derived from the validated
token subject. `X-User-Id`, `X-User-Role`, and `X-Workspace-Id` are only a local demo fallback.

## Duplicate Clicks And Idempotency

- The new-run UI creates an `idempotency_key` and now guards against rapid repeated submit calls.
- API clients should always send a stable `idempotency_key` for create-run commands.
- Backend active duplicate detection reuses queued/running/interrupted runs for matching request
  fingerprints within `ACTIVE_RUN_DUPLICATE_WINDOW_SECONDS`.

## Crawl And Fetch Safety

- Basic evidence fetch and robots checks validate URL destinations with `SSRFGuard`.
- Redirects are checked hop by hop, and final destinations are revalidated to reduce DNS rebinding
  risk.
- Policy-blocked basic fetches do not fall back to the browser fetch path.
- Keep external crawl concurrency conservative until domain allowlists, robots behavior, and cost
  controls are reviewed for the target deployment.

## Load Testing

Install load-test dependencies:

```bash
pip install -e "backend[load]"
```

Smoke test:

```bash
locust -f backend/tests/load/locustfile.py --host http://127.0.0.1:8000 --users 10 --spawn-rate 2 --run-time 5m
```

Recommended order:

1. Read-only smoke: `/api/runtime`, `/api/runs`.
2. Demo create-run smoke with unique idempotency keys.
3. Soak test with realistic users and conservative spawn rates.
4. Real-mode test only after LLM/search/crawl budgets, rate limits, and cancellation behavior are
   configured.

Useful environment variables:

- `LOCUST_AUTH_TOKEN`: bearer token for authenticated environments.
- `LOCUST_WORKSPACE_ID`: workspace used by create-run payloads.
- `LOCUST_RUN_EXECUTION_MODE`: default `demo`; only use `real` deliberately.
- `LOCUST_CREATE_RUN_WEIGHT`: lower this to reduce write pressure.
