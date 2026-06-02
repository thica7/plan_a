# 02 · 分层架构 · Temporal 外层 + LangGraph 内层

> **核心论点**：Temporal 和 LangGraph **不是替代关系，是正交关系**。Temporal 管"长流程 / 周期监控 / 审批 / 失败恢复"，LangGraph 管"单次 run 内的 Agent 推理图"。两者**包在一起**才是企业级架构。

## 2.1 为什么不替代

### v3 草案的错误判断

```
v3 第 3 章原话：
"M3: Temporal 接管编排 / M4: LangGraph 退役"
```

**为什么是错的（Codex 评审已指出）**：
1. LangGraph 的 Send fan-out / RedoScope / HITL interrupt / 节点级 trace 是 plan_a 已经做得很好的护城河
2. 用 Temporal 重写 = 重新造轮子，没有收益
3. Temporal 真正擅长的是"长流程编排"，不是"Agent DAG"
4. 强行替代 = 重新在 Temporal 里手写 Agent 图

### 正确认知：两个工具擅长不同的事

| 维度 | Temporal | LangGraph |
|---|---|---|
| 设计目标 | 长时运行的业务流程 | 短时多步 Agent 推理 |
| 状态持久化 | 一等公民（自动 replay） | 需要 checkpointer |
| HITL | Signal + Activity（更稳健） | interrupt（够用） |
| Fan-out 并发 | 支持但需手写 asyncio | Send 内置 |
| 状态合并 | 手写 | Annotated reducer 自动 |
| 失败重试 | 一等公民（指数退避 / 熔断） | 需手写 |
| 长任务（24h+） | 一等公民 | 受限于进程 |
| 周期任务 | 一等公民（CronSchedule） | 不支持 |
| 审批队列 | 一等公民（Signal） | 需手写 |
| Agent 推理图可视化 | 弱（Web UI 是 workflow 视图） | 强（graph.png + Studio） |
| 节点级 trace 集成 | 通过 OTel | 内置 |

**结论**：两者擅长的是**完全不同的层级的问题**。

## 2.2 正确的分层架构

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║                    Temporal Workflow（外层）                       ║
║                                                                   ║
║   长流程 / 跨 run / 企业级运营                                     ║
║   ─────────────────────────────────────                           ║
║   ─ ScheduledScanWorkflow（每周扫一次 competitor）                ║
║   ─ ApprovalWorkflow（生成报告 → 主管审批 → 发布）                ║
║   ─ MonitorWorkflow（持续监控，发现异常告警）                     ║
║   ─ BatchAnalysisWorkflow（批量分析多个 topic）                   ║
║   ─ DataIngestionWorkflow（每日采集证据库）                       ║
║                                                                   ║
║   通用能力：                                                       ║
║   ─ Cron 调度                                                     ║
║   ─ 失败重试（指数退避）                                          ║
║   ─ 长任务断点续跑                                                ║
║   ─ Signal 异步通信（审批 / HITL）                                ║
║   ─ Workflow 版本管理                                             ║
║                                                                   ║
║   ┌────────────────────────────────────────────────────┐         ║
║   │   ▼ 调用 Activity                                   │         ║
║   │                                                      │         ║
║   │   每个 Activity = 一次 run 的完整 Agent 推理         │         ║
║   │   ┌──────────────────────────────────────────────┐ │         ║
║   │   │                                                │ │         ║
║   │   │       LangGraph StateGraph（内层）              │ │         ║
║   │   │                                                │ │         ║
║   │   │   单次 run 内 / Agent 推理图                   │ │         ║
║   │   │   ─────────────────────────────────            │ │         ║
║   │   │   planner → collector_dispatch                 │ │         ║
║   │   │     → collector × N（Send fan-out）            │ │         ║
║   │   │     → analyst × N → comparator                 │ │         ║
║   │   │     → reflector → redteam → writer → qa        │ │         ║
║   │   │     → qa_hitl → 5 级 RedoScope                 │ │         ║
║   │   │                                                │ │         ║
║   │   │   通用能力：                                    │ │         ║
║   │   │   ─ Send fan-out 并发                          │ │         ║
║   │   │   ─ 5 级 RedoScope 路由                        │ │         ║
║   │   │   ─ HITL interrupt                             │ │         ║
║   │   │   ─ 节点级 trace（trace_spans 表）             │ │         ║
║   │   │   ─ checkpointer                               │ │         ║
║   │   │                                                │ │         ║
║   │   └──────────────────────────────────────────────┘ │         ║
║   │                                                      │         ║
║   └────────────────────────────────────────────────────┘         ║
║                                                                   ║
╚══════════════════════════════════════════════════════════════════╝
```

## 2.3 各层职责对照

### Temporal 外层 · 解决"运营时"问题

```python
# workflows/scheduled_scan.py
@workflow.defn
class ScheduledScanWorkflow:
    """每周扫一次某 Workspace 的所有 Project competitor"""
    
    @workflow.run
    async def run(self, workspace_id: str) -> ScanReport:
        # 1. 获取 Workspace 配置
        config = await workflow.execute_activity(
            get_workspace_config,
            workspace_id,
            schedule_to_close_timeout=timedelta(seconds=10),
        )
        
        # 2. 并发扫描每个 Project
        results = []
        for project in config.projects:
            try:
                result = await workflow.execute_activity(
                    run_competitor_analysis,  # ← 这个 activity 内部跑 LangGraph
                    project.topic,
                    project.competitors,
                    schedule_to_close_timeout=timedelta(hours=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                results.append(result)
            except ActivityError as e:
                # 通知失败但不阻塞其他 project
                await workflow.execute_activity(notify_failure, project.id, str(e))
        
        # 3. 聚合 + 通知
        report = await workflow.execute_activity(aggregate_scan_report, results)
        await workflow.execute_activity(send_notification, workspace_id, report)
        return report
```

```python
# workflows/approval.py
@workflow.defn
class ReportApprovalWorkflow:
    """报告生成后等审批，通过则发布"""
    
    @workflow.run
    async def run(self, report_id: str) -> str:
        # 1. 触发分析（内部用 LangGraph）
        result = await workflow.execute_activity(
            run_competitor_analysis,
            report_id,
            schedule_to_close_timeout=timedelta(hours=2),
        )
        
        # 2. 等审批（Signal 可挂起 24h+）
        await workflow.wait_condition(
            lambda: self.approval_decision is not None,
            timeout=timedelta(days=3),
        )
        
        if self.approval_decision == "approved":
            await workflow.execute_activity(publish_report, report_id)
            return "published"
        else:
            return "rejected"
    
    @workflow.signal
    async def approve(self, comment: str):
        self.approval_decision = "approved"
    
    @workflow.signal
    async def reject(self, reason: str):
        self.approval_decision = "rejected"
```

### LangGraph 内层 · 解决"推理时"问题

```python
# workflows/activities.py
@activity.defn
async def run_competitor_analysis(
    topic: str, 
    competitors: list[str],
) -> RunResult:
    """单次 run 的 Activity，内部调用 LangGraph"""
    
    # plan_a 现有的 LangGraph StateGraph 完全保留
    graph = build_real_analysis_graph(service)
    
    initial_state = {
        "run_id": generate_run_id(),
        "topic": topic,
        "competitors": competitors,
    }
    
    final_state = await graph.ainvoke(initial_state)
    
    return RunResult(
        run_id=final_state["run_id"],
        report_md=final_state["report_md"],
        metrics=final_state["metrics"],
    )
```

LangGraph 内部不变（plan_a 现有）：
```python
# packages/orchestrator/graph.py（不动）
def build_real_analysis_graph(service):
    graph = StateGraph(GraphState)
    # ... plan_a 现有的所有节点和边
    return graph.compile()
```

## 2.4 这种分层的好处

### 好处 1：plan_a 的护城河完全保留
- 5 级 RedoScope ✅
- Send fan-out ✅
- HITL interrupt ✅
- 节点级 trace ✅
- KB cache ✅

### 好处 2：Temporal 解决企业级痛点
- 周期监控（每天/每周自动跑）
- 审批工作流（提报告 → 主管审批 → 发布）
- 长任务恢复（24h+ 任务断点续跑）
- 失败告警（API 限流自动通知 + 重试）

### 好处 3：渐进式引入
- Phase 1-3：纯 LangGraph，不引入 Temporal
- Phase 4：Postgres 替代 SQLite，仍然纯 LangGraph
- Phase 5：才引入 Temporal 外层
- 任何阶段都可以停下来交付

### 好处 4：演化友好
- LangGraph 节点内部可以单独升级（如 Pydantic-AI 替换手搓 ReAct）
- Temporal Workflow 可以独立升级（不影响推理图）
- 双层独立测试

## 2.5 引入时机

| 阶段 | 周期 | Temporal | LangGraph |
|---|---|---|---|
| Phase 1-3 | W0-W10 | ❌ 不引入 | ✅ 现有 |
| Phase 4 | 10w-5m | ❌ 不引入 | ✅ 现有 |
| Phase 5 | 5m+ | ✅ 引入外层 | ✅ 内层不变 |

**绝不在 Phase 1-4 引入 Temporal**。理由：
- 单 run 工具不需要 Temporal
- 学习曲线 + 运维成本不合理
- LangGraph 已经够用

## 2.6 Phase 5 引入 Temporal 的具体步骤

### Step 1: 部署 Temporal Server
- 自建 Helm chart（推荐 1 个 Server + 1-2 个 Worker）
- 或用 Temporal Cloud（成本高但运维省）

### Step 2: 把现有 LangGraph 调用包成 Activity
```python
@activity.defn
async def run_competitor_analysis(topic: str, competitors: list[str]) -> RunResult:
    return await existing_langgraph_invoke(topic, competitors)
```
**这一步不改 LangGraph 一行代码**。

### Step 3: 写第一个 Workflow（最简单的：单次 run 包一层）
```python
@workflow.defn
class SingleRunWorkflow:
    @workflow.run
    async def run(self, topic, competitors):
        return await workflow.execute_activity(
            run_competitor_analysis,
            topic, competitors,
        )
```
价值：得到 deterministic replay + 自动重试 + Web UI 监控。

### Step 4: 增加业务 Workflow
- ScheduledScanWorkflow（周期）
- ApprovalWorkflow（审批）
- BatchAnalysisWorkflow（批量）
- MonitorWorkflow（监控）

### Step 5: 双栈共存验证（4-6 周）
- 80% 流量走 SingleRunWorkflow（Temporal 包装）
- 20% 流量直跑 LangGraph（兜底）
- 监控 SLO，验证 Temporal 不引入 regression

### Step 6: 切流到 100% Temporal Workflow
- 直接调 LangGraph 的 API 弃用
- 所有 run 走 Temporal Workflow

**整个迁移过程 LangGraph 一行代码不改**。

## 2.7 反例：什么时候真的可以替代

理论上有一个场景可以让 Temporal 替代 LangGraph：**Agent 的 ReAct 循环本身就要持久化 + replay**。

但实际上：
- plan_a 的 ReAct max_turns ≤ 6，单次 run 几分钟，不需要持久化
- 如果真要 replay 单次 run，LangGraph 的 checkpointer 已经够用
- 只有当 Agent 推理本身要跑几小时甚至几天时，才考虑用 Temporal Workflow 替代 LangGraph

**这种场景在我们项目里不存在**。所以正确策略永远是"包在外层"。

## 2.8 与 v3 草案的对比

```
v3 草案（错）：
  Temporal 替代 LangGraph
  M3 LangGraph 退役
  M4 重写所有节点为 Workflow

final（对）：
  Temporal 外层 + LangGraph 内层
  Phase 5 才引入 Temporal
  LangGraph 永不退役
  两者正交，各自演化
```

## 2.9 Phase 5 的关键决策

### 决策 1：Temporal 自建 vs Temporal Cloud

| 维度 | 自建 | Cloud |
|---|---|---|
| 月成本 | ~¥3000（K8s + 运维） | ~¥5000-10000（按用量） |
| 运维 | 自己负责 | Temporal 团队 |
| 网络延迟 | 内网 < 1ms | ~50ms（中国大陆） |
| 数据合规 | 自主可控 | 受 Temporal 政策约束 |
| 适合阶段 | Phase 5 起步 | Phase 5 + 企业 SaaS |

**推荐**：Phase 5 起步用自建，规模上来后评估 Cloud。

### 决策 2：Workflow 边界划分

**好的边界**：
- ScheduledScanWorkflow（一次扫描一个 Workspace）
- ApprovalWorkflow（一份报告的审批生命周期）
- MonitorWorkflow（一个 Workspace 的持续监控）

**不好的边界**：
- TooBroadWorkflow（包含太多业务，难维护）
- TooNarrowWorkflow（每个 Activity 一个 Workflow，过度设计）

### 决策 3：Workflow vs Activity 拆分

**Workflow**：业务流程，需要 deterministic
**Activity**：与外部交互（DB / API / LLM），可以非 deterministic

```
ScheduledScanWorkflow
├── Activity: get_workspace_config (DB)
├── Activity: run_competitor_analysis (LangGraph 调用)
├── Activity: aggregate_scan_report (CPU 计算)
└── Activity: send_notification (飞书 API)
```

## 2.9.5 ★ Temporal Replay 限制 + 幂等性设计（v2.0 新增）

### 关键认知（Codex §5.6）

```
Temporal replay 不会重放 LangGraph 内部步骤。
Temporal 记录的是 Activity 结果。
如果 LangGraph 作为一个 Activity 执行，失败重试可能重跑整个图。
因此需要 run_id 幂等、checkpoint resume、evidence 去重、report version 幂等创建。
```

这是 v1.0 漏掉的关键设计点。Phase 5 引入 Temporal 时如果不知道这个坑，会出现：
- Activity 重试 → LangGraph 重跑 → 重复写 evidence / report version
- 数据不一致 → 用户投诉

### 解决方案：稳定 ID + INSERT ON CONFLICT

#### 方案 1: Activity 内部全部写入幂等

```python
@activity.defn
async def persist_evidence_activity(run_id: str) -> int:
    sources = await get_pending_sources(run_id)
    for source in sources:
        evidence_id = compute_evidence_id(
            canonical_url=normalize_url(source.url),
            content_hash=source.content_hash,
            competitor_id=source.competitor_id,
            dimension_key=source.dimension,
        )
        await pg.execute("""
            INSERT INTO evidence_records (id, ...) VALUES ($1, ...)
            ON CONFLICT (id) DO UPDATE SET
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                seen_count = evidence_records.seen_count + 1
        """, evidence_id, ...)

@activity.defn
async def create_report_version_activity(run_id: str) -> str:
    """5 维分组键保证幂等：重试不创建重复版本"""
    return await pg.fetchval("""
        INSERT INTO report_versions (...)
        VALUES (...)
        ON CONFLICT (workspace_id, project_id, topic_normalized, 
                     competitor_layer, competitor_set_hash, version_number) 
        DO UPDATE SET run_id = EXCLUDED.run_id
        RETURNING id
    """, ...)
```

#### 方案 2: run_id 幂等键

```python
@activity.defn
async def create_run_activity(request: AnalysisRequest) -> str:
    return await pg.fetchval("""
        INSERT INTO runs (id, workspace_id, idempotency_key, ...)
        VALUES (gen_random_uuid(), $1, $2, ...)
        ON CONFLICT (idempotency_key) DO UPDATE SET status = runs.status
        RETURNING id
    """, request.workspace_id, request.idempotency_key, ...)
```

#### 方案 3: HITL 用 Signal 不用 Activity 阻塞

```python
@workflow.defn
class CompetitiveIntelWorkflow:
    def __init__(self):
        self.hitl_decision: dict | None = None
    
    @workflow.run
    async def run(self, request):
        # ❌ 错误：让 Activity 阻塞 7 天
        # decision = await workflow.execute_activity(wait_for_human, schedule_to_close_timeout=timedelta(days=7))
        
        # ✅ 正确：Workflow 用 wait_condition + Signal
        await workflow.execute_activity(
            send_approval_notification, ...,
            schedule_to_close_timeout=timedelta(seconds=30),
        )
        await workflow.wait_condition(
            lambda: self.hitl_decision is not None,
            timeout=timedelta(days=3),
        )
    
    @workflow.signal
    async def submit_decision(self, decision: dict):
        self.hitl_decision = decision
```

### 检查清单（Phase 4 引入 Temporal 前）

- [ ] 所有 evidence 写入用稳定 evidence_id + ON CONFLICT
- [ ] 所有 claim 写入用稳定 claim_id + ON CONFLICT
- [ ] ReportVersion 用 (workspace, project, topic, layer, set_hash, version) 唯一约束
- [ ] Run 表有 idempotency_key 唯一索引
- [ ] LangGraph 节点对重试是幂等的
- [ ] HITL 等待用 Signal 不用 Activity
- [ ] 关键 Activity 有合理的 schedule_to_close_timeout

如果任一条不满足，Phase 4 引入 Temporal 会出问题。

### 关键文档交叉引用

- 稳定 ID 算法：[05_DATA_MODELS.md](./05_DATA_MODELS.md) §5.3
- ON CONFLICT 写入路径：[05_DATA_MODELS.md](./05_DATA_MODELS.md) §5.4
- Temporal Workflow 完整示例：[01_EXECUTION_ROADMAP_5_PHASES.md](./01_EXECUTION_ROADMAP_5_PHASES.md) §1.6

## 2.10 对评分的影响

| 评分维度 | Phase 1-3（无 Temporal）| Phase 5（加 Temporal） |
|---|---|---|
| A2 DAG 可追溯 | LangGraph 静态图 + trace | + Temporal Web UI |
| A4 反馈闭环 | 5 级 RedoScope（LangGraph） | + 跨 run 反馈（Temporal） |
| B4 系统稳定性 | LangGraph fallback | + Temporal 自动重试 |
| B5 前瞻性 | RedTeam + EvidenceGap | + 周期监控 + 审批工作流 |
| C2 业务价值 | 单 run 工具 | + 企业 SaaS 形态 |

Phase 5 引入 Temporal 后评分预期 +2-3 分（92-94 范围）。

## 2.11 一句话总结

> **Temporal 不是 LangGraph 的对手，是它的搭档。前 10 周不需要 Temporal，企业化阶段才引入；引入时不动 LangGraph 一行代码，只是在外层加一个调度壳。**

---

> 下一步：阅读 [03_PRODUCT_FEATURES.md](./03_PRODUCT_FEATURES.md) 了解 Evidence Center / ReportVersion / Workspace 等产品化特性。
