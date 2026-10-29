# PostgreSQL 提交中心第一期实施计划

> **For agentic workers:** 使用 subagent-driven-development，逐任务实施；每项一个实现者串行写代码，规格审查通过后再做质量审查。使用 test-driven-development；所有旧验收原件只读。用户已批准方案与实施，任务之间不重复请求批准。

**Goal:** 提供真实 PostgreSQL 支撑的持久提交、幂等、任务次数预占、取消／重试、可靠派发及可复跑的事务和并发验收。

**Architecture:** 新增 `packages.task_center`，PostgreSQL 管理提交单、额度与 Outbox；短事务完成业务写入，Relay 在事务外调用现有运行／Temporal 入口。同机 SQLite 运行日志和检查点保持原职责，提交与运行状态分别展示。新功能显式启用，关闭时保持现有接口行为。

**Tech Stack:** FastAPI、Psycopg 3 异步／同步连接池、PostgreSQL 15/17 兼容 SQL、现有 LangGraph／Temporal、pytest、HTTPX、Uvicorn。

基线 `265bdc84f27567706e990d6a901282e34bf40b84`，复用现有 linked worktree 和 `codex/pastoral-desktop`。范围依据见[已批准方案](2026-10-29-postgres-backend-proposal.md)。本机有 PostgreSQL 15.18 原生工具，无 pgvector；新增迁移只依赖标准关系型 PostgreSQL。Docker／真实 Temporal 服务组合留部署机；Kafka、报告协作第二期和模型训练不在本期。

## 固定接口与业务语义

### 配置与生命周期

新增配置默认值：

```dotenv
TASK_CENTER_ENABLED=false
TASK_CENTER_DATABASE_URL=
TASK_CENTER_POOL_MIN_SIZE=1
TASK_CENTER_POOL_MAX_SIZE=8
TASK_CENTER_POOL_MAX_WAITING=128
TASK_CENTER_POOL_TIMEOUT_SECONDS=5
TASK_CENTER_STATEMENT_TIMEOUT_MS=3000
TASK_CENTER_LOCK_TIMEOUT_MS=1000
TASK_CENTER_DISPATCH_LEASE_SECONDS=30
TASK_CENTER_DISPATCH_MAX_ATTEMPTS=3
TASK_CENTER_DISPATCH_RETRY_SECONDS=1
```

启用时 URL、schema 版本、池及 SQL 故障明确失败；不能静默退回内存或旧额度判断。每个进程／事件循环拥有自己的异步池，启动打开并就绪检查、关闭排空；连接总预算包含同步企业池和派发进程。生产迁移由显式 CLI 执行，HTTP 不执行 DDL。CLI 从独立的 `TASK_CENTER_MIGRATION_DATABASE_URL` 环境变量读取迁移 owner 连接，`--app-role` 明确指定已建好的受限应用角色并授予必要权限；应用仍使用 `TASK_CENTER_DATABASE_URL`，不在 HTTP 进程保留 owner 连接。预览不读取连接秘密。日志及错误不回显 DSN、密码、请求头或模型 key。

### 公共 DTO 与 HTTP

- `SubmissionCreateRequest`：`request: RunCreateRequest`，`idempotency_key: str`（1–200 字符）；请求工作区必须与服务端授权一致，额外控制字段禁止。
- `SubmissionView`：`id, workspace_id, project_id, status, expected_run_id, run_id, workflow_id, created_at, updated_at, period_start, dispatch_attempt_count, last_error_code`；内部 request JSON、lease token、保存的主体及私有授权上下文不外露。
- 状态限定 `pending / dispatching / dispatched / cancelled / dispatch_failed`。关联 `run_status` 单独、可空并标明观测时间；不得用提交状态宣称图执行完成。
- `SubmissionPage`、`QuotaLedgerPage`：`items, next_cursor`；limit 1–100，默认 20；游标绑定工作区和筛选条件，按 `(created_at,id)` 稳定排序。
- `QuotaSnapshot`：UTC 周期、limit、enforcement、imported_count、reserved_count、available；0 为零额度，`monitor` 允许但记录超额，不能当无限额度解释。
- 请求接受和幂等重放返回 202；同键异内容／取消或重试状态冲突 409；工作区权限 403；未知／不可见条目 404；次数不足 429；连接池或数据库暂不可用 503，并给出有限 Retry-After。

接口为 `POST/GET /api/task-submissions`、`GET /api/task-submissions/{id}`、`POST /api/task-submissions/{id}/cancel`、`POST /api/task-submissions/{id}/retry-dispatch`、`GET /api/workspaces/{id}/quota-ledger`。旧接口成功响应不换类型。

### 数据与事务

迁移位于 `backend/packages/task_center/migrations/001_core.sql`，schema `task_center`：

| 表 | 关键约束与职责 |
| --- | --- |
| `schema_migrations` | version 主键、SHA256 校验；迁移事务加 advisory xact lock；修改已应用迁移即拒绝。 |
| `workspace_policies` | workspace 主键、任务限额／enforcement 和策略版本；来自服务端企业配置，不是客户端报价。 |
| `quota_buckets` | `(workspace_id,period_start)` 主键，UTC period_end、imported_count、reserved_count；计数非负。 |
| `submissions` | 全局随机 ID；`UNIQUE(workspace_id,idempotency_key)`；规范化 request SHA、原始请求、server actor、原周期、expected run ID、状态。 |
| `quota_entries` | 不可变 reserve/release 流水；`UNIQUE(submission_id,action)` 防双扣／双返；导入历史独立审计。 |
| `outbox` | 每提交单一条派发记录；attempt／generation、owner token、lease_until、available_at、状态；只在新 epoch 重试时重开。 |
| `dispatch_attempts` | `(submission_id,generation)` 唯一；开始／结束、结果与脱敏错误，禁止秘密数据。 |
| `audit_events` | 提交、取消、重试、派发审计；与相应业务写同事务。 |

表使用工作区外键关联本模块策略行，并通过 `(workspace_id,submission_id)` 等复合关系防止跨租户串联。新增模块的 workspace 行是额度策略，不冒充替换现有用户／项目主数据。所有操作显式工作区条件，事务内 `set_config(..., true)` 设置租户上下文；RLS 非超级用户验收。Relay 的服务上下文只在内部方法开启。

`TaskCenterDatabase` 管理池和租户事务；`SubmissionRepository` 提供 `submit, get, list, cancel, retry_dispatch, quota_ledger, claim, acknowledge, fail`。`SubmissionService` 校验 Auth／项目、读取可信额度策略和历史种子；`SubmissionBridge` 将所有既有实际创建入口纳入同一准入；`OutboxRelay` 使用 dispatcher callable，默认适配现有 `RuntimeCommandService`。

`submit` 的固定顺序为：工作区／幂等键事务锁 → 查原提交（相同返回、不同 409）→ 初始化原周期与导入历史 → 原子次数预占 → 新提交 → reserve 流水 → Outbox → 审计 → commit。规范化请求包括全部业务字段及默认值，排除客户端幂等键；内部执行键固定为 `task-submission:{submission_id}`，避免跨工作区同客户端键碰撞。

额度的条件更新核心为：

```sql
UPDATE task_center.quota_buckets
SET reserved_count = reserved_count + 1
WHERE workspace_id = %s AND period_start = %s
  AND (%s = 'monitor' OR imported_count + reserved_count < %s)
RETURNING reserved_count;
```

无返回则抛 typed quota error，整个事务回滚。新周期导入已有运行次数时使用持久 journal／企业数据中的真实历史，排除本模块已拥有的 expected run IDs；导入只发生一次，不能把已有任务重置为零。启用／切换旧口径前停止旧写入进程，保存导入审计。UTC 跨月取消回原 bucket。

取消仅允许 pending 且无外部发送意图者；按统一锁顺序锁提交、Outbox、额度行，cancel、release、审计同事务。重复取消幂等，不重复返还。已派发／结果未知不返还，保留模型真实计量。人工 retry 仅对 dispatch_failed 重开原 Outbox epoch，保留旧尝试、同业务 ID、原预占，不生成新次数扣减。

Outbox 领取锁提交行并 `SKIP LOCKED`，随后更新 Outbox，保持取消／ACK／重试一致的锁顺序；只持短事务。ACK、失败与 lease 接管检查 token＋generation，旧 worker 不能覆盖新记录。外部操作至少一次，固定运行／workflow ID 幂等；不宣称外部调用 exactly-once。最多 3 次自动派发，unknown outcome 耗尽时保留额度和人工重试入口。

## Task 1 原生 PostgreSQL、连接池与版本化迁移

**Files:** 新建 `backend/scripts/local_postgres.py`、`backend/packages/task_center/{__init__,database,migrations,errors}.py`、`backend/packages/task_center/migrations/001_core.sql`、`backend/tests/postgres_support.py`、`backend/tests/integration/test_task_center_database.py`；修改 `backend/pyproject.toml`、`backend/packages/config/settings.py`，必要新增默认关闭配置测试。

- [x] 写真实数据库红测：owned cluster 启停、重复迁移不重建、checksum 漂移拒绝、事务 rollback、非超级用户租户隔离、池等待上限／超时与关闭。

```python
@pytest.mark.asyncio
async def test_exception_rolls_back_real_transaction(task_database):
    database = task_database
    with pytest.raises(RuntimeError, match="abort"):
        async with database.transaction("ws-a") as conn:
            await conn.execute("INSERT INTO task_center.workspace_policies (workspace_id,run_limit,enforcement) VALUES ('ws-a',1,'block')")
            raise RuntimeError("abort")
    async with database.transaction("ws-a") as conn:
        row = await (await conn.execute("SELECT count(*) AS n FROM task_center.workspace_policies WHERE workspace_id='ws-a'" )).fetchone()
    assert row["n"] == 0
```

- [x] 用现有 venv 运行红测，保存 `data/artifacts/task-center-2026-10-29/impl-task1-red.log`。缺 fixture／模块时先建立可运行合同，不能把拼写错误当红测证据。
- [x] `OwnedPostgres` 使用 `/private/tmp` 下随机目录、Unix socket、`listen_addresses=''`；initdb/pg_ctl 只针对有本次 marker 的目录，退出停止自己的 server 并删除目录。测试创建 NOSUPERUSER／NOBYPASSRLS app 角色；迁移 owner 与应用角色区分。任何真实 DB 启动失败显式报错，不能跳过后计通过。
- [x] 增加 `psycopg_pool` 依赖并安装到项目已有 venv；池 `open=False`，显式 open/wait/close；包数据包含 SQL。新增关系迁移不依赖 pgvector，不改旧 `001_enterprise_core.sql`。
- [x] 实现配置、迁移校验、连接上下文及错误脱敏；运行红测对应绿测与相关配置回归，再独立规格／质量审查。

Run: `COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests ../plan_a/.venv/bin/python -m pytest backend/tests/integration/test_task_center_database.py -q`。

## Task 2 原子提交、幂等、额度与控制事务

**Files:** 新建 `backend/packages/task_center/{models,repository,canonical}.py`、`backend/tests/integration/test_task_center_transactions.py`；仅必要的追加迁移，不覆写已验收迁移。

- [x] 为 `SubmissionRepository(database)` 与 `QuotaSeed` 固定类型，写并发红测；fixture `task_repository` 由已定义的 `task_database` 创建，每个测试隔离 schema 数据，`request_factory(key)` 返回当前 `RunCreateRequest`。

```python
@pytest.mark.asyncio
async def test_last_slot_is_reserved_once(task_repository, request_factory):
    seed = QuotaSeed(run_limit=1, enforcement="block", legacy_runs=[])
    results = await asyncio.gather(*(task_repository.submit(request_factory(str(i)), actor=TEST_ACTOR, seed=seed) for i in range(100)), return_exceptions=True)
    assert sum(isinstance(item, SubmissionView) for item in results) == 1
    assert sum(isinstance(item, QuotaExceeded) for item in results) == 99
    snapshot = await task_repository.quota_snapshot("ws-a")
    assert snapshot.reserved_count == 1
```

- [x] 实现上述固定 SQL 事务；100 个同键请求得到相同 ID、1 次 reserve、1 条 Outbox；同键不同内容 409。对每个业务写步骤在真实数据库层注入失败，检查提交、流水与 Outbox 全无半成品。
- [x] 实现 cancel、retry、ledger 和稳定分页；种子含已有任务时扣入 imported_count，排除已归属提交；测试跨月原 bucket 释放、重复取消、cancel vs claim 竞态、monitor／0 额度。
- [x] 测试租户作用域、复合 FK、状态／负数约束、同一连接先 A 后 B 上下文不残留。所有主断言查真实 SQL 行与计数，不仅检查 mock 调用次数。
- [x] 保存红／绿及真实并发结果，规格通过后质量审查。

Run: `python -m pytest backend/tests/integration/test_task_center_transactions.py -q`，沿用 Task1 隔离环境。

## Task 3 Outbox 领取、ACK、重试与进程退出

**Files:** 新建 `backend/packages/task_center/{relay,dispatch}.py`、`backend/tests/integration/test_task_center_outbox.py`；repository 增量及必要追加 SQL 迁移。

- [x] 两个真实进程竞争领取同一批 Outbox，记录每次 generation；真实 DB 检查不会并发获得同一有效尝试。
- [x] 实现短事务领取、发送意图记录、事务外 dispatcher、owner 条件 ACK／失败、有限退避与过期重领。取消仅允许尚未发送，发送前再次检查当前尝试；已写发送意图按 unknown 保守处理。
- [x] 写定向红测：owner 发送后崩溃、ACK 丢失、超时、旧 generation ACK、lease 到期后暂停旧 worker 恢复、3 次耗尽与人工重试；外部用持久的幂等受控接收器，不用内存 set 冒充跨进程幂等。

```python
@pytest.mark.asyncio
async def test_stale_ack_cannot_overwrite_new_attempt(outbox_case):
    old = await outbox_case.repository.claim(owner="worker-a")
    await outbox_case.expire_owned_lease(old)
    new = await outbox_case.repository.claim(owner="worker-b")
    assert new.generation > old.generation
    assert not await outbox_case.repository.acknowledge(old, DispatchReceipt(old.expected_run_id))
    assert await outbox_case.repository.acknowledge(new, DispatchReceipt(new.expected_run_id))
```

- [x] `mark_sending`、`acknowledge(claim, DispatchReceipt)` 与 `fail` 对失效租约／代际返回 False，Relay 明确记为 lease_lost；错误运行身份拒绝并抛 DispatchConflict。调用方不得忽略拒绝结果。ACK 不代表图完成；保留 run_id／workflow_id 和派发时间。内部发送结果状态必须是实际运行身份；不信任客户端或假 sender 的自报完成。
- [x] 原件保存、规格／质量审查；真实 Temporal 服务继续单列未验，不能混入本地进程测试结论。

## Task 4 既有创建入口统一准入与历史口径衔接

**Files:** 新建 `backend/packages/task_center/{service,bridge,factory}.py`、`backend/tests/unit/test_task_center_entrypoints.py`、`backend/tests/integration/test_task_center_runtime.py`；必要修改 `runtime/service.py`、`orchestrator/service.py`、`workflows/{service,activities}.py`、`app/routers/{workflows,enterprise}.py`、`app/deps.py`；已验收测试如需适应追加迁移，仅调整版本枚举，不改原业务断言。

- [x] 先写实际入口红测：RunService 直接创建、Runtime 创建、Temporal 直接启动、活动创建、扫描和监控实际创建均只能预占一次；旧重复请求在剩余额度 0 时仍返回原任务。
- [x] `SubmissionBridge` 在默认关闭时不创建池、不读 URL、不改变旧路径。开启时通过工厂复用 task service；任何无法验证的私有预占身份明确失败。
- [x] 持久记录由服务端选择的派发入口语义与执行后端，重放保持首次路由；相同幂等键更改交付语义应冲突，不能让 RunService 仅创建的回放被 Relay 改成启动另一条流程。内部字段不向客户端开放，必要时追加迁移。
- [x] 以进程内私有上下文承载经 DB 重验的派发授权；跨 Temporal 活动通过持久 run／workflow 身份和规范化请求重验同一提交，不向公共 DTO 暴露“skip quota”字段。作用域和 payload 改动均拒绝。 对已经发送但确认未知的远端工作，活动验证应基于持久身份、完整 payload、合法路由、未释放预占和发送意图；瞬时 Relay 租约失效不能撤销可能已被接受的工作。派发写回仍严格受当前 owner／generation 约束，活动不能代替旧 owner ACK。
- [x] 直接竞争调研、定时扫描和监控的 HTTP 启动入口先校验服务端主体与工作区／项目；控制工作流不提前扣周期次数，但不能让客户端 requested_by 冒充受信任身份后由活动代扣他人额度。
- [x] 旧入口维持成功 DTO，inline 派发与 Relay 使用同一领取／ACK 协议和稳定身份；竞争已被其他派发者领取时查询绑定或给明确 busy，不创造第二个任务。周期导入和原限额调整走同一个可信策略入口。
- [x] 已验证预占内使用固定 expected run 身份，不再按相似内容跨幂等键合并为另一运行；原 legacy 次数检查对已验证预占不再二次阻断；token／费用检查继续执行。旧手动恢复／重做不新增提交次数；新的扫描／监控周期创建新提交。
- [x] 任务次数策略以 PG 为真值：首次可信 seed 使用稳定版本，只有受权 quota PATCH 显式递增版本，内存 metadata 重启不覆盖已持久策略。PATCH 先提交 PG 任务次数策略，再同步旧 metadata；同步失败明确说明 PG 已生效，不能宣称跨存储回滚。Token／费用仍由旧 metadata 管理，本期不引入跨存储事务。

- [x] 实际本机派发必须接通既有共享执行控制；未配置时明确拒绝实际启动，不能把 Outbox 租约当作整个 Graph 的互斥。纯提交／查询和受控接收器事务测试仍可独立运行。
- [x] 实际 RunService／LangGraph demo 执行并核对关联 run、检查点和最终提交状态；模拟底层模型，不 mock 准入／journal／graph。保留原同机 execution_control fencing，不绕过旧内核锁。
- [x] 运行现有 runtime、workflow、HITL、恢复、共享执行回归，保存首失败与修正；规格／质量审查。

## Task 5 HTTP、权限、池与 Worker 生命周期

**Files:** 新建 `backend/app/routers/task_submissions.py`、`backend/scripts/run_submission_relay.py`、`backend/scripts/migrate_task_center.py`、`backend/tests/unit/test_task_center_http.py`；修改 `app/{main,deps}.py`、`.env.example`；企业池增量位于 `enterprise/postgres.py`、`task_center/database.py` 及相关测试。

- [x] 实现固定六接口，actor 来源复用鉴权；`project_id` 须属于当前 workspace；伪造 headers 在鉴权开启时不改变主体。429 额度与503池／存储错误分开。
- [x] 原始请求幂等身份与首次服务端确定的执行模式分别保存；同一 `auto` 请求在 demo／real 默认设置切换后仍返回原单，明确修改业务字段仍冲突。已有无法还原的旧输入不伪造恢复，迁移按追加版本处理。

- [x] 创建、查询、取消及 retry 的 API 测试使用真实数据库；明确非法游标、跨区游标、分页并发插入、limit 边界和未启用时的响应。
- [x] 同步企业适配器用有界 `ConnectionPool`，保持原事务／RLS语义；通过受控调用接入异步入口，不将事件环直接阻塞在同步 SQL。测试回滚和连接复用，不把整个 graph 放进线程。
- [x] 应用与 Worker 启动 open/wait，调用层先停止接收、等待或取消并 join 在途派发，再关闭池；Psycopg 的 close 标准语义不能当作已借出事务全部结束的证明；readonly readyz 验证配置、schema、池连接，不调用模型。迁移 CLI 默认预览，显式 `--execute` 执行；Relay CLI 默认预览，显式 `--execute` 启动有限并发循环，有停止清理。
- [x] 检查资源总预算，设置 SQL statement／lock timeout；有上限地将 pool overload 映射503／Retry-After。
- [x] 规格／质量审查后标准导出 OpenAPI／生成 TS；新 schema 变更须运行前端类型检查和构建，界面新页面不在本期。

## Task 6 真实 HTTP 与数据库故障／并发验收工具

**Files:** 新建 `backend/scripts/verify_task_center.py`、`backend/scripts/task_center_acceptance.py`、`backend/tests/integration/test_task_center_acceptance.py`；复用 owned PostgreSQL helper。

- [x] CLI 默认预览，显式 `--execute` 才启动专属临时 PG、随机 loopback HTTP 端口、两个 API 进程与两个 Relay 进程。拒绝现用端口／任意目录，启动失败返回非零，finally 只停止本次 PID／cluster。
- [x] 固定种子和 10／50／100 并发梯度，测试不同请求争剩1、相同幂等键100次、事务中断、取消领取竞争、发送后／ACK前进程退出、数据库断连、连接池饱和、租户切换与旧入口不能绕过。
- [x] 对比空闲与饱和时实际 HTTP吞吐、P50/P95/P99、错误分布、DB连接／等待、有效业务行和净额度。`EXPLAIN (ANALYZE, BUFFERS)` 使用自建适量数据，记录实际索引计划，不虚构 QPS目标。
- [x] 运行接收器与现有 demo graph 的关联身份分别核对；只替换外部模型／工具，不把假 dispatcher 等同完整 Agent 验收。未知 Temporal 网络结果仍列为未验真实服务。
- [x] 结束时所有 child join，pool、PG 和 socket 停止，临时目录删除；没有业务记录／预占／Outbox 泄漏。保存源码与输入冻结哈希、原始指标和结构化结果。
- [x] 工具、场景及结论经过独立规格与质量审查。

## Task 7 最终门禁、文档与分支交付

**Files:** README、`docs/agent-execution.md`、`docs/docker_deployment.md`、`docs/optimization/2026-10-29-task-center-delivery.md` 和 `2026-10-29-task-center-results.json`，必要 OpenAPI／TS 生成文件。

- [x] 最终冻结后独立运行真实 PG／HTTP验收；检查原始 SQL 行、账本恒等式、派发绑定与进程清理。冻结期间不再改源码。
- [x] 先隔离开启 env-file 读取的配置单测，使其只读取该测试的临时假配置；用读取前拦截证明不访问真实工作区 `.env`，生产配置加载行为不改。

- [x] 完整后端回归、实际配置 Ruff 对照基线新增0、标准 OpenAPI和前端生成／编译；失败保留原件，最小修复后重验。
- [x] 文档逐项区分已实现／真实验收／模拟外部请求／未验服务；说明状态职责、取消／重试计费、额度导入、迁移和连接预算，不宣称跨主机或报告语义合格。
- [x] 凭据扫描排除读取私有.env，精确核提交清单。

分支发布按已有授权提交推送当前分支，发布后核远端 SHA、提交文件和干净状态；实际结果以 Git 远端历史及本机 `final-git-verification.json` 为准，不在待提交内容中预填发布成功。

## 证据目录与完成定义

本轮所有红／绿、审查、数据库／HTTP原始指标及最终发布核验写入 `data/artifacts/task-center-2026-10-29/`，不同轮次不覆盖失败证据。上一轮 `local-concurrency-2026-10-28`、报告实测和现用数据库只读。

只有六接口、所有创建入口的统一准入、次数账本、可靠派发、真实 PostgreSQL 事务故障测试与真实 socket HTTP 并发实测均通过，才完成第一期；仅 helper 或 SQL mock 通过不计完成。真实 Docker／Temporal服务、pgvector完整旧企业投影与跨主机能力仍按依赖组合独立验收。
