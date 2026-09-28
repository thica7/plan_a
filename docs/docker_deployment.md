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

## 端口与知识库配置

宿主端口由根目录 `.env` 配置，容器内部端口保持固定：

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `APP_BIND` | `8080` | 应用与 API 入口 |
| `QDRANT_BIND` | `127.0.0.1:6333` | Qdrant HTTP |
| `POSTGRES_BIND` | `127.0.0.1:55432` | Postgres |
| `TEMPORAL_BIND` | `127.0.0.1:7233` | Temporal gRPC |
| `TEMPORAL_UI_BIND` | `127.0.0.1:8233` | Temporal UI |

例如 `APP_BIND=127.0.0.1:9080`、`QDRANT_BIND=127.0.0.1:9333`。
`scripts/start.sh`、`scripts/start.ps1`、`scripts/docker_deploy.ps1` 和
`make demo` 从 `docker compose config --format json` 读取实际地址，等待健康检查完成。
脚本需要 Python 3.11+ 和支持 `up --wait` 的 Compose v2；项目 `.venv` 优先使用，
可通过 `PYTHON_EXECUTABLE` 指定解释器。Mac/Linux 使用 `bash scripts/start.sh --build`。
仅查看配置地址可使用 `python scripts/docker_deploy.py --urls-only`。

backend 与 temporal-worker 共享 Compose 环境配置：

- `QDRANT_URL=http://qdrant:6333`。
- `KB_DB_PATH=/app/runs/knowledge_docker.db`，两者挂载同一 `run-data` volume。
- 两者均等待 Qdrant `/readyz` 健康检查通过后启动。
- `KB_EMBEDDING_PROVIDER`、`KB_RERANKER_PROVIDER`、模型与 HTTP provider 配置均继承同一份
  `.env`，Compose 不覆盖这些选择。`hash` 适用于确定性离线测试，生产语义检索需按检索评测选择 provider。
- `KB_VECTOR_COLLECTION` 默认 `knowledge_chunks`，`KB_INDEX_VERSION` 默认 `v1`。
  切换 embedding 模型时使用新的 collection/version 并重新建索引，避免混写不同模型向量。

升级已有数据后，旧 KB 文档会显示为 `pending`，不会被误认作已有可用向量。
逐份调用 `POST /api/knowledge/documents/{document_id}/reindex` 补建新模型向量；
`GET /api/knowledge/providers` 可检查实际 provider、降级原因和新 collection。
项目级 evidence 使用独立的 Postgres 向量表，切换模型后可调用
`POST /api/enterprise/evidence/reindex?workspace_id=<workspace-id>` 进行限定工作区重建。
重建完成前，该检索只返回匹配当前模型和维度的记录。

根目录 `.env` 的 `QDRANT_URL` 和 `KB_DB_PATH` 为本地开发值；Compose 明确覆盖为上述容器内地址。
更换宿主 Qdrant 端口后，本地开发的 `QDRANT_URL` 也应同步修改；容器内地址保持不变。

## 本地开发启停（Windows / Mac / Linux）

先安装后端到项目 `.venv`，并在 `frontend` 安装依赖。运行入口自动探测解释器和 Node.js，
支持 `PYTHON_EXECUTABLE` / `NODE_EXECUTABLE`，无需固定磁盘路径。
本地端口优先级为启动参数 → 进程环境 → 根目录 `.env` → 默认值。

```bash
# Mac/Linux；默认同时启动 Docker 依赖
bash scripts/dev_start.sh --backend-port 8100 --frontend-port 5180
bash scripts/dev_status.sh
bash scripts/dev_stop.sh

# 依赖服务由其他方式提供时
bash scripts/dev_start.sh --no-docker --backend-port 8100 --frontend-port 5180

# Makefile 入口；DEV_ARGS 透传运行参数
make dev DEV_ARGS="--no-docker --backend-port 8100 --frontend-port 5180"
make dev-status
make dev-stop
```

```powershell
scripts\dev_start.cmd -BackendPort 8100 -FrontendPort 5180 -NoDocker
scripts\dev_status.cmd
scripts\dev_stop.cmd
```

Vite 收到明确的 `--port`、`--strictPort`，API 代理同步指向实际 backend 端口。
直接从 `frontend` 运行 `pnpm dev` 时，Vite 也读取根目录 `.env` 的端口；可用 `VITE_API_TARGET`
指定其他 API 目标。统一 `dev_start` 入口始终将代理设置为其启动的 backend。

PID、创建时间标记、仓库路径和实际启动配置记录在 `logs/runtime/services.json`，日志位于同目录。
状态入口读取记录中的实际端口，即使之后修改 `.env` 也能正确定位已启动服务。
停止和重启只处理记录中的 PID，并再次校验创建时间与当前命令中的仓库服务路径。
端口占用者只用于诊断，启动报错后由使用者选择其他端口或自行停止该进程。
PID 被其他进程复用、归属无法验证或记录损坏时拒绝停止；人工确认后再整理记录。
旧版本脚本启动且没有记录的进程不会自动清理。

默认检测最近的 queued/running 任务并拒绝中断；`--force` / `-Force` 表示明确中断本项目任务。
如果无法读取当前任务状态，默认同样拒绝停止，以免静默中断正在运行的任务；
此时先检查后端与鉴权，确需停止本项目进程时再显式使用 `--force` / `-Force`。
`--no-health-check` / `-NoHealthCheck` 只跳过 HTTP readiness，输出为 `started`，不代表服务已就绪。
`--stop-docker` / `-StopDocker` 可在停止本地服务后停止该 Compose 项目的依赖容器。
`make dev-backend`、`make dev-frontend` 为手动前台入口，不加入后台 PID 记录；使用终端正常结束即可。

当前工程回归不调用收费 API，也不替代 Docker/Windows 真实服务验收。
