# 本机并发治理实施计划

> **For agentic workers:** 使用 subagent-driven-development。一个实现者串行写源码；每项先规格审查，再质量审查。旧验收原件只读。

**Goal:** 让实际任务入口遵守有界准入、共享执行归属和模型总并发，补缓存去重并完成本机压力验收。

**Architecture:** 同一 RunJournal SQLite 协调表加 POSIX 文件锁；执行上下文带 token/generation，空闲写使用 revision CAS；缓存使用有界 single-flight，Redis 互斥仅做离线合同验证。

**Tech Stack:** Python asyncio、sqlite3、fcntl、FastAPI、pytest、现有 LangGraph/Temporal/Redis 适配。

基线 `f46684a582d56d49e11b0f914deaf9062f731cf1`，复用 `codex/pastoral-desktop` 工作区。用户已批准本轮范围及实施；容量起点和同机边界见[设计](2026-10-28-local-concurrency-design.md)，不再重复请求已获授权。Docker、Kafka、训练和付费模型压力测试不在本轮范围内。

## Task 1：可独立验证的共享协调器

**Files:** 新建 `backend/packages/infrastructure/execution_control.py`、必要的同目录 `process_locks.py`；测试 `backend/tests/unit/test_execution_control.py`。

- [x] 写红测：两个独立 coordinator 实例指向同一临时文件，`admit(run_id, workspace_id, operation_id)` 有界幂等；`async with coordinator.run(ticket)` 实际持有执行名额；`async with coordinator.model_slot()` 跨进程持有固定模型名额。用 spawn 子进程验证，不用一个对象伪装跨进程。
- [x] 实现 `ExecutionPolicy`、`SQLiteExecutionCoordinator`、typed capacity/conflict/timeout 错误、token/generation ticket、原子短事务、同区 FIFO 与跨区可运行调度、排队期限和取消清理。运行名额与模型名额绑定内核锁；配置池不一致拒绝；持锁进程暂停不允许 TTL 强抢。
- [x] 实现上下文重入、有效性校验、明确 release/handoff 所需原语和可读取的容量快照；不接生产调用，不修改旧业务存储语义。
- [x] 运行：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_execution_control.py -q`。必须覆盖进程退出、取消与 to_thread 事务完成竞争，不泄漏持锁 FD 或 ticket。
- [x] 独立规格通过后质量审查，输出保存在 `data/artifacts/local-concurrency-2026-10-28/`，不提交运行数据。

Task1 基础模块独立规格／质量复审通过；30 项定向测试通过。首轮审查发现并修复子任务越权释放、图节点凭据读取和取锁跨越期限问题；失败原件保留，见本轮 artifact 中 `review-task1-*` 与 `impl-task1-deadlinefix-handoff.json`。这仅证明基础协调原语，不代表实际任务入口已接通。

## Task 2：实际任务准入、执行归属和共享状态

**Files:** `config/settings.py`、`memory/run_journal.py`、`orchestrator/service.py`；必要新建 `orchestrator/execution_control.py` 混入；`runtime/service.py`、`runtime/commands.py`、`app/routers/runs.py`、`workflows/activities.py`，必要 `workflows/competitive_intel.py`。测试新建 `test_shared_run_execution.py` 及相关现有恢复/HITL 测试。

- [x] 先红测实际入口：global=1、queue=2，第一任务阻塞、两个等待，额外请求明确容量错误；同 run 两个实例只进入一次图，幂等重发不占额外 ticket。
- [x] 新增显式协调开关、同 journal 路径校验和设计中的有界参数。开启后存储/平台/路径错误明确拒绝，默认关闭保留旧部署兼容；本轮验收必须开启。
- [x] 把准入接入 HTTP 接受之前；run_pipeline/recover/resume/scoped redo 和 Temporal 活动在首次修改前统一 guard，嵌套重做重入。resume 将所有权移交唯一后台任务，HTTP 返回或取消不重复调度。
- [x] RunJournal 增 revision CAS 和执行 token/generation 拒写；原子事件分配与控制事件追加。更新生产 emit/persist 的必要接线，不用异步 fire-and-forget 保存绕过预算顺序和 fencing。
- [x] 修读取方的状态修复写入，跨实例 GET/list 读共享记录；SSE 按持久游标补读，有界内存兼容路径。仅所有权有效的执行者可以提交最终状态，失权 except/finally 不覆盖新 owner。
- [x] Temporal 三类活动明确 busy/等待语义，不能把 running 当 completed；离线调用真实活动对象验证，无需启动服务。
- [x] 运行新增测试及 `test_run_recovery_stream.py`、`test_run_recovery_boundaries.py`、`test_hitl_runtime_commands.py`、`test_runtime_user_loop_backend.py`、工作流相关回归；规格后质量审查。

Task2 已通过独立规格 R3 和质量 R4 复审；最终指定组 240 项、默认关闭兼容子集 16 项通过，两组不作相加。修复了重复消费者取消、Temporal 启动意图与失败收尾、重启后排队接管、项目范围竞态、原子迁移和短写锁清理。真实 Temporal 服务与全后端回归仍留后续验收；控制型扫描／监控 workflow 不占运行名额，每次实际调研执行才准入。

## Task 3：模型 transport 全局名额

**Files:** `llm/doubao_client.py`、原生模型搜索实际 client、必要 `infrastructure/execution_control.py` factory；`knowledge/retrieval.py` 仅必要接线。测试 `test_global_model_concurrency.py` 与现有执行预算/provider tests。

- [x] 红测两个进程混合普通生成、RAG 查询改写和原生模型搜索，受控 transport 记录活跃峰值；保护必须在实际 transport 外围，不能 monkeypatch 掉被测名额入口。
- [x] 发送前取得全局 slot，再执行 `reserve_transport()`；未发送的排队取消/超时不虚记调用，重试和备用 provider 共用池，backoff 不占名额。
- [x] 保留原模型预算、usage、真实重试/取消与错误脱敏；独立工具 Search/Fetch 不冒充生成调用，未完成 RPM/TPM 调度明确保留。
- [x] 独立规格后质量审查；旧真实 writer 原件不改，默认关闭路径保持既有协议与预算测试。

Task3 已通过独立规格和质量审查。新增 27 项测试及实现者 403 项相关回归通过；独立规格另核 5 个真实运行检查点故障场景。双进程合成 transport 首红峰值 6（配置 2），接线后峰值不超过 2。等待未发送时归还预留、实际发送后未知计费保持；这些是受控 transport 验证，不是真实服务商容量或调用费用实测。

## Task 4：有界缓存并发去重

**Files:** 新建 `infrastructure/singleflight.py`；`infrastructure/source_cache.py`、`redis_runtime.py`、`tools/evidence_fetch.py`、`knowledge/retrieval.py` 的必要接线。测试 `test_singleflight.py` 及现有 source/retrieval/redis tests。

- [x] 红测 32 个同页请求仅一次实际 fetch、相同 embedding 仅一次实际计算；不同模型/选项/范围不合并。
- [x] 实现有界键/等待者、独立结果副本、单个取消隔离、无人等待时取消、异常键清理和过载行为。缓存命中保留采集时间和全部证据验证。
- [x] 保留价格/敏感 URL/强制刷新/DeepSeek 独立 Fetch 的绕过；不把 single-flight 描述成跨进程缓存。
- [x] 可选 Redis 缓存互斥用 owner token 安全释放，假共享客户端验证跨实例，真实 Redis/Lua/TTL/故障留部署验收；不新增业务真值到 Redis。
- [x] 运行 source、retrieval、redis 与新 single-flight 测试，规格后质量审查。

Task4 规格 R2、质量审查通过；最终相关回归 294 项通过，独立规格定向 44 项通过，不作相加。32 次实际 ASGI 检索请求每次创建 service 仍只计算一次相同 embedding，项目结果独立。修复了缓存过期被旧命中绕过、Redis 获取锁确认未知时取消未清理的问题；旧失败证据保留。真实 Redis 服务仍未验收。

## Task 5：压力、故障与交付

**Files:** 新建 `backend/scripts/verify_local_concurrency.py`、必要 `backend/tests/integration/test_local_concurrency.py`；更新现有 Locust 说明、README、Agent 执行及部署边界文档。

- [x] 写可重复的实际入口集成验收，再提供默认预览、显式执行的本机脚本；使用临时目录和合成执行，不加载 .env、不使用现用 DB 或付费模型。
- [x] 固定种子/规模，记录排队/拒绝/过期、运行和模型峰值、延迟分位、错误和资源清理；覆盖慢消费者、冷缓存突发、取消与 owner 进程退出。不能从本机合成数据推导真实模型或跨容器容量。
- [x] 完成相关与最终完整后端回归，按实际文件配置对照基线检查新增 Ruff；如改公开 schema 则标准 OpenAPI/TypeScript 生成和编译。
- [x] 冻结最终源码和输入，独立运行本机压力/故障验收；报告通过与未验项，未完成的同步 I/O、跨机/Redis/Temporal 服务验收明确保留。
- [x] 更新交付文档并完成独立快速审查与精确凭据扫描，准备分支发布。

Task5 规格 R3、质量 R3 及最终代码增量复核通过。最终后端 8874 项通过、1 跳过；37 文件冻结后独立 64 请求故障注入通过，运行／模型／工作区峰值 2／2／1、最终名额归零。已将内部 pytest 临时库纳入主目录清理，保留了首次完整门禁 14 项测试替身兼容失败及修正证据。标准 OpenAPI 导出一致，36 个 Python 文件按源码行对照无新增 Ruff。

上述门禁后按已有授权提交并推送当前分支，不合并主分支、不创建 PR。提交内容不预记发布成功；发布后核远端 SHA、提交文件和干净状态，在本机 `release-verification.json` 记录结果。
