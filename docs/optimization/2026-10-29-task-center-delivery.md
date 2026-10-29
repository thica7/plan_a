# PostgreSQL 提交中心第一期交付记录

项目于 2026-10-29 启动，最终本机验收于 2026-10-30 完成。实施依据为[已批准方案](2026-10-29-postgres-backend-proposal.md)与[任务计划](2026-10-29-task-center-plan.md)，基线为 `265bdc84f27567706e990d6a901282e34bf40b84`，分支为 `codex/pastoral-desktop`。本记录描述实现与本机验收事实，具体指标、源码哈希和原始结果摘要见[脱敏结构化结果](2026-10-29-task-center-results.json)。

第一期实现持久提交、幂等、任务次数预占、Outbox、可靠派发、取消／人工重试、历史次数导入与显式迁移；默认 `TASK_CENTER_ENABLED=false`。真实验收使用本机原生 PostgreSQL 15.18 和真实 socket HTTP，未执行 Docker、模型训练或外部模型调用。报告语义质量仍未整体达标，Writer 实验开关保持 0；此处的 demo 图完成不改变历史四份报告未合格的结论。

## 接口、状态与业务身份

公开接口由 [task_submissions.py](../../backend/app/routers/task_submissions.py) 提供：

| 方法与路径 | 行为 |
| --- | --- |
| `POST /api/task-submissions` | 接受新提交或同键同内容重放，返回 202 |
| `GET /api/task-submissions` | 工作区／状态过滤与稳定游标分页 |
| `GET /api/task-submissions/{id}` | 单条提交和独立运行状态观测 |
| `POST /api/task-submissions/{id}/cancel` | 满足条件时取消；重复取消保持原结果 |
| `POST /api/task-submissions/{id}/retry-dispatch` | 仅失败派发可人工重试，返回 202 |
| `GET /api/workspaces/{id}/quota-ledger` | 月度次数快照与 reserve／release 账本 |

创建载荷为 `request: RunCreateRequest` 与长度 1–200 的 `idempotency_key`，禁止额外控制字段。内部 request JSON、保存的主体、lease token 和私有授权不作为公开 DTO 输出。分页默认 20、上限 100，游标绑定工作区与筛选条件。同键异内容、取消／重试状态冲突为 409；工作区权限不足为 403，未知或不可见条目为 404；次数不足为 429；数据库／连接池暂不可用为 503，并返回有限 `Retry-After`（当前为 1 秒）。无效请求按 400／422 的对应校验处理。

提交状态为 `pending / dispatching / dispatched / cancelled / dispatch_failed`。`dispatched` 仅表示派发已确认，`run_status` 及其观测时间另从 run journal 读取，可以为空；它不代表报告完成，也不代表报告语义合格。HTTP 提交成功表示 PostgreSQL 已接受意图，模型执行在后续流程中发生。

启用后六类实际创建入口统一进入 PostgreSQL 准入：`RuntimeCommandService.create_run`、`RunService.create_run`、`TemporalWorkflowService.start_competitive_intel`，以及 CompetitiveIntel、ScheduledScan、Monitor Activity。定时控制工作流不预占未来所有周期，实际周期创建才占一次；同一周期重放保留原业务身份。余额降为 0 后，同一单重放仍可完成，不再次扣额。真实 PostgreSQL 集成测试见[旧入口验收](../../backend/tests/integration/test_task_center_runtime.py)。

原始客户端**规范请求 SHA** 与首次解析后的实际派发 payload SHA 分开保存。新请求 `auto` 仅在首次接受时解析执行模式与路由；重放使用原客户身份及首次路由，不随部署配置漂移。迁移 `003_client_request_identity` 新增可空 `client_request_sha`；旧 NULL 行不能猜测已丢失的原始 `auto`，只能按已存载荷比较或使用原提交 ID 操作。本期是新协议首次发版，没有生产旧 v2 提交数据；该兼容限制仍保留，不能宣称恢复了旧原始请求。

## 次数账本与策略

额度单位是**任务次数**。一次事务写入 submission、唯一 reserve 和唯一 Outbox；每工作区幂等键只对应一单。旧 token／费用预算继续独立执行，本账本不是实际模型账单。`limit=0` 是零额度，`block` 拒绝超额，`monitor` 允许但审计超额。

月桶使用 UTC 月边界。首次建立桶时，从真实 `journal.load_run_summaries()` 按工作区、去重 run ID、创建周期导入历史次数，并排除提交中心已有 expected run ID；每桶仅导入一次。启用前必须停旧 writer 并备份，避免桶初始化后继续走旧路径漏计。策略以 PostgreSQL 为真值，Memory metadata 重启不覆盖；PATCH 在行锁内合并本次字段。PG 提交后 metadata 镜像失败会明确返回已生效的同步错误，不表示策略回滚。

未曾有发送意图的 `pending` 单可取消，重复取消不重复 release；跨月仍返还原周期桶。已有历史发送意图、正在派发或外部结果未知的单保留预占，不自动退款。人工 retry 只允许 `dispatch_failed`，沿用原 submission／expected run／workflow／reserve，递增 epoch，每个新 epoch 默认最多 3 次派发尝试；没有重新计费或无限自动重试。

## 派发与连接生命周期

[Relay](../../backend/packages/task_center/relay.py) 以短事务、`SKIP LOCKED`、lease／owner token／generation 领取工作，事务外调用现有运行入口。持久发送意图与条件 ACK／fail 防止过期 owner 改写新状态；稳定 run／workflow 身份用于接收侧幂等。语义为至少一次投递，外部未知结果可能已经执行或付费，不承诺外部 exactly-once。

实际链路为 PostgreSQL 提交 → Relay → `TaskCenterService.dispatch` → RunService／LangGraph 或 Temporal／Activity → 原 Agent 图；各 LLM Agent 不各自持有新 PG 池。Graph 执行仍依赖同机共享 SQLite、POSIX execution control、durable journal 和图检查点，不具备已验收的跨主机运行能力。

异步 PG 池默认每进程 min 1／max 8、max waiting 128、池等待 5 秒、statement timeout 3000ms、lock timeout 1000ms；同步 enterprise 池默认 max 4、等待 5 秒。metadata 使用默认 4 槽有界 offload，取消会等待已借出线程结束。停机停止接收、join Graph／Relay／metadata、排空事务，再关闭 driver。旧 Graph／hydrate／stream 仍有同步 SQL，不能称整个后端全异步。

owner 专用 `TASK_CENTER_MIGRATION_DATABASE_URL` 仅由显式迁移 CLI 执行读取，不进入应用环境；`TASK_CENTER_DATABASE_URL` 使用受限非 owner、`NOSUPERUSER NOBYPASSRLS` 角色。管理员先建角色；`--app-role` 仅授予既有角色必要权限，不能让 app 继承 owner。迁移及 Relay 均默认 preview，`--execute` 才产生迁移／运行副作用。HTTP 不执行提交中心 DDL。部署、旧 enterprise schema 前置、当前镜像缺脚本及 Compose 缺 Relay 的接线要求见[部署步骤](../docker_deployment.md#7-postgresql-提交中心第一期)。

## 最终冻结后验收

Phase A 仅修正启用 env-file 的测试夹具，候选限定为临时 `fake.env`，保留真实加载器与 timeout=12 断言。读取前守卫证明旧夹具会访问测试目录外候选并在读取前失败，修复后同守卫通过；整文件 22 项通过。生产 loader 不变，没有读取项目私有 `.env`。冻结清单包含 456 份 source／test／生成合同文件，后续全量回归及原生 CLI 基于该冻结内容。

| 最终工程门禁 | 实际结果 |
| --- | --- |
| 完整后端 | 9071 passed、1 skipped、250 warnings；525.11 秒，exit 0 |
| 唯一 skip | `test_postgres_rls_smoke.py:12` 需专用 `ENTERPRISE_RLS_SMOKE_DATABASE_URL`；提交中心真实 PG 测试未跳过 |
| Ruff | 实际配置基线 4023→4023，source-aware 多重集合新增 0；保留历史存量，Ruff 本身 exit 1 |
| 标准 OpenAPI／TypeScript | 重新生成与冻结文件字节一致 |
| 前端 | `pnpm --dir frontend build` exit 0 |
| 最终独占原生 CLI | exit 0；独立原始 SQL／SQLite／哈希／进程检查 25/25 通过 |
| 源与原件保护 | 456 冻结文件匹配；另核 255 份前阶段原件均未改变 |

Ruff 对照使用路径、规则、消息、源行文本的多重集合并保留重数，不能只比较行号或把 exit 1 说成全仓零问题。原生 CLI 自带 439 份运行源码快照和 463 份 evidence 哈希，两类均独立匹配；这与 456 份 Phase A 冻结文件是不同口径。

### 真实 HTTP 指标

平台为 macOS arm64，原生 PostgreSQL 15.18（Homebrew）；具体机型、总内存和 CPU 容量未完整采集。固定 seed 4242，2 个 API、2 个 Relay，另有受控接收器、controller 和单独 demo Graph。企业 metadata 为 Memory，提交、额度和 Outbox 使用真实 PostgreSQL。外部模型和真实 Temporal 服务均为 0。

实际池配置为 API 2×4＋Relay 2×4＋controller 4＝20；临时 tenant pool 1 在 Relay 启动前关闭，PG max connections 32。API 等待 1 秒、lock 700ms、statement 1500ms，不能与生产默认值混用；本次没有同步企业 SQL 池的连接负载。

| 单轮突发请求数 | 空闲提交请求/秒 | P50 ms | P95 ms | P99 ms | HTTP |
| --- | ---: | ---: | ---: | ---: | --- |
| 10 | 134.9347 | 45.904 | 65.170 | 65.170 | 202×10 |
| 50 | 150.5325 | 206.480 | 281.803 | 310.093 | 202×50 |
| 100 | 84.4231 | 519.992 | 1041.830 | 1077.984 | 202×100 |

| 人为饱和请求数 | 返回请求/秒 | P50 ms | P95 ms | P99 ms | HTTP |
| --- | ---: | ---: | ---: | ---: | --- |
| 10 | 4.6526 | 781.769 | 2130.414 | 2130.414 | 503×10 |
| 50 | 17.3287 | 1753.385 | 2197.154 | 2835.342 | 503×50 |
| 100 | 33.3733 | 1835.971 | 2255.928 | 2927.139 | 503×100 |

饱和错误来自 `task_center_storage_error`／`task_center_pool_busy`，均给 Retry-After；解除后创建恢复 202，两个 API 池恢复 available 4、waiting 0。这里的请求/秒只统计一次突发窗口内的提交或错误返回，不是稳态容量、SLA、模型吞吐或完整报告耗时。吞吐不包含 explain fixture。

### 事务、身份与退出证据

| 场景 | 最终原始证据结论 |
| --- | --- |
| 剩余 1 次、100 个不同请求竞争 | 1 个 202、99 个 429；1 submission／reserve／Outbox |
| 同键 100 次 | 全部 202；仍仅 1 submission／reserve／Outbox；异内容 409 |
| 三处事务故障注入 | submission／quota entry／Outbox 写入分别失败，回滚后均为 0 行 |
| 取消与领取竞争 | 本次 12 次均由领取先赢、取消 409；历史发送意图取消 409；可取消释放另由真实 PG 集成测试覆盖 |
| 租户／授权 | 伪造角色与工作区 403，不可见 ID 404；同一租户连接反复切换不串上下文 |
| 连接断开／数据库停止 | 断开后 503，重连恢复 202；最终停 PG 后 10 个请求全 503／Retry-After |
| 接收成功、ACK 前退出 | 发送 2 次、1 个接收侧业务身份、2 次派发历史、1 reserve；旧 ACK／fail 和伪 generation 均拒绝 |
| 自动尝试与人工重试 | 首 epoch 3 次、新 epoch 3 次，仍同一单和一次 reserve，退款 0 |
| 真实生产 adapter 的 demo Graph | `TaskCenterService.dispatch → RunService → LangGraph`；expected run 与实际 run 相同，19 checkpoints／29 events，真实 thread 由 `(expected_run_id, 'demo')` 推导后独立匹配 |

最终 SQL 导出为 1380 submissions、1380 Outbox、1380 reserve entries、8 月桶：179 dispatched、1200 pending、1 dispatch_failed。1200 pending 属于 `explain` 工作区的合成查询计划夹具；unknown 工作区的 1 单保留 reserve 是合法保守状态。账本恒等式、唯一身份、引用绑定及非法／孤儿检查均通过；不能把合法保留行误报为泄漏，也不能把它们计入 HTTP 吞吐。`EXPLAIN (ANALYZE, BUFFERS)` 在 `enable_seqscan=on` 下分别使用列表与幂等索引，完整计划保留在原件。

受控 HTTP 接收器只证明幂等投递边界；19／29 的 Graph 证据来自另一次真实 adapter 路径，不能混作真实外部模型或 Temporal 全链路。退出核验逐个父控 Popen 记录 role／PID／returncode／发起信号与原因：仅一个已关联发送者允许预期 exit 73；Graph 自然 exit 0；父控主动 TERM 允许 0／-15。所有 child accepted、无强杀，join／pool／socket／端口／PG／临时目录清理均通过。

## 保留的失败与修复链

- Task 6 初版验收器忽略接收器意外 `-9`，曾将退出异常误报为 passed。fix1 改为父控逐 PID 原因校验，只接受已核实的单一 sender 73；非预期退出和强制 KILL 均失败。健康 CLI exit 0 与接收器 `-9` 负向 CLI exit 1 均有原件；不能仅信 JSON 的 `status` 字段。
- 本次 Phase A 的 env 夹具红证据在文件读取前拦截，绿证据仅访问临时假配置；没有用读取真实秘密证明风险。
- 主控首版独立 oracle 将 `Counter(mapping)` 的行字典误当计数，造成两个假阴性。v2 只改为按 submission ID iterable 构造 Counter；应用／测试未改，原 23 项检查保留并重新核所有原始哈希，最终 25/25。首版原件只读保留，不覆盖或隐藏。

这些记录均在本机忽略目录 `data/artifacts/task-center-2026-10-29/`，不是 GitHub 可访问附件。权威最终原件为 `impl-task6-fix1-run-20261030-004822-4ff73fbd/result.json`，SHA256 为 `95760ad9d9c3e032b73c6084ad6af625ca162d45c6f9fd4858b9d113ac506e97`；其目录名前缀来自工具版本，最终性由本次主控日志、SHA、源码匹配与退出码共同确定。

同目录保留 `root-task7-full-backend-1.log`、`root-task7-gates.json`、`root-task7-independent-oracle.json`、`root-task7-independent-oracle-v2.json`、`root-task7-ruff-comparison.json`、`root-task7-previous-stage-check.json`、`root-task7-frontend-build.log`、`impl-task7-env-*`，以及 Task 1–6 的红绿和审查链。公开 JSON 仅导出白名单指标、配置和哈希，不上传 raw SQL／SQLite、capability、认证资料、临时地址或私有路径；456 份源码哈希不包含本文或结果 JSON，避免自引用循环。

## 复跑与未验范围

已安装后端开发依赖的仓库根目录执行；原生验收需本机可用的 `initdb/postgres/pg_ctl`。默认预览无连接和运行副作用，只有 `--execute` 创建自有私有临时 PG 与随机 loopback socket，不连接现用数据库；结束后关闭自有资源：

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend \
  .venv/bin/python backend/scripts/verify_task_center.py
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend \
  .venv/bin/python backend/scripts/verify_task_center.py --execute

COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=backend:backend/tests:backend/tests/unit:backend/tests/integration \
  .venv/bin/python -m pytest backend/tests -q -p no:cacheprovider
COMPETISCOPE_LOAD_ENV_FILES=0 make sync-openapi PYTHON=.venv/bin/python
pnpm --dir frontend build
```

复跑保留失败首次原件、输入 seed、配置、源快照、SQL／SQLite 与退出记录；应同时核 CLI exit、各 child 退出原因、账本／身份及证据 SHA，不能只看 passed。可按脱敏结果中的 `source_sha256` 逐文件重算 SHA256。

本期未验证 Docker／共享容器卷、真实 Temporal 服务与 Redis、PostgreSQL 17 完整 pgvector 企业投影、跨主机、多主部署、外部模型性能、完整 real Agent 报告语义或稳态 SLA。不新增 Kafka，不训练模型；旧报告质量、调用和 token 记录保持各自历史日期与原结论。
