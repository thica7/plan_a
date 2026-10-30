# 本机与内网演示部署

2026-10-30 交付继续按用户要求不在开发电脑上执行 Docker。以下容器命令供另一台部署电脑使用；代码单测、假 Redis 与假模型测试不能代替这些实机验收。第一期提交中心容器接线见第 7 节；本轮完整企业 PostgreSQL 15.18＋pgvector 0.8.7 的原生本机持久化工作台见第 8 节，两者的验收范围分别记录。

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

普通停止保留 volume；清理时不要使用 `down -v`。迁移不支持直接复制运行中 SQLite 文件。关闭提交中心时，旧企业存储保留原初始化行为；开启提交中心时企业存储不自动迁移，旧 enterprise schema 与必要授权须先由管理进程准备，再显式迁移提交中心。升级前先备份并在隔离项目恢复检查。

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

## 7. PostgreSQL 提交中心（第一期）

本节为另一台部署电脑的操作步骤，开发电脑未执行。`TASK_CENTER_ENABLED=false` 默认关闭；启用后数据库不可用、schema 漂移、owner 权限或池配置错误都明确失败，不回退到内存额度。HTTP 只检查提交中心迁移版本和权限，不执行其 DDL。

### 迁移 owner 与应用角色分开

1. 停止本池全部旧 writer／API／Worker／Relay，备份 PostgreSQL、run journal、图检查点和产物，确认项目外也没有旧路径写入。首次月桶从真实 `journal.load_run_summaries()` 导入历史次数；导入期间继续写旧 journal 会漏计。备份与恢复检查完成后才切换。
2. 管理员在目标数据库建立独立的迁移 owner，以及既有登录应用角色（例如 `task_center_app`）：应用角色须为 `NOSUPERUSER NOBYPASSRLS`，不拥有提交中心 schema，不直接或间接继承 owner。CLI `--app-role` 只授权已有角色，不建角色、数据库或密码。旧 enterprise schema（含部署组合所需 pgvector）与企业 DML 权限须由管理员先准备；本机未验证完整 PostgreSQL 17／pgvector 组合。
3. 在独立管理终端通过密钥管理设施注入 `TASK_CENTER_MIGRATION_DATABASE_URL`，仅迁移 CLI 使用。它不能保存在 API／Worker／Relay 的环境或 `env_file`。应用的 `TASK_CENTER_DATABASE_URL` 必须指向受限 app 角色；应用若使用 PostgreSQL 企业存储，`ENTERPRISE_DATABASE_URL` 也须是具有必要 DML 权限的受限应用连接。不要把普通 app 角色授为 owner 的成员。
4. 在装好后端依赖的仓库根目录先预览，再显式执行；命令不传 DSN 字面量：

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend \
  .venv/bin/python backend/scripts/migrate_task_center.py
# 仅在独立管理终端已安全注入 owner 连接后执行
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend \
  .venv/bin/python backend/scripts/migrate_task_center.py --execute --app-role task_center_app
unset TASK_CENTER_MIGRATION_DATABASE_URL
```

预览不连接数据库、不读取连接秘密；`--execute` 才迁移并授予必要 DML。应用权限检查会拒绝 owner／superuser／bypass-RLS 和 schema DDL 权限。PowerShell 使用独立管理进程并在结束时清除对应环境变量。

完整企业 PostgreSQL 部署还须包含新增的 `backend/db/postgres/002_run_delivery_status.sql`，由管理员通过企业存储的 `EnterprisePostgresStore.migrate()` 管理路径顺序应用 001＋002；提交中心迁移 CLI 不代替企业迁移。002 只扩展 run CHECK 以接纳 `completed_with_blockers`，不改变 QA／发布规则。应用 HTTP 不自动执行 DDL。本轮已验原生 PG15 的升级／重复迁移与受限 app 状态读写，尚未验 PG17 容器及真实模型 blocked Graph。

### 应用配置与 Relay

在独立应用环境中注入受限 DSN，并为 API／Worker／Relay 使用一致的 journal、工作目录和 POSIX 共享卷。下面仅列非秘密参数；当前演示先采用 LangGraph，真实模型、Temporal 另行验收：

```dotenv
TASK_CENTER_ENABLED=true
COMPETISCOPE_LOAD_ENV_FILES=0
TASK_CENTER_POOL_MIN_SIZE=1
TASK_CENTER_POOL_MAX_SIZE=8
TASK_CENTER_POOL_MAX_WAITING=128
TASK_CENTER_POOL_TIMEOUT_SECONDS=5
TASK_CENTER_STATEMENT_TIMEOUT_MS=3000
TASK_CENTER_LOCK_TIMEOUT_MS=1000
TASK_CENTER_DISPATCH_LEASE_SECONDS=30
TASK_CENTER_DISPATCH_MAX_ATTEMPTS=3
TASK_CENTER_DISPATCH_RETRY_SECONDS=1
ENTERPRISE_POOL_MAX_SIZE=4
ENTERPRISE_POOL_TIMEOUT_SECONDS=5
EXECUTION_CONTROL_ENABLED=true
EXECUTION_CONTROL_JOURNAL_PATH=runs/run_journal.db
RUN_ORCHESTRATION_BACKEND=langgraph
TEMPORAL_TRAFFIC_PERCENT=0
DEMO_MODE=true
```

关闭 env-file 自动加载时，需要的配置必须由进程环境或容器环境注入。容器中 journal 使用同一 `/app/runs/run_journal.db`；图检查点默认位于相同工作目录的 `runs/graph_checkpoints.db`。API、Worker、Relay 的同名目录必须挂载同一个实际 `run-data` 卷；副本还须共享可信企业元数据。Memory 企业元数据仅用于本次隔离演示，不能当跨进程生产共享元数据。

迁移完成后启动 API，再用相同应用环境启动独立 Relay；API 的新提交接口只持久化意图，不代替后台 Relay。原有入口可在其受控调用中领取当前单，但不能依赖这一路径清空新接口的 Outbox。

```bash
# 从仓库根目录运行；先预览，不构造运行依赖
PYTHONPATH=backend .venv/bin/python backend/scripts/run_submission_relay.py
PYTHONPATH=backend .venv/bin/python backend/scripts/run_submission_relay.py --execute --concurrency 4
```

当前 `backend/Dockerfile` 未复制 `backend/scripts`，现有 Compose 也未定义 Relay 服务。部署者须先通过镜像构建或只读挂载提供脚本，增加 Relay 服务／进程，并使其继承相同应用配置与共享卷。现有 Compose 的 `env_file: .env` 和企业 DSN 拼接仍可能把 PostgreSQL 管理凭据带进应用；启用前须用独立应用环境文件替代该继承，并显式覆盖企业应用 DSN。仅新增一个 `env_file` 可能仍合并旧文件，必须核对最终应用环境中 owner 秘密确已移除；不要把完整配置输出回传或入库。本期未修改或实测这些容器接线，不能只改开关便声称可用。

先以 demo 创建提交单、读取状态及账本，确认 Relay 派发及 run journal／检查点关联，再演练取消、幂等重放、数据库断连与恢复。`dispatched` 不表示报告完成，`/api/readyz` 成功也不表示 Relay 已消费或报告合格。旧 `client_request_sha=NULL` 数据不能推测已经丢失的原始 `auto` 请求，应使用已存请求载荷或原单 ID；详见[交付记录](optimization/2026-10-29-task-center-delivery.md)。

### 连接预算、额度及停机

异步提交池每进程默认上限 8、等待队列 128，池等待 5 秒、statement 3000ms、lock 1000ms；同步企业池每进程默认上限 4。总预算为各 API／Worker／Relay 的提交池加企业池，再加管理／观测连接；metadata 有界 offload 默认 4 槽，不是额外 4 个独立数据库连接。不要把每进程默认值当全机上限。

本次原生实测覆盖的是另一组配置：2 API×4＋2 Relay×4＋controller×4＝20，临时租户池 1 在 Relay 启动前关闭，PostgreSQL `max_connections=32`；Memory 元数据未启用企业 SQL 池。实测 API 池等待 1 秒、lock 700ms、statement 1500ms。生产应为同步企业池、真实 Temporal 数据库及管理连接另留预算，不能直接照搬 20 连接。具体机型、总内存和 CPU 容量未完整采集。

次数按 UTC 月桶计量，0 是真零额度，`monitor` 超额继续但审计。首次月桶导入真实历史 journal，排除提交中心已有 expected run ID 并仅导入一次；策略以 PostgreSQL 为准，Memory 重启不覆盖。额度 PATCH 在行锁内合并；PG 提交后 metadata 镜像失败会明确返回“任务次数策略已生效、metadata 同步失败”，排查时先读取当前策略，不要误当回滚。跨月取消返还原月份，已有发送意图／unknown 不退款；人工 retry 使用原 reserve 与业务身份。

正常停机顺序为停止入口接收、等待 Graph／Relay 与 metadata 工作、排空借用事务，最后关闭 driver 池；取消 metadata await 也要 join 正在运行的线程。让进程有完成清理的时间。恢复时核对租约 generation／token 与原业务身份；外部副作用属于至少一次投递，未知网络结果可能已付费或执行，不承诺 exactly-once。实际 Graph 仍受同机 SQLite／POSIX 执行归属约束，不能把 PostgreSQL 提交持久化当跨主机完整运行能力。

本机验收和复跑工具见[第一期交付记录](optimization/2026-10-29-task-center-delivery.md)及[脱敏结果](optimization/2026-10-29-task-center-results.json)。Docker、真实 Temporal／Redis、PostgreSQL 17 完整 pgvector 企业投影、跨主机均未验；不增加 Kafka，不训练模型。

## 8. 原生 PostgreSQL 本机持久化工作台（P0）

这是独立于上述 Compose 的原生本机入口。2026-10-30 实测环境为 macOS arm64、PostgreSQL **15.18（Homebrew）＋pgvector 0.8.7**，完整企业 public 19 表与提交中心三份迁移。启动器目前要求 PG15 工具及其兼容扩展；不会安装软件。先安装 Python 3.11+ 后端依赖、Node.js／pnpm 前端依赖，并把包含 `initdb`、`pg_ctl`、`postgres`、`pg_config` 的 PG15 工具目录加入 `PATH`。pgvector 必须为该 PG15 构建，不能把另一主版本的扩展安装视为已满足依赖。此入口使用 POSIX 进程／权限机制，未验 Windows。

### 初始化、启动、状态和停止

从仓库根目录执行，所有 action 默认只预览，不创建目录／进程／数据库连接：

```bash
WORKBENCH_PYTHON=.venv/bin/python
# 本次隔离 worktree 的可用解释器是 ../plan_a/.venv/bin/python；
# 在该 worktree 复用依赖时设 WORKBENCH_PYTHON=../plan_a/.venv/bin/python。
"$WORKBENCH_PYTHON" scripts/workbench_runtime.py init
"$WORKBENCH_PYTHON" scripts/workbench_runtime.py start
"$WORKBENCH_PYTHON" scripts/workbench_runtime.py status
"$WORKBENCH_PYTHON" scripts/workbench_runtime.py stop
# 真正执行，首次先 init，再 start
"$WORKBENCH_PYTHON" scripts/workbench_runtime.py init --execute
"$WORKBENCH_PYTHON" scripts/workbench_runtime.py start --execute
"$WORKBENCH_PYTHON" scripts/workbench_runtime.py status --execute
"$WORKBENCH_PYTHON" scripts/workbench_runtime.py stop --execute
```

默认 profile 为 `runs/local-workspace`；用 `--workspace-dir PATH` 选择独立目录，切勿指向旧业务目录。API 默认 `http://127.0.0.1:8010`，前端为 `http://127.0.0.1:5180`，提交中心位于 `/submissions`。可用 `--backend-port 8011 --frontend-port 5181` 选择端口，首次启动时明确传入，并在后续操作使用同一组参数。start 依次等待 PG、API readyz、Relay 真实就绪后启动 Vite；重复 start 复用同配置进程，冲突端口不会被自动杀掉。进程归属核 PID、UTC 创建时间、实际 argv、代码路径及 profile；身份不明时拒绝发信号。

机器重启后手动执行 start；本轮未安装 launchd／systemd 或其他开机自启。stop 先关闭本工作区服务，再停 PG，保留数据，没有 destroy 命令；退出失败或归属未知时保留诊断与依赖，先排查再重试，勿删除 marker、锁或手工改 PID。

### 信任边界与存储

PG 的 `listen_addresses` 为空，仅使用工作区派生的私有短 Unix socket；macOS 实测目录形如 `/private/tmp/pwpg-{uid}-{rootHash20}`。profile 根／PG data 与 socket 目录为 0700，私有记录为 0600。初始化 CLI 使用管理角色，应用角色 `plan_a_workspace_app` 为 NOSUPERUSER／NOBYPASSRLS／NOINHERIT，不具 owner 成员关系、DDL 或 TRUNCATE 权限。Unix socket 使用本地 trust；同一系统用户属于信任边界。API／前端只绑定 loopback，演示关闭 API 鉴权，不能把它作为内网或公网部署配置。

启动器为子进程构造受控环境，关闭根／frontend env 文件加载，不继承 provider key、owner DSN、Redis、Temporal、Qdrant HTTP；固定 `DEMO_MODE=true`、LangGraph、任务中心和同机执行控制。全局运行上限 2／工作区 1 是本轮本机配置，不是容量承诺。全局任务中心默认 false，旧入口与原 `.env` 不改。

| profile 内路径 | 内容 |
| --- | --- |
| `postgres/data` | 企业项目／run／报告版本、提交／Outbox／额度及 schema |
| `run_journal.db`、`graph_checkpoints.db` | API／Relay 共用的运行、事件与图检查点 |
| `knowledge.db`、`kb_cache.db` | 现有知识库与缓存 SQLite |
| `traces.db`、`preference_memory.db` | 追踪及偏好 SQLite |
| `artifacts/`、`vite-cache/` | 报告等文件产物、前端缓存 |
| `runtime/`、`postgres/` 下的私有记录／日志 | 归属、配置与诊断，勿公开上传 |

旧 Memory 演示及其他 profile 的数据不会自动迁入。此 profile 没有使用 Qdrant HTTP 或真实语义模型；不能把完整企业 PG schema 可用视为所有知识库／执行数据已迁 PG，或生产 RAG 已验收。

### 停机备份与恢复限制

备份前在页面确认当前任务状态，停止本 profile 的 API／Relay／前端及 PG，并以 `status --execute` 确认退出；也须确认没有其他进程直写此 profile。随后以私有目录完整备份 `runs/local-workspace`，包含 PG data、全部 SQLite、产物和归属记录，保留文件权限。不要只复制运行中的 SQLite／PG 文件，不要只备份提交表；备份含业务资料，应留在本机私有位置，勿进 Git。

本轮验证的是正常 stop／start 保留原路径数据，未完成备份恢复演练。归属标记含系统 UID、规范绝对路径和代码身份，不能承诺把备份移动到新路径或另一台机器后直接 start。原路径恢复也须在全停、保留当前副本并校验权限／版本后隔离验证；跨机应另行设计并验证 PostgreSQL 逻辑导出／导入及配套 SQLite／产物还原。不能直接把本机 PG15 data 目录拷入另一台 Docker／PG17 当迁移方案。

### 独立复跑与已验范围

以下验收器默认预览；`--execute` 仅自行分配随机私有临时 profile 和 loopback 端口，拒绝任意外部 DSN 或用户目录目标：

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
  "$WORKBENCH_PYTHON" backend/scripts/verify_persistent_workbench.py
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
  "$WORKBENCH_PYTHON" backend/scripts/verify_persistent_workbench.py --execute
```

已验真实 PG／app pool／API／Relay／demo Graph、提交与一次 reserve 的绑定、API／Relay 重启及 PG 整栈重启、同键 20 请求一单、最后额度竞争、取消只释放一次、无 Relay 时 pending 及恢复、断库 503 和原故障 key 恢复完成。恢复探针实际观察到 readyz 双依赖 200 后旧连接池仍短暂 POST 503，随后有界同键重试得到相同单；不承诺就绪后每个请求立即成功或恢复 SLA。成功临时 fixture 仅在所有自有进程正常退出证据齐全后删除；失败保留私有诊断。

浏览器已实际创建演示提交并打开原报告，正常全栈停启后重载原报告，提交／project／run／报告版本、一次 reserve、35 个事件和 19 个检查点快照一致。本轮独立全后端 9175 通过／1 跳过，全前端 340 项、Vite 隔离 8 项、标准工具临时生成比较及构建通过，Ruff 存量 4023／新增 0；首失败、修复及预发布扫描范围详见[本轮交付](optimization/2026-10-30-persistent-workbench-delivery.md)和[脱敏结果](optimization/2026-10-30-persistent-workbench-results.json)。提交前另核实际暂存范围与扫描，发布以 Git 历史为准。原始日志及截图只保存在 Git 忽略的本机 `data/artifacts/persistent-workbench-2026-10-30/`，公开文档不把它们当可下载资产。

Docker 完整 Relay／脚本／owner 环境隔离接线仍需按第 7 节补齐；本轮未执行容器、真实模型／Temporal／Redis、生产语义 RAG、跨主机或高并发容量验收。报告内容未重新验收，历史真实报告 0/4 结论不变；不增加 Kafka，不训练模型。

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
