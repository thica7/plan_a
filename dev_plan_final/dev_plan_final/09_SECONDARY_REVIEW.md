# 09 · 二次评审 · 企业骨架前置（v2.0 修订）

> 本章记录 2026-05-28 Codex 对 dev_plan_final v1.0 的**二次评审**结论，以及 final v2.0 吸收的修订。这是关键的"数据骨架前置 vs 后置"权衡记录。

## 9.1 评审上下文

- **被评审对象**：`dev_plan_final/` v1.0（10 文档）
- **评审者**：Codex（外部 AI Reviewer，与 v1 评审同一来源）
- **评审日期**：2026-05-28
- **评审原文**：`codex_review.md` 全文存档
- **采纳率**：80%（关键技术决策） + 20% 调整（时间盒 + 个别命名）

## 9.2 二次评审的核心论点

> **"企业级架构骨架前置，企业级复杂能力后置。"**

简言之：v1.0 是"先做产品闭环（雏形），再做企业化"——Phase 1-3 用 SQLite + 默认单 Workspace + Run-centric。v2.0 改为"企业骨架第一天就建立"——Phase 1 直接搭 Postgres + Workspace/Project/EvidenceStore/ReportVersion/AuditLog skeleton。

### v1.0 vs v2.0 关键差异

| 维度 | v1.0（旧）| v2.0（新）|
|---|---|---|
| Postgres | Phase 4 迁移 | **Phase 1 建 schema** |
| Workspace/Project | Phase 4 引入 | **Phase 1 默认实例 + 字段预留** |
| EvidenceRecord | 仍在 RunDetail 内 | **Phase 1 抽离独立入库** |
| ReportVersion | Phase 3 实现 | **Phase 1 最小表 + Phase 3 diff** |
| AuditLog | Phase 4 引入 | **Phase 1 skeleton + Phase 5 完整 RBAC** |
| 稳定 evidence_id | 缺失 | **Phase 1 sha256-based 设计** |
| Temporal | Phase 5 引入 | **Phase 4 引入薄壳（Codex 建议 Phase 3，调整为 Phase 4）** |
| Phase 1 时长 | 2 周 | **4 周（接受工时代价换数据骨架对）** |
| 总时间盒 | 10 周雏形 | **12 周雏形** |

## 9.3 为什么接受"企业骨架前置"

### Codex 的核心论点（直接引用）

> "新的原则不是提前堆满所有能力，而是避免早期系统长成一个 SQLite run 工具，后期再痛苦迁移。"

### 这个论点为什么对

#### 论点 1：数据迁移成本远大于一开始就用 PG

```
v1.0 路径（先 SQLite 后 PG）：
  Phase 1-3   (W0-W10)   SQLite × 4 表
  Phase 4     (10w-5m)   双写过渡期 1 月+ → PG
  风险：
  ├─ schema 不一致排查
  ├─ JSONB 索引重建
  ├─ 数据迁移期间双 bug 难定位
  └─ 跨表外键关系迁移容易漏

v2.0 路径（直接 PG）：
  Phase 1     (W0-W4)    PG schema 设计 + 默认 Workspace
  Phase 2-12+ ......     一直用 PG，无迁移
  代价：Phase 1 多花 2 周
  收益：Phase 4 省 1 月迁移痛苦
```

#### 论点 2：字段预留几乎零成本

```sql
-- v1.0 思路：runs 表先不带 workspace_id
CREATE TABLE runs (id, topic, ...);

-- Phase 4 时：
ALTER TABLE runs ADD COLUMN workspace_id UUID;
UPDATE runs SET workspace_id = '...' WHERE workspace_id IS NULL;
ALTER TABLE runs ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE runs ADD CONSTRAINT fk_runs_workspace FOREIGN KEY ...;
-- 加索引、检查、约束... 全表 scan
```

vs

```sql
-- v2.0 思路：第一天就预留
CREATE TABLE runs (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    project_id UUID,  -- nullable Phase 1，Phase 4 起 NOT NULL
    topic VARCHAR(200),
    created_by UUID NOT NULL DEFAULT '...',
    ...
);
CREATE INDEX idx_runs_workspace ON runs(workspace_id);
```

预留字段成本：~5 行 SQL。后期加字段成本：~1 周（含数据迁移 + 测试）。**ROI 100×。**

#### 论点 3：稳定 evidence_id 是 v1.0 漏掉的关键设计

Codex 的 §5.3 指出：
```
evidence_id = sha256(canonical_url + content_hash + competitor_id + dimension_key)
claim_id = sha256(evidence_id + normalized_claim_text + claim_type)
```

**为什么这是关键**：
- 没有稳定 ID → 跨 run 同一证据是不同记录 → Evidence Store 跨 run 检索失效
- 没有稳定 ID → ReportVersion diff 时无法对齐"是同一条 claim 还是新claim"
- 没有稳定 ID → source reliability 统计无法聚合

v1.0 在 03_PRODUCT_FEATURES.md §3.1 提到 EvidenceRecord 但**没有定义稳定 ID 算法**。这是 v1.0 最大的技术债。v2.0 必须修。

#### 论点 4：Temporal replay 限制是关键技术坑

Codex 的 §5.6 指出：
```
Temporal replay 不会重放 LangGraph 内部步骤。
Temporal 记录的是 Activity 结果。
如果 LangGraph 作为一个 Activity 执行，失败重试可能重跑整个图。
因此需要 run_id 幂等、checkpoint resume、evidence 去重、report version 幂等创建。
```

v1.0 的 02_ARCHITECTURE_LAYERED.md 没说清这个。如果 Phase 5 引入 Temporal 时不知道这个坑，会出现：
- Activity 重试 → LangGraph 重跑 → 重复写 evidence / report version
- 数据不一致 → 用户投诉

v2.0 必须在 Phase 1 设计阶段就让 evidence_id / claim_id / report_version_id 全部是**幂等的稳定 ID**，配合 INSERT ... ON CONFLICT DO NOTHING 保证幂等。

## 9.4 v2.0 的关键修订清单

### 修订 1: README → 版本号 v1.0 → v2.0

- 版本号升级
- 加二次评审说明
- 调整时间盒：10 周 → 12 周
- 调整原则："产品闭环优先" → "企业骨架优先 + 复杂能力后置"

### 修订 2: 01_EXECUTION_ROADMAP 重写

**v1.0 Phase 1（2 周）**：
- 工程清理 + Git
- AI_ASSISTED_DEVELOPMENT.md
- RunMetrics 4 字段
- baseline eval 骨架

**v2.0 Phase 1（4 周）**：
- 工程清理 + Git（不变）
- AI_ASSISTED_DEVELOPMENT.md（不变）
- **Postgres schema 初版**（新增）
  - workspaces / users / projects / competitors / project_competitors
  - runs / evidence_records / knowledge_claims
  - report_versions / report_version_claims / audit_logs
- **默认 Workspace / Project / User**（新增）
- **稳定 evidence_id / claim_id 设计**（新增）
- **EvidenceRecord 从 RunDetail 抽离独立入库**（新增）
- **ReportVersion 最小表**（新增）
- **AuditLog skeleton + 写入框架**（新增）
- **AgentExecutor 接口定义**（新增）
- **FastAPI CRUD（创建任务/查询任务/查询证据/查询报告版本）**（新增）
- **LangGraph 现有分析链路写入新数据模型**（关键改造）
- baseline eval 骨架（保留）
- React 最小工作台（推迟到 Phase 2，Phase 1 不要求前端）

### 修订 3: 05_DATA_MODELS 重写

加入：
- **稳定 ID 算法**（sha256-based）
- **ReportVersion 分组规则**（workspace_id / project_id / topic_normalized / competitor_layer / competitor_set_hash）
- **project_competitors 作为唯一事实来源**（删 Project.competitor_ids 字段）
- 完整 Postgres schema（含所有约束、索引、触发器）
- Phase 1 默认数据初始化脚本

### 修订 4: 02_ARCHITECTURE_LAYERED 增加章节

新增 §2.X：**Temporal replay 限制 + 幂等性设计**
- Temporal 不重放 LangGraph 内部
- run_id / evidence_id / claim_id / report_version_id 幂等
- INSERT ... ON CONFLICT DO NOTHING
- Activity retry 不引起重复写

### 修订 5: 07_ENTERPRISE_ROADMAP 时序调整

Phase 4 不再做"Postgres 迁移"（Phase 1 已建立），而是做：
- 多 Workspace 真实启用（Phase 1-3 是默认单 Workspace）
- RBAC 完整实现
- AuditLog 强化
- Source Registry
- pgvector 索引引入
- Temporal 薄壳引入

### 修订 6: 03_PRODUCT_FEATURES 调整描述

**v1.0 错误说法**："Evidence Center 是 plan_a 现有 SQLite 的统一查询视图"
**v2.0 修正说法**："Evidence Center 建立在 Phase 1 抽离的 EvidenceRecord 独立表之上"

### 修订 7: 06_QUALITY_AND_BASELINE_EVAL 指标调整

去掉 keyword_recall 作为主指标（Codex §4 §5.6 建议），改用：
- layer 判断准确率
- evidence coverage
- citation validity
- schema pass rate
- source freshness
- human override rate

keyword_recall 保留为辅助指标。

## 9.5 不采纳 / 调整的少数建议

### 不采纳 1: 目录改名 dev_plan_enterprise_aligned

**Codex 建议**：把目录改成 `dev_plan_enterprise_aligned` 或 `dev_plan_revised_enterprise_alignment`

**不采纳理由**：
- 已有 v2 review → v2.5 → v3 → final 四级演化，再加一级显得啰嗦
- 改目录会导致所有历史链接失效
- "final" 名字虽不严谨但表达"当前执行版"
- v2.0 修订足够表达迭代

**替代方案**：保留目录名 `dev_plan_final`，README 里加 v2.0 版本号即可。

### 调整 1: Temporal Phase 3/4 引入薄壳 → 仅 Phase 4

**Codex 建议**：Phase 3 或 Phase 4 引入 Temporal 薄壳

**v2.0 调整**：仅 Phase 4 引入

**调整理由**：
- Phase 3 还在做 RedTeam / EvidenceGap / scoring，Agent 能力没收敛
- Phase 3 引入 Temporal 薄壳意义不大（没有完整 Project / Audit 配合）
- Phase 4 已有完整数据骨架，此时 Temporal 才能用上
- Codex 的 CompetitiveIntelWorkflow 例子需要 persist_evidence_activity 等，依赖完整数据层

### 调整 2: Phase 1 时间盒 W0-W2 → W0-W4

**Codex 建议**：Week 0-2 完成企业数据骨架 + 最小分析闭环

**v2.0 调整**：扩到 Week 0-4

**调整理由**：
- Codex 的 Phase 1 任务清单（Postgres + Workspace + Evidence 抽离 + ReportVersion + AuditLog skeleton + FastAPI CRUD + LangGraph 接入）实际工时约 4 周（1.5-2 人）
- 2 周是不切实际的乐观估计
- 多 2 周换"后期不大改"，整体时间盒仍然合理（12 周 vs Codex 隐含的10 周）

### 调整 3: Pydantic-AI 阶段

**Codex 建议**：Phase 1 定接口 / Phase 4+ 替换实现

**v2.0 调整**：Phase 1 定接口 / Phase 3 新 Agent 用 Pydantic-AI 实现 / Phase 4+ 替换现有手搓

**调整理由**：
- Phase 3 的新 Agent（RedTeam / EvidenceGap）反正要从零写
- 直接用 Pydantic-AI 比手搓更省代码（30 行 vs 200 行）
- 不冲突 Codex 的"渐进替换"思想，只是更早收益

## 9.6 v2.0 的整体架构原则

```
v1.0 原则：产品闭环优先 → 企业化后置
v2.0 原则：企业骨架前置 → 复杂能力后置
```

具体落地：

**Phase 1（W0-W4）· 企业骨架**
- ✅ Postgres + 完整 schema（workspace_id / project_id 全字段预留）
- ✅ EvidenceRecord / KnowledgeClaim 独立入库
- ✅ 稳定 evidence_id / claim_id（sha256）
- ✅ ReportVersion 最小表
- ✅ AuditLog skeleton（写入框架，不做完整 RBAC）
- ✅ AgentExecutor 接口
- ❌ 不做：完整 RBAC、Temporal、pgvector、审批、监控

**Phase 2（W4-W6）· 业务情报能力（不变）**
- L1/L2/L3 + ScenarioPack + verify_homepage + QA rules
- 30 条 golden cases

**Phase 3（W6-W10）· Agent 能力增强（不变）**
- RedTeam（Pydantic-AI）+ EvidenceGap（Pydantic-AI）
- scoring / recommender + Report diff
- Evidence Center 前端 + 业务工作台

**Phase 4（W10-W12 + 后续）· 企业工作流化**
- Temporal 薄壳（CompetitiveIntelWorkflow）
- Approval queue 原型
- Multi-Workspace 真实启用

**Phase 5（M3+）· 企业治理和规模化**
- 完整 RBAC
- pgvector / 全文检索
- AuditLog 强化
- Langfuse / OTel
- PII redaction / model policy

## 9.7 评分预期重估

| 阶段 | v1.0 评分 | **v2.0 评分** | 备注 |
|---|---|---|---|
| Phase 1 完成（W2 / W4） | 82 / - | **84** | 企业骨架到位 |
| Phase 2 完成（W6） | 85 | **87** | 业务能力 + 数据基础扎实 |
| Phase 3 完成（W10） | 88-90 | **90-92** | Evidence Center 真跨 run |
| Phase 4 完成（W12 / 后续） | 90-92 | **92** | Temporal 薄壳 |
| Phase 5 完成（5-12m） | 92-94 | **93-94** | 企业治理 |

v2.0 比 v1.0 在每个阶段都高 1-2 分，因为数据骨架更扎实，Evidence Center / ReportVersion 真正跨 run 工作。

## 9.8 风险提示

### v2.0 新增风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Phase 1 4 周做不完 | 中 | 中 | 延 1 周到 5 周 + 砍 React 工作台到 Phase 2 |
| Postgres schema 设计有错 | 中 | 高 | ADR 写每个表的设计决策 + 至少 1 人外审 |
| 稳定 ID 算法实现 bug | 低 | 高 | 充分单测 + 跨 run 等价性测试 |
| EvidenceRecord 抽离改造影响现有 LangGraph | 中 | 高 | 双写过渡（旧 RunDetail + 新表）1 周后切流 |
| AgentExecutor 接口设计后期需要调整 | 高 | 低 | Phase 1 只定最简接口，Phase 3 时再扩展 |

### v1.0 已有风险（继续监控）

详见 [08_RISK_AND_DECISIONS.md](./08_RISK_AND_DECISIONS.md)。

## 9.9 决策依据 ADR-0011

新增 ADR-0011（详见 08 文档）：

```markdown
# ADR-0011: 企业骨架前置（Phase 1 直接 Postgres + Workspace 字段预留）

## Context
v1.0 草案"先 SQLite 后 Postgres，Phase 4 迁移"。Codex 二次评审指出：
- 数据迁移成本远大于一开始就用 PG
- 字段预留几乎零成本
- 稳定 evidence_id 是关键设计，v1.0 漏掉

## Considered Options
- A: v1.0 路径（SQLite 先行，Phase 4 迁移）
- B: v2.0 路径（Phase 1 直接 PG + 完整 schema）
- C: 混合（Phase 1 PG 但仅 runs 表，其他表延后）

## Decision
选择 B。理由：
- 数据骨架是难以演化的，应该一开始就对
- Phase 1 多 2 周工时换 Phase 4 省 1 月迁移痛苦
- 稳定 ID 设计是关键，必须 Phase 1 落地

## Consequences
- Phase 1 时长：2 周 → 4 周
- 总时间盒：10 周 → 12 周
- 开发环境复杂度提升（要起 PG 容器）
- 但 Phase 4 不需要做"Postgres 迁移"
- ReportVersion / Evidence Store 真跨 run 工作
```

## 9.10 一句话总结

> **v1.0 想"先简单做出来后期再迁移"，被 Codex 评审指出会落入"早期 SQLite run 工具，后期痛苦迁移"陷阱。v2.0 改为"企业骨架前置 + 复杂能力后置"，Phase 1 多 2 周建数据骨架，换 Phase 4 不踩迁移坑 + Evidence Center / ReportVersion 真跨 run 工作。**

---

> 下一步：阅读修订后的 [01_EXECUTION_ROADMAP_5_PHASES.md](./01_EXECUTION_ROADMAP_5_PHASES.md) 了解 v2.0 的 12 周路线。
