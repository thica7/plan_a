# 本机并发治理交付记录

实施始于 2026-10-28，最终本机验收日期为 2026-10-29。分支 `codex/pastoral-desktop`，基线 `f46684a582d56d49e11b0f914deaf9062f731cf1`。用户授权本机任务准入、共享状态、模型并发、缓存去重和压力测试；Docker 由另一台电脑部署，未增加 Kafka，未训练模型，未调用付费模型。

## 本轮实现

| 能力 | 实际接线与行为 |
| --- | --- |
| 准入与背压 | HTTP 接受前预留有界 ticket；新建、恢复、人工续跑、限定重做和实际 Temporal 活动共池。队列满返回 429／`Retry-After`；冲突和协调存储错误明确失败。控制型扫描／监控 workflow 不跨周期占名额。 |
| 共享执行归属 | 同机 SQLite 与 POSIX 文件锁约束全局／工作区／单 run；同区 FIFO，其他可运行工作区可以继续。活进程暂停不被 TTL 抢占；退出后可显式恢复。 |
| 共享状态 | 执行写绑定 token／generation，空闲控制写使用 revision CAS；事件 ID 在事务内分配，控制事件只追加。GET／list 不替远端 owner 修改状态，持久 SSE 按游标补读。 |
| 模型在途并发 | 普通生成、RAG 查询改写、原生模型搜索、重试和备用 provider 在实际 transport 前取得全局 slot，再预留发送预算。未发送时取消／超时归还对应预留；已发送的未知结果保守计账。独立 Search／Fetch 工具 API 不占生成池。 |
| 缓存并发去重 | 合格公共页和 query embedding 使用有界 single-flight，独立结果副本、取消隔离与异常清理。embedding 跨同进程 service 实例共享计算，检索结果仍按项目／工作区隔离并重验 canonical。价格、敏感 URL、强制刷新和独立 DeepSeek Fetch 绕过公共页复用。 |
| 可选 Redis | owner token 条件发布／释放，失效旧 owner 不覆盖新缓存或删除新锁。只完成共享假客户端合同，真实 Redis 服务待验。 |

主要实现为 [`execution_control.py`](../../backend/packages/infrastructure/execution_control.py)、[`execution_factory.py`](../../backend/packages/infrastructure/execution_factory.py)、[`run_journal.py`](../../backend/packages/memory/run_journal.py)、[`service.py`](../../backend/packages/orchestrator/service.py)、[`singleflight.py`](../../backend/packages/infrastructure/singleflight.py) 和实际模型／抓取／检索适配器。各 Agent 的入口说明见 [Agent 执行文档](../agent-execution.md#部署缓存和中断恢复)。

## 最终独立本机验收

先冻结 37 个变更源码、测试及公开示例配置文件，再独立执行 [`verify_local_concurrency.py`](../../backend/scripts/verify_local_concurrency.py)。最终源码增量压缩包 SHA256 为 `b59ebb82106c40366001a5dba7638017ba2ab31378e83ded7050ae73cb0fe9fe`；基线、逐文件哈希、环境和结果见[结构化记录](2026-10-28-local-concurrency-results.json)。本机环境为 macOS arm64、Python 3.11.15、SQLite 3.53.2。

两个真实 spawn 进程，共享临时 journal／锁，走实际 ASGI API → Runtime → RunService → coordinator。合成突发场景只替换图体／图检查点占位和模型 HTTP 响应；另一个恢复场景使用真实 LangGraph／SQLite 检查点。

| 64 请求故障注入 | 实测 |
| --- | --- |
| 接纳／拒绝 | 10／54；54 个 429 均有合法 `Retry-After` |
| 完成／排队过期 | 2／8 |
| 运行／模型／工作区峰值 | 2／2／1，与本场景配置一致 |
| 最终 queued／running／model | 0／0／0；pending 任务为 0，子进程全部 join |
| 普通生成／改写／原生模型搜索 | 各 2 次受控 transport |
| 公共页／embedding 冷突发 | 各 32 个等待者，仅一次实际 provider 计算；结果副本独立，限单进程 |

此场景刻意持有运行任务 0.65 秒，超过排队期限 0.5 秒，以验证拒绝、过期和清理。2 完成／8 过期不代表正常负载成功率。实际压力配置为运行 2、每区 1、模型 2、队列 8；与默认部署容量区分。

| 合成延迟 | 样本数 | P50 毫秒 | P95 毫秒 |
| --- | ---: | ---: | ---: |
| HTTP 创建 | 64 | 175.142 | 213.911 |
| 入队到领取，仅已开始 ticket | 2 | 71.860 | 87.998 |
| 接纳请求到 ticket 结束，含过期 | 10 | 601.899 | 1154.608 |
| 仅成功请求端到端 | 2 | 1154.440 | 1155.953 |

分位数按排序后线性插值计算。排队及成功样本仅各 2 条；以上是受控 ASGI／MockTransport 场景记录，不能外推真实模型、HTTP socket／反向代理吞吐或生产 SLA。

真实恢复场景在检查点确认持久化、待执行节点为 `collector` 后结束本次创建的 owner 子进程。新实例通过正式恢复入口取得 generation 1→2；Planner 完成次数保持 1→1，旧 token 在新 owner 活跃时及释放后均拒写。终态 `completed` 仅证明 demo 流程恢复，未断言报告内容合格。新实例 GET／list、实际 SSE 路由 body iterator 的持久游标补读及慢读取通过；未测试真实网络代理缓冲。

CLI 内另实际执行 10 项既有回归，覆盖重复消费者、工作区 FIFO、取消／超时／启动失败、revision、released token 和慢消费者。它们与新增 7 项集成测试及完整后端回归重叠，不作相加。最终独立工具确认主临时目录及内部 pytest `--basetemp` 均已删除。

## 回归与审查

- 五项实现逐项经过规格、质量双审，最终代码增量复核通过，新增 P1／P2 为 0。
- 首次完整回归为 14 失败、8860 通过、1 跳过：10 项旧 Settings 测试替身缺少默认关闭开关，4 项抓取替身未接新关键字。仅修 3 个测试文件，保留原结果断言，并新增 8 个参数值断言；对应三个模块红测 14 失败／392 通过，修后 406 通过。
- 审查另发现内部 pytest 临时库未归入主临时目录；仅增加 `--basetemp`，独立观察 9 个 SQLite 文件位于该目录，退出后父子目录均删除。早先失败和审查原件保留。
- 最终完整后端门禁：**8874 通过、1 跳过**，322.08 秒；220 条警告均为既有 FastAPI `on_event` 弃用提示。
- 36 个变更 Python 文件按实际 `backend/ruff.toml` 与基线逐源码行对照，新增 Ruff 诊断为 0；原 113 条为 106 条，未宣称全仓 lint 为零。
- 标准 OpenAPI 导出与已提交文件完全一致，前端生成接口文件未变，无需重新生成。
- 37 个最终冻结文件与 184 份上一轮验收原件哈希均一致。1572 个仓库文件的凭据模式扫描无命中，`.env` 未跟踪；该扫描不代表 Git 历史或运行时秘密审计。

## 使用与部署边界

新增协调默认关闭。启用须让所有 API／Worker 使用相同开关、journal 实际路径、锁目录和池配置；设置示例和停止／备份要求见[部署说明](../docker_deployment.md#同机执行协调显式启用)。不自动修改现用 `.env`。已有池配置不一致会拒绝使用；没有在线改池迁移工具。

使用已安装后端依赖的 Python，在仓库根目录运行：

```bash
# 仅预览，不读 .env、不创建数据库或结果文件
python backend/scripts/verify_local_concurrency.py
# 显式离线执行；只创建自己的临时环境，失败返回非零
python backend/scripts/verify_local_concurrency.py --execute --requests 64 --output data/artifacts/local-concurrency-result.json
```

以下仍需后续处理：

1. 在部署机验证真实 Redis Lua／TTL／断连、共享卷锁与恢复，以及 Postgres、Qdrant HTTP、Temporal 服务；本轮不执行 Docker。
2. 企业 memory store 不提供多实例业务真值；多人部署仍需持久企业存储，知识库多进程使用 Qdrant HTTP。本机 file lock 不提供跨主机高可用或外部调用 exactly-once。
3. 生成并发限制不等于服务商 RPM／TPM 调度；部分旧同步持久化、BGE／HTTP 路径仍未整链异步化。用真实负载测量后再定位瓶颈。
4. 本轮未重跑付费报告语义验收，不能将后端测试通过转成报告达标、RAG 合格或训练成功。既有内容失败及实验默认关闭状态保留。

代码按已有授权提交并推送当前分支；不合并主分支、不创建 PR。发布成功以推送后远端 SHA 核验为准，不以本记录代替发布事实。
