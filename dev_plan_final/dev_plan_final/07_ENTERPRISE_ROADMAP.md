# 07 · 企业化路线（Phase 4-5，12 周后）· v2.0 修订

> **v2.0 修订**：原 v1.0 思路是"Phase 4 才迁移到 Postgres"，被 Codex 评审指出会落入"早期 SQLite run 工具，后期痛苦迁移"陷阱。v2.0 把数据骨架（PG + Workspace/Project + EvidenceRecord + ReportVersion + AuditLog skeleton）前置到 Phase 1。
>
> **本章新职责**：Phase 4 不再做"PG 迁移"，而是做 **Temporal 薄壳引入 + 真多租户启用 + pgvector + Source Registry**；Phase 5 做完整企业治理（RBAC + 监控告警 + 合规 + Langfuse / OTel）。

## 7.1 总览（v2.0 修订）

```
Phase 4 (W10-W12 + 后续)   Temporal 薄壳 + 真多租户
├─ Temporal Server 部署
├─ CompetitiveIntelWorkflow（薄壳，包 LangGraph）
├─ ApprovalWorkflow 原型
├─ Multi-Workspace 真启用（Phase 1 已建表，仅 Workspace 选择器）
├─ pgvector 索引引入（embedding 检索）
└─ Source Registry（数据源注册中心）

注：Phase 4 不再做"PG 迁移"，因为 Phase 1 已建立完整 PG schema。

Phase 5 (5-12m)   完整企业治理
├─ 完整 RBAC（OPA / Cerbos）
├─ AuditLog 强化（不可篡改 + 全事件覆盖 + 审计 UI）
├─ ScheduledScanWorkflow（周期监控）
├─ MonitorWorkflow（持续监控 + 异常告警）
├─ BatchAnalysisWorkflow（批量分析）
├─ DataIngestionWorkflow（每日采集）
├─ Multi-tenant 配额管理
├─ Langfuse / OTel 全栈观测
├─ Token / cost governance
├─ PII redaction（Microsoft Presidio）
├─ Model policy
└─ Report publish workflow（含合规检查）
```

每阶段独立交付价值。Phase 4 不再有"数据迁移"压力，节省 1 月。

## 7.2 Phase 4 · 企业化数据层（10w-5m）

### 关键模块

#### 4.1 Postgres 替代 SQLite（M3-M4）

**为什么换**：
- SQLite 单写并发限制（高峰期阻塞）
- 没有原生 JSONB 索引（查询慢）
- 没有 vector 类型（要装 sqlite-vss 别扭）
- 不支持 Row-Level Security（多租户必需）

**为什么 Postgres + pgvector 而非 Neo4j**：
- pgvector 满足 RAG 需求（不需要图查询）
- Postgres 是团队熟悉的（不引入 Cypher）
- JSONB 替代图节点（足够灵活）
- 单库简化运维

**实现要点**：
```python
# 三表并存策略：1 个月双写过渡
async def write_evidence(evidence: EvidenceRecord):
    # 双写：SQLite + Postgres
    await sqlite_store.put(evidence)
    await pg_store.put(evidence)

# 验证一致性
async def verify_consistency():
    # 每天对比两库 diff，差异 = 0 才切流
    ...

# 切流：100% 读 PG，停止写 SQLite
```

**详细数据迁移代码**：见 [05_DATA_MODELS.md](./05_DATA_MODELS.md) §5.9。

**工时**：3-4 周（含双写过渡）

#### 4.2 Workspace / Project / Competitor Library（M4-M5）

详见 [05_DATA_MODELS.md](./05_DATA_MODELS.md) §5.3-5.5。

关键点：
- Phase 1-3 时所有数据自动归到 `default` workspace
- 引入时 zero-downtime（运行中的 run 不受影响）
- 前端加 Workspace 选择器

**工时**：2-3 周

#### 4.3 RBAC（M5）

```python
# packages/auth/rbac.py（Phase 4 新增）
from enum import Enum

class Role(str, Enum):
    OWNER = "owner"      # 所有权限 + 删 workspace
    ADMIN = "admin"      # 管理成员 + 编辑 workspace
    EDITOR = "editor"    # 创建/编辑 project + run analysis
    VIEWER = "viewer"    # 只读

# OPA 策略（详见 05 文档）
async def check_permission(user_id, action, target):
    decision = await opa_client.evaluate(
        policy="workspace.allow",
        input={"user": user, "action": action, "target": target}
    )
    return decision.result
```

**集成到 API 层**：
```python
@router.post("/projects")
async def create_project(
    request: CreateProjectRequest,
    user: User = Depends(get_current_user),
):
    if not await check_permission(user.id, "create_project", workspace):
        raise HTTPException(403, "Insufficient permissions")
    # ...
```

**工时**：2 周

#### 4.4 AuditLog（M5）

详见 [05_DATA_MODELS.md](./05_DATA_MODELS.md) §5.8。

关键点：
- 所有写操作都通过中间件 emit audit event
- audit_events 表 `REVOKE UPDATE, DELETE`（不可篡改）
- 前端加 Audit View（按 actor / target / time 筛选）

**工时**：1-2 周

#### 4.5 Source Registry（M5）

详见 [05_DATA_MODELS.md](./05_DATA_MODELS.md) §5.7。

关键点：
- 替换 plan_a 现有 hard-coded source 列表
- 集中管理 robots.txt 合规白名单
- 每个 source 有 reliability_score（影响 RawSource confidence）

**工时**：2 周

#### 4.6 Report History 跨 Workspace（M5-M6）

```
ReportVersion (Phase 3 引入)：单 Project 内的版本
   ↓ Phase 4 升级
Report History：跨 Project / Workspace 的全局检索
   ├─ 按 topic 跨 Workspace 找类似报告
   ├─ 报告引用关系图（A 引用 B 引用 C）
   └─ 报告全文搜索（Meilisearch）
```

**工时**：2 周

### Phase 4 总工时

```
Postgres 迁移        4 周
Workspace/Project    3 周
RBAC                 2 周
AuditLog             1 周
Source Registry      2 周
Report History       2 周
─────────────────────
总计                 14 周（约 3.5 月）
团队 3 人              ≈ 5 周（10 周后第 5-6 月完成）
```

### Phase 4 评分加成

| 评分维度 | Phase 3（W10） | Phase 4 完成 |
|---|---|---|
| C2 业务价值 | 业务工作台 | + Workspace 多租户 |
| C3 交互 | 单工作台 | + RBAC 角色视图 |
| E1 合规 | robots tool | + Source Registry 中心化 |
| E2 数据隐私 | 基础 | + AuditLog + Workspace 隔离 |
| **预期评分** | 88-90 | 90-92 |

## 7.3 Phase 5 · 长流程编排（5m-12m）

### Temporal 引入步骤

详见 [02_ARCHITECTURE_LAYERED.md](./02_ARCHITECTURE_LAYERED.md) §2.6。

#### Step 1: Temporal Server 部署（M5-M6）

**自建 Helm chart**：
```yaml
# helm/temporal/values.yaml
server:
  replicaCount: 1  # Phase 5 起步 1 个，规模上来后扩
  resources:
    requests: { cpu: 1000m, memory: 2Gi }
    limits: { cpu: 2000m, memory: 4Gi }

cassandra:
  enabled: false  # 用 Postgres 作 datastore
  
postgresql:
  enabled: true
  databases: [temporal, temporal_visibility]

prometheus:
  enabled: true
```

**工时**：2 周（含 K8s 部署 + 监控）

#### Step 2: 第一个 Workflow（M6-M7）

```python
# workflows/single_run.py（最简包装）
@workflow.defn
class SingleRunWorkflow:
    @workflow.run
    async def run(self, request: AnalysisRequest) -> RunResult:
        # 调 LangGraph（plan_a 现有不变）
        return await workflow.execute_activity(
            run_competitor_analysis,
            request,
            schedule_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
```

价值：
- 自动重试 + 失败恢复
- Web UI 可视化
- deterministic replay

**工时**：1 周

#### Step 3: ScheduledScanWorkflow（M7-M8）

```python
@workflow.defn
class ScheduledScanWorkflow:
    """每周扫一次 Workspace 的所有 Project"""
    
    @workflow.run
    async def run(self, workspace_id: str, scan_config: ScanConfig):
        projects = await workflow.execute_activity(
            get_active_projects, workspace_id,
        )
        
        results = []
        for project in projects:
            try:
                result = await workflow.execute_activity(
                    run_competitor_analysis,
                    project_to_request(project),
                    schedule_to_close_timeout=timedelta(hours=3),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(seconds=30),
                        backoff_coefficient=2.0,
                    ),
                )
                results.append(result)
            except ActivityError as e:
                await workflow.execute_activity(
                    notify_failure, project.id, str(e),
                )
        
        report = await workflow.execute_activity(
            aggregate_scan_report, results,
        )
        await workflow.execute_activity(
            send_workspace_notification, workspace_id, report,
        )
        return report
```

**Cron 调度**（Temporal 内置）：
```python
# 启动 ScheduledScanWorkflow
await client.start_workflow(
    ScheduledScanWorkflow.run,
    args=[workspace_id, scan_config],
    id=f"scheduled-scan-{workspace_id}",
    task_queue="scheduler",
    cron_schedule="0 2 * * 1",  # 每周一凌晨 2 点
)
```

**工时**：2 周

#### Step 4: ApprovalWorkflow（M8）

```python
@workflow.defn
class ReportApprovalWorkflow:
    """报告生成 → 主管审批 → 发布"""
    
    def __init__(self):
        self.approval: str | None = None
    
    @workflow.run
    async def run(self, report_id: str, approver_ids: list[str]) -> str:
        # 1. 触发分析
        result = await workflow.execute_activity(
            run_competitor_analysis_for_report,
            report_id,
        )
        
        # 2. 通知审批者
        await workflow.execute_activity(
            send_approval_request, approver_ids, report_id,
        )
        
        # 3. 等审批（最多挂起 3 天）
        try:
            await workflow.wait_condition(
                lambda: self.approval is not None,
                timeout=timedelta(days=3),
            )
        except asyncio.TimeoutError:
            await workflow.execute_activity(
                send_approval_timeout, approver_ids, report_id,
            )
            return "timeout"
        
        if self.approval == "approved":
            await workflow.execute_activity(publish_report, report_id)
            return "published"
        else:
            return "rejected"
    
    @workflow.signal
    async def approve(self, approver_id: str, comment: str = ""):
        self.approval = "approved"
    
    @workflow.signal
    async def reject(self, approver_id: str, reason: str):
        self.approval = "rejected"
```

**工时**：2 周

#### Step 5: MonitorWorkflow（M8-M9）

```python
@workflow.defn
class MonitorWorkflow:
    """持续监控某 Project，发现异常告警"""
    
    @workflow.run
    async def run(self, project_id: str):
        # 长时运行 workflow，从启动到主动 cancel
        prev_report = None
        
        while True:
            # 1. 跑分析
            result = await workflow.execute_activity(
                run_competitor_analysis_for_project, project_id,
                schedule_to_close_timeout=timedelta(hours=2),
            )
            
            # 2. 检测异常
            if prev_report:
                anomalies = await workflow.execute_activity(
                    detect_anomalies, prev_report, result,
                )
                if anomalies:
                    await workflow.execute_activity(
                        send_anomaly_alert, project_id, anomalies,
                    )
            
            prev_report = result
            
            # 3. 等到下一周期
            await asyncio.sleep(7 * 24 * 3600)  # 7 天
```

**工时**：2 周

#### Step 6: 双栈共存验证（M9）

- 80% 流量走 Temporal Workflow 包装
- 20% 流量直跑 LangGraph（兜底）
- 监控 SLO 4 周

**工时**：4 周（与上面 Step 1-5 部分重叠）

#### Step 7: 切流到 100% Temporal（M10-M11）

- 直跑 LangGraph 的 API 弃用
- 所有 run 走 Temporal Workflow
- 退役兜底路径

**工时**：1-2 周

### Phase 5 总工时

```
Temporal Server 部署          2 周
SingleRunWorkflow             1 周
ScheduledScanWorkflow         2 周
ApprovalWorkflow              2 周
MonitorWorkflow               2 周
BatchAnalysisWorkflow         1 周
DataIngestionWorkflow         1 周
双栈共存 + 切流               4 周
─────────────────────────────
总计                          15 周（约 4 月）
团队 3-4 人                   ≈ 4-5 周（M9-M11）
```

### Phase 5 评分加成

| 评分维度 | Phase 4 完成 | Phase 5 完成 |
|---|---|---|
| A2 DAG 可追溯 | LangGraph trace | + Temporal Web UI |
| A4 反馈闭环 | 5 级 RedoScope | + 跨 run 反馈监控 |
| B4 系统稳定性 | LangGraph fallback | + Temporal 自动重试 + 长任务恢复 |
| B5 前瞻性 | RedTeam | + 周期监控 + 审批 + 多租户 |
| C2 业务价值 | 多租户工作台 | + 真企业 SaaS 形态 |
| **预期评分** | 90-92 | 92-94 |

## 7.4 不做的（避免过度设计）

| 项 | 不做原因 |
|---|---|
| Kafka Event Sourcing | Postgres + AuditLog 已够 |
| Neo4j 知识图谱 | pgvector 满足需求 |
| RDF/OWL 本体推理 | 业务不需要 |
| Yjs 多人实时协作 | 评论 + RBAC 够用 |
| GraphQL | REST + SSE 够用 |
| TLA+ 形式化验证 | 不是评分项 |
| 联邦学习 | 单 Workspace 不需要 |
| 因果推理 do-calculus | 学术方向 |
| 自适应 Schema 演化 | 手动 migration 够用 |
| Pydantic-AI 全栈替换 | 渐进替换即可 |

## 7.5 团队扩展

```
Phase 1-3（10 周）：1.5-2 人
├─ 全栈 1 人
└─ 兼职前端 + QA 0.5 人

Phase 4（M3-M5）：3 人
├─ 后端 1 人（Postgres 迁移）
├─ 全栈 1 人（Workspace + RBAC）
└─ SRE 1 人（K8s + 监控）

Phase 5（M5-M11）：4 人
├─ 后端 2 人（Temporal + Workflow）
├─ 全栈 1 人（前端 + 审批 UI）
└─ SRE 1 人（Temporal 运维）
```

## 7.6 成本预算

```
Phase 4 基础设施新增：
├─ Postgres RDS         ¥2000/月
├─ K8s 集群             ¥5000/月（4 节点）
├─ Meilisearch          ¥500/月
└─ pgvector / Redis     已含
─────────────────────────────────
小计                    ¥7500/月

Phase 5 基础设施新增：
├─ Temporal Server      ¥3000/月（自建 1+1 worker）
├─ Workflow 调度成本    ¥2000/月（频繁 LLM 调用）
└─ 监控告警工具         ¥1500/月
─────────────────────────────────
小计                    ¥6500/月

Phase 4-5 总基础设施：  ¥14000/月

人力（按 ¥30k/月/人）：
├─ Phase 4 (3 人 × 3 月)  = ¥270,000
└─ Phase 5 (4 人 × 6 月)  = ¥720,000
─────────────────────────────────
人力总计                  ¥990,000

LLM API（按 1000 runs/月，平均 ¥3/run）：
└─ ¥3,000/月 × 9 月       = ¥27,000

Phase 4-5 总预算：       ≈ ¥120 万
```

## 7.7 Go/No-Go 决策

每个阶段末有 Go/No-Go：

### Phase 4 末（M5）
- ✅ Postgres 切流 100%
- ✅ Workspace/Project/Competitor Library 全部上线
- ✅ RBAC + AuditLog 跑通
- ✅ Source Registry 替代 hard-coded

如不达标 → 推迟 Phase 5。

### Phase 5 末（M11）
- ✅ Temporal Server 稳定运行 ≥ 3 月
- ✅ 4 个 Workflow 全部跑通
- ✅ 100% 流量走 Temporal
- ✅ deterministic replay 验证字节级一致

如不达标 → 保留双栈，标记"Temporal Workflow 部分上线"。

## 7.8 何时不进入 Phase 4-5

满足以下任一 → **不要启动 Phase 4-5**：

1. Phase 3 答辩通过后无后续投入预算
2. 团队人员不足（< 3 人）
3. 业务方满意于 Phase 3 雏形
4. 6 个月内有更优先的业务交付

**Phase 3 是稳定终态**，不一定要往企业化走。

## 7.9 与 v3 远景的对比

```
v3 远景（dev_plan_v3/）想做的：
├─ Temporal 替代 LangGraph    ❌ final 不做
├─ Pydantic-AI 全栈            ❌ final 仅渐进
├─ Kafka Event Sourcing       ❌ final 不做
├─ Neo4j + RDF/OWL            ❌ final 不做
├─ Yjs 多人协作               ❌ final 不做
├─ GraphQL                    ❌ final 不做
├─ TLA+ 形式化验证            ❌ final 不做
├─ 自适应 Schema 演化         ❌ final 不做
├─ 多 Agent 互评博弈          ❌ final 用 RedTeam 即可
├─ 因果推理                   ❌ final 不做
├─ 联邦协作                   ❌ final 不做
└─ 200 条黄金集 + LLM-judge   ❌ final 用 30 + 50 + 100 渐进

v3 远景中保留的核心思想：
├─ Temporal 外层（Phase 5）   ✅
├─ Pydantic-AI 渐进（Phase 3+） ✅
├─ Postgres + pgvector        ✅
├─ AgentOps 思想              ✅
└─ K8s + ArgoCD               ✅
```

## 7.10 一句话总结

> **Phase 4-5 是把雏形升级为企业产品，时间节奏是 6-12 个月，不是 6 个月一口气堆所有东西。Temporal 是 Phase 5 的事，不是 Phase 1-3 的事。**

---

> 下一步：阅读 [08_RISK_AND_DECISIONS.md](./08_RISK_AND_DECISIONS.md) 了解风险登记和关键决策记录。
