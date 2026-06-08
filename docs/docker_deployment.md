# Docker Deployment

This project can run as a single Docker Compose stack:

```text
nginx -> frontend
      -> backend -> postgres
                 -> temporal
temporal-worker -> temporal/backend activities
```

## Requirements

- Docker Desktop or Docker Engine with Compose v2.
- A root `.env` file. Copy `.env.example` and fill real provider keys only when
  running real API mode.

## First Deploy

```powershell
Copy-Item .env.example .env
notepad .env
powershell -ExecutionPolicy Bypass -File scripts\docker_deploy.ps1
```

The app is served from:

```text
http://localhost:8080
```

Temporal UI is exposed locally at:

```text
http://127.0.0.1:8233
```

## Real API Mode

Set these values in `.env`:

```text
DEMO_MODE=false
ARK_API_KEY=...
ARK_MODEL=...
PPLX_API_KEY=...
BACKUP_LLM_API_KEY=...
BACKUP_LLM_MODEL=...
```

Do not commit `.env`. It is ignored by Git and Docker build context.

## Useful Commands

```powershell
# Build and start everything
powershell -ExecutionPolicy Bypass -File scripts\docker_deploy.ps1

# Rebuild images
powershell -ExecutionPolicy Bypass -File scripts\docker_deploy.ps1 -Build

# Follow logs
docker compose logs -f --tail=100

# Stop containers but keep volumes
docker compose down

# Stop and remove persistent volumes
docker compose down -v
```

## Deployment Notes

- `backend/Dockerfile` installs the backend, vendored `third_party/webfetch_v2`,
  and Playwright Chromium for browser fetch fallback.
- `docker-compose.yml` uses named volumes for Postgres, run data, and artifact
  data so deployment state is not committed to Git.
- Postgres schema migration is owned by `EnterprisePostgresStore` on backend
  startup.
- Nginx proxies `/api/*` to the backend and the rest of the site to the
  frontend container.

