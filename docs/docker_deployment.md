# Docker Deployment

This project can run as a single Docker Compose stack:

```text
nginx -> frontend
      -> backend -> postgres
                 -> temporal
temporal-worker -> temporal/backend activities
```

## Requirements

- Docker Desktop or Docker Engine with Docker Compose v2.24.0 or newer.
- No local `.env` file is required for demo mode. The checked-in
  `.env.example` supplies safe defaults, and an optional root `.env` can
  override them for real API mode.

## First Deploy

```powershell
docker compose up -d
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

Create a root `.env` only when you need real providers:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set these values:

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
docker compose up -d --build

# Optional helper that creates .env for editing if it is missing
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
  seed/eval data, and Playwright Chromium for browser fetch fallback.
- `docker-compose.yml` loads `.env.example` first and then an optional `.env`.
  This makes `docker compose up -d` work in demo mode while still allowing
  local secret overrides.
- `docker-compose.yml` uses named volumes for Postgres, run data, and artifact
  data so deployment state is not committed to Git. The artifact volume mounts
  only `/app/data/artifacts`, leaving packaged seed data visible in the image.
- Postgres schema migration is owned by `EnterprisePostgresStore` on backend
  startup.
- Nginx proxies `/api/*` to the backend and the rest of the site to the
  frontend container.
