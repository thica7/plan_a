# 本机持久化任务工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 subagent-driven-development，按任务先实现、再规格审查、最后质量审查。用户已批准本轮 P0，不重复请求执行许可。

**Goal:** 在原生 PostgreSQL 上提供重启不丢数据、可由像素桌面实际操作的提交与额度工作台。

**Architecture:** 复用第一期六接口、Outbox 和原 Agent 图；新增私有持久 PG 工作区与受控启停入口，前端按 runtime capability 选择新提交路径。企业元数据和提交账本均使用 PG，SQLite 执行日志／检查点按工作区隔离。

**Tech Stack:** PostgreSQL 15、pgvector、Psycopg 3、FastAPI、React／TypeScript／Vite、既有 LangGraph demo。

设计和已批准范围见 [设计说明](2026-10-30-persistent-workbench-design.md)。基线 `b744fa0e1db4857df99668ae333687eb2e636a55`，继续复用现有隔离 worktree／分支。所有失败／绿测／审查存 `data/artifacts/persistent-workbench-2026-10-30/`，不覆盖上期证据。

## Task 1 私有常驻 PostgreSQL 与完整业务初始化

**Files:** 新建 `backend/scripts/local_workspace_postgres.py`、`backend/tests/unit/test_local_workspace_postgres.py`、`backend/tests/integration/test_local_workspace_postgres.py`。必要辅助空文件 `backend/tests/integration/__init__.py` 保持同名 unit／integration 测试在默认 pytest 导入模式下可合并收集；不修改业务断言或全局导入配置。不把旧 `OwnedPostgres.stop()` 用于持久目录，不改已有 SQL。

- [x] 写失败测试：preview 零副作用、非归属／符号链接目录拒绝、重复初始化不清数据、停止后目录仍在、错误 PID／创建时间拒绝、重启仍有原业务行。
- [x] 实现固定接口，供后续启动器复用：

```python
class PersistentWorkspacePostgres:
    def __init__(self, root: Path, *, binary_dir: Path): ...
    def initialise(self) -> dict: ...
    def start(self) -> dict: ...
    def stop(self) -> dict: ...
    def status(self) -> dict: ...
    def app_environment(self) -> dict[str, str]: ...
```

类持有规范化工作区 root，管理 `root/postgres` 及独立 marker；短 socket 根由 root 哈希派生。公开返回值不含 DSN、管理环境或秘密。`app_environment()` 仅返回受限 app 配置，由调用者直接注入子进程，禁止打印。配置／依赖缺失明确失败；半初始化保留可诊断状态，不删目录。

- [x] 初始化使用已有 `EnterprisePostgresStore.migrate()` 与提交中心 `apply_migrations()`／`grant_application_role()`；先确认 pgvector。管理员执行初始化，app 只获企业 schema 必要 DML／sequence 权限及提交中心最小权限；不给 owner 成员关系或 DDL／TRUNCATE。数据库只监听私有 Unix socket。
- [x] 写真实 PG 测试：完整 schema／vector 已安装、默认工作区可查询、app 非 owner／非超级用户、两次启动原 task／project 行保留，使用真实 app pool；测试目录与用户工作区分离。测试结束仅清理自己创建的临时目录。
- [x] 命令与预期：

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=backend:backend/tests \
  .venv/bin/python -m pytest backend/tests/unit/test_local_workspace_postgres.py \
  backend/tests/integration/test_local_workspace_postgres.py -q -p no:cacheprovider
```

PG 测试因共享内存／进程检查需使用测试专属目录在已授权的沙箱外执行。先保存红测，最小实现后绿测；规格与质量审查通过再进入下一任务。

## Task 2 运行配置与受控本机启停

**Files:** 新建 `scripts/workbench_runtime.py`、`backend/tests/unit/test_workbench_runtime.py`；必要修改 `packages/config/settings.py`、`app/deps.py`、`packages/schema/api_dto.py`、`app/routers/runtime.py`、`frontend/vite.config.ts`、`.env.example`；新增 `backend/tests/unit/test_workbench_runtime_config.py` 与 `frontend/scripts/vite-env-isolation.check.mjs`（Node 专用隔离检查，红测不读取真实 env；Task2 首版及其证据使用 `.test.mjs`，Task4 全量前端复现双 runner 收集冲突后仅改名，断言字节保持）。运行相关 KB cache／trace／preference 路径通过 Settings 与 deps 保留默认并支持 profile 覆盖；标准生成 `frontend/openapi.json`、`frontend/src/api/openapi.ts`。

- [x] 先写配置／环境隔离红测：`RuntimeConfig.task_center_enabled` 默认 false；`GRAPH_CHECKPOINT_PATH` 默认 `runs/graph_checkpoints.db`，覆盖值传到真实 `GraphCheckpointer`；关 env-file 时 Vite 不读根／frontend env 文件。
- [x] 新入口命令固定为下面四个 action，默认仅 preview；只读 `status` 仍需显式 execute 才探测进程。初始化、启动不含 destroy：

```bash
.venv/bin/python scripts/workbench_runtime.py init
.venv/bin/python scripts/workbench_runtime.py init --execute
.venv/bin/python scripts/workbench_runtime.py start --execute
.venv/bin/python scripts/workbench_runtime.py status --execute
.venv/bin/python scripts/workbench_runtime.py stop --execute
```

支持 `--workspace-dir`（默认 `runs/local-workspace`）、`--backend-port`（8010）、`--frontend-port`（5180），测试使用自己的随机目录和空闲端口。非 loopback 绑定不提供；已有端口冲突、未知进程拒绝，不自动杀占用者。

- [x] 启动 PG → API → readyz → Relay → Vite，使用绝对代码路径和隔离工作区文件。复用 `dev_runtime.process_snapshot` 等可靠归属方法，但不用会读取根 `.env` 的旧环境构造函数。registry 包含 PID、创建时间、服务角色、规范代码与工作区身份。
- [x] 子进程使用显式环境白名单加 app 环境；`COMPETISCOPE_LOAD_ENV_FILES=0`、`DEMO_MODE=true`、LangGraph、执行控制开启、独立 journal／checkpoint／artifact／KB 路径；不继承管理 DSN、模型／搜索 key、Redis、Temporal、Qdrant HTTP。仅本机可信 loopback 演示，不擅自开放内网。
- [x] 停止先停止入口、等待／安全取消本工作区工作、join Relay／API，再停止 PG；保留持久数据。部分启动失败只回收本次已创建进程；不知道归属的资源不发信号。stdout／错误与 registry 不含应用环境和 DSN。
- [x] 对 raw settings、runtime DTO／API、新 CLI 与 Vite 配置做定向测试，导出 OpenAPI／TS 并核生成稳定；这一任务不实现 UI 页面。

## Task 3 提交中心页面与新建研究接线

**Files:** 新建 `frontend/src/api/submissions.ts`、`frontend/src/pages/Submissions.tsx`、`frontend/src/pages/Submissions.test.tsx`；必要增加一个聚焦 hook／样式文件；修改 `features/new-run/useNewRunBuilder.ts` 及测试、`features/desktop/apps.tsx` 及相关测试、`api/types.ts`、`stores/i18n.ts`。不重写桌面／旧报告页面。规格修复增加 `frontend/src/api/workspaceScope.ts` 及聚焦测试，统一入口、预检、载荷和详情工作区；质量修复仅在 `DesktopWindow.tsx` 提供独立的 `windowVisibility` Context，提交资源最小化时暂停读取、恢复时读取，同 key 缓存与错误手动恢复语义保留。

- [x] 先写前端红测：runtime 开启时新建只调用提交 API，进入 `/submissions/:id`；关闭／旧 runtime 缺字段时保持旧路径；新接口出错不回退；相同载荷失败重试沿用同键，载荷修改换键，快速双击只发一次。
- [x] 新演示 profile 不带搜索凭据：demo 模式的自动竞品入口允许走模拟流程并明确标识演示资料；real 模式仍执行真实搜索能力检查，不能伪造 has_web_search_key。相同意图的未知结果重试即使最新余额为 0 也应允许同键重放，由服务器判定；不得被旧配额预检误阻。
- [x] 从生成 schema 引用 SubmissionCreateRequest／SubmissionView／SubmissionPage／QuotaLedgerPage 类型。所有请求使用既有 `apiFetch` 鉴权和同源限制；状态错误保留 HTTP status／code，503／429／409／403／404 给中文可执行提示。
- [x] 桌面“提交中心”列表提供当前工作区、状态筛选、游标下一页／返回首页和刷新；额度展示 limit／imported／reserved／剩余与 reserve／release 流水，monitor 超额不伪装成 block。不要把任务次数写成模型账单。
- [x] 额度汇总使用服务器整月快照，不把当前页流水求和当整月统计；dispatched 但运行失败时只提供原分析详情入口，不展示“重试派发”或“报告合格”。
- [x] 单条详情分别展示提交派发状态与运行观测状态、最后错误码／尝试次数、取消和重试派发。关联 run 后用明确链接打开原 RunDetail；`dispatched` 不展示为报告完成。服务未启用／断开／无权／空列表分别显示。轮询不重叠，卸载／换工作区后丢弃过期响应，不持续在隐藏／错误状态制造风暴。
- [x] 沿用明亮像素风、中文文本、已有按钮／链接的交互审计约定和可访问性标签；英文 locale 不显示内部技术代码作产品说明。
- [x] 测试取消 409 竞态、重试成功／失败、网络错误后恢复、运行状态更新、分页／工作区隔离、卸载轮询停止；再运行旧 builder／Desktop 回归与 build。

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 pnpm --dir frontend test \
  src/pages/Submissions.test.tsx \
  src/features/new-run/useNewRunBuilder.test.tsx \
  src/features/desktop/Desktop.test.tsx
COMPETISCOPE_LOAD_ENV_FILES=0 pnpm --dir frontend build
```

## Task 4 真实持久化与故障闭环验收

**Files:** 新建 `backend/tests/integration/test_persistent_workbench.py`；必要新建 `backend/scripts/verify_persistent_workbench.py`，默认 preview，execute 只操作本次自有测试目录；不把用户常驻目录当可删除 fixture。另将 Node 专用环境检查 `.test.mjs` 原样改名为 `.check.mjs`，消除 Vitest 误收集；显式 Node 命令仍必须执行全部 8 项，不改过滤规则或断言。 真实状态兼容探针确认 `completed_with_blockers` 被原 PostgreSQL CHECK 拒绝（SQLSTATE 23514）；新增 `backend/db/postgres/002_run_delivery_status.sql`，仅在既有管理迁移事务／锁中顺序应用，在 `EnterprisePostgresStore.migrate()` 接入。保留旧 SQL，允许原五状态与该阻断状态，非法状态继续拒绝，不改 QA／发布规则。

- [x] 真实 PG + vector + 企业 app pool + API + Relay 跑 demo 提交至图完成，记录提交 ID／run ID／project／report version／额度流水／检查点的绑定。
- [x] 停 API／Relay 后重启，核 PG 项目／报告／提交仍在；再停止 PG 并重启整栈，原 ID 与 reserve 仍唯一，journal/checkpoint 未丢。
- [x] 相同 key 并发 20 请求只一单；不同请求争最后一次配额只有一单。另验证没有 Relay 时 pending 不冒充完成、重启 Relay 能继续；数据库不可用／额度不足有明确响应且恢复后可查。
- [x] 验收器核自己进程的实际 exit／归属／cleanup；API／Relay 错误退出不得把“已退出”算成功，保留首失败；用户常驻 PG 正常 stop 保留数据，测试目录仅在证明归属且进程全停后清理。
- [x] 浏览器在真实前端操作一次：新建 → 提交详情 → 运行／报告链接 → 刷新／服务重启后仍可查看；观察明亮像素样式和中文状态，截图保存在本机证据目录。模型内容为 demo，不计语义验收。
- [x] 在自有真实 PG 验证原五状态约束升级、重复迁移不丢旧数据、受限 app 保存并读回 `completed_with_blockers`，非法状态仍拒绝；保留首个 23514 故障原件。
- [x] 各 Agent 仍通过既有 graph 执行，本轮不改分析／写作算法，不调用外部模型。

## Task 5 最终回归、文档与交付

**Files:** README、`docs/agent-execution.md`、`docs/docker_deployment.md`，新增 `docs/optimization/2026-10-30-persistent-workbench-delivery.md` 与脱敏 results JSON。 全量回归另外确证 `test_workbench_runtime.py` 的父包导入缓存未被替身隔离；仅补两行测试 mock，保留全部原断言、生产代码不变，并经独立规格／质量审查后重跑完整后端。

- [x] 冻结后 root 独立运行完整后端、相关前端／桌面交互回归、标准 OpenAPI／TS、构建；实际 Ruff 用 path/code/message/source-line 多重集合对照本轮基线，新增 0。保留所有环境失败与修复原件，不改旧断言以掩盖问题。
- [x] 完成真实常驻工作区启动与重启验证，正常结束后按演示需要保留其进程／数据；仅处理本启动器的服务，旧演示／旧验收证据不变。记录实际访问 URL 和哪些进程仍运行，不把预览／HTTP202当全流程成功。
- [x] 文档说明完整企业PG已验的实际版本／vector版本、loopback 信任边界、启动命令、数据路径／备份与停止、旧数据未自动迁移、内容质量和 Docker／真实模型／Temporal／Redis仍未验。既有报告0/4结论原样保留。
- [x] 最终规格与整体质量审查通过；预发布候选凭据扫描与受控源码／文档范围核对通过，保留所有首失败和修复原件。

发布动作由 root 在终审后执行：复核最终暂存内容的凭据与路径，按已有授权提交并普通推送当前分支，不合并 main、不强推。实际发布以包含本计划的 Git 历史、远端 SHA 与本机最终核验记录为准，不在待提交文件中预填未来提交 SHA。

## 验收命令和执行约定

当前 workspace 的 Python 在 `../plan_a/.venv/bin/python`；文档使用可移植 `.venv/bin/python`。真实 PG／进程／socket 测试直接申请沙箱外运行于自有随机目录；不要先把共享内存权限错误当作业务故障。不得打印真实连接秘密、原 `.env` 或完整子进程环境。

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=backend:backend/tests:backend/tests/unit:backend/tests/integration \
  .venv/bin/python -m pytest backend/tests -q -ra -p no:cacheprovider
COMPETISCOPE_LOAD_ENV_FILES=0 make sync-openapi PYTHON=.venv/bin/python
COMPETISCOPE_LOAD_ENV_FILES=0 pnpm --dir frontend build
```

遇到明确依赖阻碍时先完成不受影响项，保留证据并报告；不因工程验收通过升级旧报告的语义质量结论。
