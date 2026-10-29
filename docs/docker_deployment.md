# 本机与内网演示部署

本轮按用户要求不在开发电脑上执行 Docker。以下容器命令供另一台部署电脑使用；代码单测、假 Redis 与假模型测试不能代替这些实机验收。

## 1. 部署电脑准备

- 安装 Docker Desktop，或 Docker Engine + Compose v2；启动 Engine，确认支持 `docker compose up --wait`。
- 安装 Python 3.11+，拉取当前代码。宿主不必安装后端和前端依赖，镜像会构建它们；首次构建需访问镜像仓库和依赖源。
- 从 `.env.example` 创建该电脑自己的 `.env`。先用 `DEMO_MODE=true` 验证部署；真实模型凭据只保存在本机，不复制进交付文档、截图或 Git。
- 修改默认 Postgres 密码。内网访问配置 `AUTH_ENABLED=true` 与有效 token 主体，给予所需角色和工作区。模型 API key 不能当登录 token。

```bash
# 这些检查只在部署电脑运行
python --version
docker version
docker compose version
# Mac/Linux：cp .env.example .env
# PowerShell：Copy-Item .env.example .env
```

现有 Compose 仍按单 API / 单运行 Worker 配置，容器部署尚未实机验收。新增可选同机执行协调，使用共享 SQLite 和 POSIX 文件锁；本机多进程验证不能替代容器卷、真实 Temporal 和多副本业务存储验收。尚未提供公网 TLS 或跨主机多主方案。

### 同机执行协调（显式启用）

API 与 Worker 必须使用相同开关、journal 路径和池配置，运行数据库及其旁边的锁目录必须位于同一台 POSIX 主机的同一实际文件系统。默认关闭，不自动修改现用 `.env`。以下容量仅为配置起点，并非真实服务容量承诺：

```dotenv
EXECUTION_CONTROL_ENABLED=true
EXECUTION_CONTROL_JOURNAL_PATH=runs/run_journal.db
EXECUTION_GLOBAL_RUNNING_LIMIT=2
EXECUTION_WORKSPACE_RUNNING_LIMIT=1
EXECUTION_GLOBAL_QUEUE_LIMIT=32
EXECUTION_WORKSPACE_QUEUE_LIMIT=8
EXECUTION_QUEUE_WAIT_SECONDS=60
LLM_MAX_CONCURRENCY=4
EXECUTION_MODEL_WAIT_SECONDS=30
```

本机 API 会直接使用指定 journal；另一台 Linux 部署电脑应统一设置为 `/app/runs/run_journal.db`，并确认 API／Worker 共用现有 `run-data:/app/runs` 卷。不要把同名但不同卷或不同主机上的文件视为共享协调。Windows 可继续使用旧演示入口；开启这项 POSIX 保护时会明确拒绝不支持的平台。

启用或调整配置前，停止本池全部执行进程并备份。已有池配置不一致会拒绝启动；当前没有在线改池容量或自动迁移工具，不能靠删除锁文件或手工修改表绕过校验。排队满返回 429／`Retry-After`；队列过期可见失败；路径、存储或池配置错误明确拒绝。工作区限流、运行准入、模型在途并发和每次运行的 token／费用预算分别执行。

活进程暂停不会被 TTL 强抢，退出后操作系统释放执行锁；新实例可按既有恢复接口显式接管。未知结果的外部请求仍可能已经付费或执行，不能保证 exactly-once。真实容器中的锁、SQLite 共享卷、进程退出恢复与 Redis owner 条件释放仍须在部署机单独验收；本轮不执行 Docker、不增加 Kafka。

## 2. 启动模式与端口

| 模式 | 编排配置 | 启动组件 |
| --- | --- | --- |
| `light` | LangGraph / Temporal 流量 0 | Nginx、前端、API、Postgres、Qdrant |
| `persistent` | Temporal / 流量 100 | 上述组件 + Temporal、Worker、Temporal UI |
| 追加 `--redis` | API / Worker 一致开启缓存与限流 | 额外启动内部 Redis |

Python 入口兼容 Mac、Linux、Windows；下列命令在仓库根目录执行。`--dry-run` 只输出计划，不读取真实 `.env`、不调用 Docker。其他命令由部署者明确执行。

```bash
python scripts/docker_deploy.py --mode light --redis --dry-run
python scripts/docker_deploy.py --mode light --redis --build
python scripts/docker_deploy.py --mode light --redis --check
```

需要 Temporal 时可使用独立项目；先在进程环境或 `.env` 错开下表各端口：

```bash
python scripts/docker_deploy.py --mode persistent --project plan-a-persistent --redis --build
```

缺省项目为 `plan-a-demo`。同项目从持久模式切到轻量模式前，需先保存并处理进行中的任务，明确停止该项目原 Temporal/Worker/UI；脚本不会自动停止它们。脚本拒绝归属其他目录的同名项目。保留的 `start.sh` / `docker_deploy.ps1` 默认进入 persistent；需要选择模式时使用上述 Python 入口。

| `.env` 或进程配置 | 默认值 | 用途 |
| --- | --- | --- |
| `APP_BIND` | `127.0.0.1:8080` | 应用与 API |
| `QDRANT_BIND` | `127.0.0.1:6333` | Qdrant HTTP |
| `POSTGRES_BIND` | `127.0.0.1:55432` | Postgres |
| `TEMPORAL_BIND` | `127.0.0.1:7233` | Temporal gRPC |
| `TEMPORAL_UI_BIND` | `127.0.0.1:8233` | Temporal UI |

进程环境优先于 `.env`；示例 `APP_BIND=127.0.0.1:9080`、`QDRANT_BIND=127.0.0.1:9333`。内网应用访问需追加 `--lan`，启动前检查解析后的 API 鉴权；其他依赖端口仍限定 loopback，Redis 不发布宿主端口。局域网 HTTP 仅用于可信内网演示；需要跨不可信网络时先补 TLS。不要公开 `docker compose config` 输出，它可能包含实际凭据。

`/api/livez` 只确认 API 进程响应；`/api/readyz` 验证 journal、企业存储、按配置所需的 Qdrant、Temporal 与 Redis，不调用模型。必需依赖失败返回 HTTP 503，只有可选缓存失效返回 200 / warn。就绪不等于 Worker 已完成任务，也不等于报告内容合格。Nginx 为 SSE 禁用缓冲并透传 `Last-Event-ID`。

Compose 依赖镜像使用明确版本标签；应用构建基镜像仍有 Python 3.11 / Node 20 等浮动 tag，Python 依赖也尚未全部锁定。当前未锁定镜像 digest，仍需在部署电脑确认架构、拉取及兼容性。禁止用容器启动成功替代应用验收。

## 3. 数据持久化与任务恢复

| 存储 | 内容 |
| --- | --- |
| `run-data` | run journal、图 checkpoint、KB SQLite、事件、追踪与偏好等 |
| `artifact-data` | 报告、来源与导出产物 |
| `postgres-data` | 企业数据、向量及持久模式 Temporal 数据库 |
| `qdrant_data` | 知识库向量索引 |
| Redis | 可丢弃缓存和短时限流计数；不作任务真值或备份来源 |

普通停止保留 volume；清理时不要使用 `down -v`。迁移不支持直接复制运行中 SQLite 文件。Postgres schema 由现有企业存储初始化；升级前先备份并在隔离项目恢复检查。

LangGraph 任务中断后，持有 `report:write` 权限的主体可调用 `POST /api/runs/{run_id}/recover`。接口校验已持久执行归属、运行/失败状态、原 checkpoint、当前真实模型策略和重复执行。人工等待保持等待，已完成、未知归属及限定重做不使用普通恢复；重启不会自动重放真实付费调用。SSE 客户端用最后收到的事件 ID 作为 `Last-Event-ID` 补读。

Temporal Activity 的中断重试使用同一 run/thread 图检查点。已经提交的阶段可跳过，未提交的中断节点可能重新调用模型；当前不保证外部副作用 exactly-once。普通业务失败仍记录失败，不自动重试为成功。

## 4. 备份、隔离恢复与重启演练

脚本默认仅输出计划。备份需要 `--execute --allow-stop`：核验容器/卷归属，暂停该项目原本运行的写入服务，导出 PostgreSQL 各数据库和三组文件卷，校验清单后在 finally 中启动原先暂停的服务。备份期间也需停止项目外部直连数据库的写入。备份目录含业务资料，应本地私密保存；Git 已忽略 `backups/`。

```bash
python scripts/demo_data.py backup --project plan-a-demo --directory backups/demo-01
python scripts/demo_data.py backup --project plan-a-demo --directory backups/demo-01 --execute --allow-stop
python scripts/demo_data.py restore --project plan-a-demo --target-project plan-a-drill-01 --directory backups/demo-01
python scripts/demo_data.py restore --project plan-a-demo --target-project plan-a-drill-01 --directory backups/demo-01 --execute
```

恢复只允许全新 `plan-a-drill-*` 项目，校验 SHA256、文件名单和 tar 路径，拒绝覆盖已有目标卷。临时 Postgres 不发布服务端口；恢复后应用保持停止。先为演练错开所有宿主端口，再启动演练项目，例如在独立终端设置：

```text
APP_BIND=127.0.0.1:9080
QDRANT_BIND=127.0.0.1:9333
POSTGRES_BIND=127.0.0.1:65432
TEMPORAL_BIND=127.0.0.1:8234
TEMPORAL_UI_BIND=127.0.0.1:9233
```

Mac/Linux 用 `export NAME=value`，PowerShell 用 `$env:NAME='value'`，或准备演练专用 checkout 的 `.env`；配置后运行：

```bash
python scripts/docker_deploy.py --mode light --project plan-a-drill-01 --redis --build
# 在演练项目里创建一个 demo 任务，替换 DEMO_RUN_ID
python scripts/demo_data.py fault --project plan-a-drill-01 --run-id DEMO_RUN_ID
python scripts/demo_data.py fault --project plan-a-drill-01 --run-id DEMO_RUN_ID --execute
```

故障脚本只接受隔离项目与已存在 demo 任务，存在活跃 real 任务则拒绝。验证重启前后持久标记、任务与事件前缀哈希，等待/终态不得因重启变成完成。它是进程重启持久性检查，不证明 SIGKILL、停电、模型调用续跑或完整 Temporal 工作流完成。另需在演练中实际运行任务、在阶段间中断并核对恢复与预算。

## 5. Redis 验收与故障边界

缓存默认关闭。`--redis` 同时开启 API/Worker 的缓存和共享限流；组件可独立用 `REDIS_CACHE_ENABLED` / `REDIS_RATE_LIMIT_ENABLED` 配置，Compose 的统一开关 `DEMO_REDIS_ENABLED` 优先。应用使用惰性客户端、短超时与无自动重试。

- 缓存仅用于完整公共 HTTPS 正文，保留原采集时间和哈希；价格、URL 查询串、凭据、失败和摘要绕过缓存。
- 失效/损坏/断连按 miss；缓存不跳过来源核验、证据准入及 RAG 范围约束。
- 写入入口按可信鉴权主体限流，未鉴权使用服务器看到的 peer；反向代理后的匿名请求可能共享一个额度，内网应开启鉴权。达到阈值返回 429 / Retry-After；启用限流但 Redis 不可用返回 503。现有 token/费用预算继续执行。
- Redis 没有 AOF/RDB，重启会重置缓存和短时计数，不用于计费或持久配额。固定窗口限流在边界两侧允许短时突发；跨容器只针对同一 Redis 主节点保证原子计数。

部署电脑上先预览，再显式执行真实 Redis 检查：

```bash
docker compose -p plan-a-drill-01 exec -T backend python -m packages.infrastructure.redis_acceptance
docker compose -p plan-a-drill-01 exec -T backend python -m packages.infrastructure.redis_acceptance --execute
```

它只写随机命名空间两个有 TTL 的键，检查往返、1 秒过期、20 个并发 Lua 请求中允许 10 / 拒绝 10，不生成报告。若恰跨整点固定窗口，重新执行确认。

在隔离项目停止 Redis 后检查 `/api/readyz` 为 503，以及带有效授权的创建请求为 503；重新启动 Redis 后应恢复。测试缓存单独故障降级时，在演练 `.env` 设置 `DEMO_REDIS_ENABLED` 以外的单独配置会被 Compose 统一开关覆盖，需用明确的临时 Compose override 将两项设为 cache=true / limit=false，再重建演练 API/Worker，验证 readyz=200/warn、实际抓取仍可继续。不要对现用项目进行故障演练，也不要用真实付费任务验证限流。

回传脱敏的服务状态、上述 JSON、恢复/备份校验结果和失败日志摘要；不要回传 `.env`、token、完整 config 或原始数据库。Redis 实机 Lua/TTL、限流断连、Postgres/Qdrant/Temporal 容器验收在回传前均为待验收。

## 6. 知识库部署配置

API 与 Worker 使用同一 Compose 配置和 volume：`QDRANT_URL=http://qdrant:6333`、`KB_DB_PATH=/app/runs/knowledge_docker.db`。本地 `.env` 的宿主路径与 URL 被容器内配置覆盖。默认 vector collection 为 `knowledge_chunks`，index version 为 `v1`。

`KB_EMBEDDING_PROVIDER`、`KB_RERANKER_PROVIDER` 与模型配置继承 `.env`；`hash` 仅用于确定性离线测试。切换真实 embedding 模型时使用新 collection/version 并重建，不能混写向量。当前 backend 镜像未安装本地 BGE/精排 extras、未打包模型权重；需另行构建含 `bge-m3` / `reranker` extras 和模型目录挂载的镜像，或使用已配置的 HTTP provider，再验收实际语义检索。

旧 KB 文档保持 `pending`，按文档调用 `POST /api/knowledge/documents/{document_id}/reindex`，用 `GET /api/knowledge/providers` 核对 provider 与降级原因。项目 evidence 的 Postgres 向量表另用 `POST /api/enterprise/evidence/reindex?workspace_id=<workspace-id>` 重建。索引可用不代表报告前提归属与引用绑定已合格。

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
