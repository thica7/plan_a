# Architecture-First Execution Plan

Last updated: 2026-06-07

## 定位

这份方案只回答一个问题：

> 接下来如果用户明确要推进“架构上的东西”，应该怎么做，才不会继续变成这里补一下、那里补一下。

它不替代：

- `dev_plan_final/dev_plan_final/*`
- `docs/enterprise_execution_master_plan.md`
- `docs/checkpoint4_architecture_contract_consolidation_plan.md`
- `D:/codex_workspace/websearch_v2/clean_research_pipeline_rewrite_plan.md`

它是这些方案之上的执行收口顺序。

## 当前判断

当前项目已经不是“没有功能”的状态，而是进入了 Phase 5 企业产品化阶段。

已经比较扎实的主干：

- LangGraph 内层 Agent DAG。
- Temporal 外层 workflow shell。
- Clean Research Pipeline 数据采集/抽取/准入边界。
- Enterprise Store 的 workspace/project/run/evidence/claim/report/audit。
- Source Identity Resolver。
- ReportVersion scope。
- Quality Finding Matrix。
- 报告查看、source token 跳转、trace、decision replay、EvalOps 基础。

当前最大的架构风险不是再缺一个 extractor 或一个 UI 面板，而是：

- HITL 生命周期还没有成为统一契约。
- Temporal / LangGraph / RunService / Enterprise Store 的职责边界还不够硬。
- Observability / Langfuse / OTel / audit / decision replay 还没有一份统一 telemetry contract。
- 质量、审批、发布、人工修正、memory feedback 之间还需要一条稳定事件链。

所以接下来要先收口 Checkpoint 4，而不是继续开新功能面。

## 总路线

```text
先完成 Checkpoint 4 架构契约
  -> 再进入 Checkpoint 5 企业运行骨架
  -> 最后才继续补体验、答辩材料、生产部署增强
```

当前优先级：

1. C4.5 HITL 生命周期契约。
2. C4.6 Temporal / LangGraph / Research / Enterprise Store 职责边界。
3. C4.7 Observability / Governance telemetry 契约。
4. Checkpoint 4 完成审计文档。
5. 新建 Checkpoint 5 企业运行骨架方案。

## C4.5 HITL 生命周期契约

目标：

让人工介入不是几个 UI modal，而是一条可审计、可回放、可恢复、可写入 memory 的企业流程。

统一生命周期：

```text
requested
accepted
modified
rejected
timed_out
resumed
redo_requested
revision_created
approved
published
```

实施范围：

- 新增或整理 `backend/packages/hitl/`。
- 定义 `HitlLifecycleEvent` 或同等 typed contract。
- PlanReview、QAReview、manual redo、manual report revision、report approval 都通过同一生命周期记录。
- 每次人工决策至少写入：
  - stage
  - decision
  - actor_id
  - target_type
  - target_id
  - run_id
  - report_version_id, if any
  - redo_scope, if any
  - audit_log_id, if any
  - decision_replay_event_id or stable event key
- memory feedback 只能在人工决策确实包含 durable correction/preference 时写入，不再因为“点了通过”就无差别写入。

验收：

- HITL_ENABLED=true 的 run 能在 decision replay 里看到 planner review 和 QA review。
- QA review 的 redo 能形成 lifecycle event，并能关联 RedoScope。
- 手动报告修订必须创建新 draft，不允许原地覆盖发布版本。
- report approval request / approve / reject / publish 都能进入同一 lifecycle/audit/replay 链。

建议提交：

```text
feat(hitl): standardize review lifecycle events
```

## C4.6 编排职责边界契约

目标：

让系统里每一层知道自己负责什么，避免 RunService 继续变成隐藏上帝对象。

边界：

```text
Temporal
  owns: long-running lifecycle, retry, schedule, approval workflow, notification hooks

LangGraph
  owns: one-run agent DAG, planner/collector/analyst/comparator/writer/QA, scoped redo

Research Pipeline
  owns: discovery, capture, extraction, admission, quality gaps, repair task proposals

Enterprise Store
  owns: durable workspace/project/run/evidence/claim/report/artifact/audit/memory records

RunService
  owns: API coordination, compatibility glue, state assembly
  must not own: source admission rules, report publication rules, workflow lifecycle rules
```

实施范围：

- 写清楚 ownership contract。
- 把已有代码中的边界入口标出来，而不是立刻大规模搬文件。
- 补架构测试，防止关键路径重新绕过 contract：
  - `/api/runs` 在 Temporal 模式必须通过 Temporal service。
  - ReleaseGate 使用 ReportVersion scope。
  - collector 只能通过 Research Pipeline admission 产生可报告证据。
  - report approval 不由 LangGraph 直接发布。
- 对 `RunService` 做小步瘦身：只抽出边界明确、测试覆盖足够的 helper/service，不做大爆炸重构。

验收：

- 有一张代码级 ownership map。
- 有测试证明关键路径没有绕过 Temporal/Research/Enterprise contracts。
- 新增功能时能判断应该放在哪一层。

建议提交：

```text
docs(architecture): define orchestration ownership boundaries
```

如果有少量代码抽取：

```text
refactor(orchestrator): separate boundary coordination helpers
```

## C4.7 Observability / Governance 契约

目标：

把 local trace、decision replay、audit、metrics、Langfuse、OTel 统一成一个 telemetry contract。

不是现在就强行部署 Langfuse，而是明确：

- 本地 baseline 一定可用。
- Langfuse 是 mirror adapter。
- OTel exporter 是 deployment adapter。
- audit/decision replay 是企业合规主线。

统一 telemetry event 类型：

```text
trace_span
tool_call
model_call
token_cost
quality_finding
decision_event
audit_event
compliance_event
hitl_lifecycle_event
workflow_event
```

实施范围：

- 新增或整理 `backend/packages/observability/telemetry_contract.py`。
- Runtime/status 接口明确返回：
  - local trace enabled
  - decision replay enabled
  - Langfuse configured / disabled reason
  - OTel configured / disabled reason
  - audit enabled
  - compliance redaction enabled
- Decision replay 吸收 C4.5 的 HITL lifecycle event。
- Metrics 暴露 hosted observability 状态，不让前端误以为“没配 Langfuse = 没观测”。

验收：

- 不配置 Langfuse 时，真实 run 仍然能完成本地 trace、decision replay、quality matrix。
- 配置 Langfuse/OTel 时，不需要改 agent 代码，只改配置和 exporter。
- `/api/runtime` 或 `/api/metrics` 能解释当前观测状态。

建议提交：

```text
refactor(observability): formalize telemetry export contract
```

## Checkpoint 4 完成审计

C4.5-C4.7 完成后，新增一份完成审计：

```text
docs/reports/checkpoint4_architecture_contract_audit_20260607.md
```

必须逐条回答：

- Identity Resolver 是否统一？
- Report scope 是否和 project memory/history 分离？
- Clean Research Pipeline 是否仍是采集/抽取/准入唯一边界？
- Quality Finding Matrix 是否覆盖 QA/RedTeam/EvidenceGap/ClaimValidator/ReleaseGate/EvalOps？
- HITL 是否可审计、可回放、可恢复？
- Temporal/LangGraph/Research/Enterprise Store 边界是否清楚？
- 本地观测是否在无 Langfuse 情况下完整可用？

验证：

```text
ruff:
  backend/packages/identity
  backend/packages/research
  backend/packages/quality
  backend/packages/hitl
  backend/packages/workflows
  backend/packages/observability
  backend/packages/orchestrator

pytest:
  backend/tests/unit/test_source_reconciliation.py
  backend/tests/unit/test_research_pipeline.py
  backend/tests/unit/test_quality_findings.py
  backend/tests/unit/test_temporal_workflows.py
  backend/tests/unit/test_observability.py
  backend/tests/unit/test_enterprise_store.py
```

真实 run 验收：

```text
1. Temporal 模式真实 run 一次，HITL disabled。
2. HITL_ENABLED=true 真实 run 或 fixture-backed run 一次，验证 planner/QA review lifecycle。
3. 检查 report source token、quality matrix、release gate、decision replay、runtime observability。
```

## Checkpoint 5 企业运行骨架

Checkpoint 4 完成后再开 Checkpoint 5。

Checkpoint 5 不再围绕“单次 run 质量”，而围绕“企业业务产品可运行”。

候选工作流：

1. Approval Queue 产品化。
2. Artifact / SourceSnapshot 生命周期。
3. Workspace isolation / RBAC / RLS readiness。
4. Memory/RAG advisory context 治理。
5. EvalOps / Regression Gate 产品化。
6. Cost / quota / model policy 统一治理。
7. Monitor jobs / scheduled scan 作为企业运营能力。

Checkpoint 5 的第一份文档应是：

```text
docs/checkpoint5_enterprise_runtime_plan.md
```

它应从 `dev_plan_final` 和高分融合 backlog 中吸收：

- H5 MemoryAgent。
- H8 Decision Replay 升级。
- H9 EvalOps 看板。
- H10 SourceSnapshot / ArtifactStore / ToolRegistry / ModelRouter。
- Phase 5A RBAC/RLS/observability/governance。

但执行顺序必须服从企业产品逻辑：

```text
先审批/发布/审计
再隔离/治理/观测
再 memory/RAG/EvalOps 增强
最后 SSO/RLS/生产部署增强
```

## 不做什么

短期不要做：

- 不要重写 LangGraph。
- 不要把 Temporal 细粒度化到每个 Agent 节点。
- 不要继续在 collector 里加 source 特例。
- 不要把 writer 变成 source resolver。
- 不要为了单个 run 的 bad URL 修改架构。
- 不要把 Clean Research Pipeline 外的问题都塞进 Clean Research Pipeline。
- 不要因为 Langfuse 没部署就否定本地 trace/decision replay。

## 下一步立即执行

从这里继续：

```text
1. 完成 C4.5 HITL 生命周期契约。
2. 提交：feat(hitl): standardize review lifecycle events
3. 完成 C4.6 编排 ownership 文档和边界测试。
4. 提交：docs(architecture): define orchestration ownership boundaries
5. 完成 C4.7 telemetry contract。
6. 提交：refactor(observability): formalize telemetry export contract
7. 写 checkpoint4 完成审计。
8. 再开 checkpoint5_enterprise_runtime_plan。
```

