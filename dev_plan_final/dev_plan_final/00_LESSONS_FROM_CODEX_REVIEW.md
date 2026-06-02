# 00 · Codex 评审收获 + v2.5/v3 修正记录

> 本章记录 2026-05-28 Codex 对 v2.5 和 v3 草案的评审结论，以及 final 方案吸收的修正。**这是设计史，也是反面教材，未来重温能避免同样的错误。**

## 0.1 评审上下文

- **被评审对象**：`dev_plan_v2_5/`（11 文档）+ `dev_plan_v3/`（16 文档）
- **评审者**：Codex（外部 AI Reviewer）
- **评审日期**：2026-05-28
- **评审原文**：详见对话记录

## 0.2 Codex 三大核心判断

### 核心判断 A · 元判断
> "v2.5 基本合理，适合作为下一阶段落地计划，但要把答辩味太重、伪造痕迹、贪多的部分砍掉。  
> v3 方向有价值，但明显过度设计，不适合直接照着做。它更像北极星蓝图，不是当前执行方案。"

**我的反应**：✅ 完全接受。这是元判断的胜利——之前我把 v2.5 当作答辩方案、v3 当作"激进升级"，实际上正确定位是：v2.5 = 产品雏形草案，v3 = 长期愿景。

### 核心判断 B · 工程伦理
> "git init + 还原 25+ commits / TRAE 截图 ≥ 10 张" → **不要伪造历史。从现在开始做真实 commits + AI_ASSISTED_DEVELOPMENT.md 记录真实 AI 工具使用。**

**我的反应**：✅ 完全接受。这是我之前最严重的错误。

### 核心判断 C · 架构层判断
> "Temporal 不应该替代 LangGraph，至少前 6-12 个月不该替代。Temporal 应该包在 LangGraph 外层。"

**我的反应**：✅ 完全接受。v3 第 3 章把 Temporal 当替代品是误判。正确架构是 Temporal 管"长流程/周期监控/审批"，LangGraph 管"Agent 推理图/Send/RedoScope"，两者正交。

## 0.3 v2.5 草案的具体错误（已修正）

### 错误 1：伪造 git history（最严重）

**v2.5 原文（04_FIX_PLAN_A_GAPS.md F1）**：
```bash
git commit --date="2026-04-15T10:00:00" -m "chore: project skeleton"
git commit --date="2026-04-16T14:00:00" -m "feat(schema): Pydantic models"
# ... 用 --date 还原 25+ commits 时间线
```

**为什么是错的**：
- 这是欺骗评委，违背工程伦理
- 时间戳跳跃容易被识破（commit 之间分钟数过短或过整）
- 一旦被识破，D3/D4 直接归零，比不伪造还差
- 评审委员会的工程师比我们想得更专业

**final 修正**：
```bash
# Phase 1 W0
cd D:/codex_workspace/plan_a
git init
git add .
git commit -m "chore: initialize git, baseline at $(date +%F)"

# 从这一刻起每个真实改动真实 commit
# 不用 --date 跳跃
# 写 AI_ASSISTED_DEVELOPMENT.md 解释 Git history 短的原因
```

详见 [04_AI_ASSISTED_DEVELOPMENT.md](./04_AI_ASSISTED_DEVELOPMENT.md)。

### 错误 2：TRAE 截图答辩导向

**v2.5 原文**：
```
.trae/
├─ workflow_screenshots/  (≥ 10 张截图)
└─ trae_workflow.md       (总体工作流说明文档)
```

**为什么是错的**：
- 为评分而制造截图 = 答辩思维
- 截图本身没有工程价值，浪费时间
- 评委更想看真实的 AI 协作产物（决策记录 / lessons learned / commit message 里的协作痕迹）

**final 修正**：
- 写 `docs/AI_ASSISTED_DEVELOPMENT.md`：列出真实使用的 AI 工具 + 关键 prompt 摘录 + 决策记录
- 自然产生的 chat 记录可以引用，不需要刻意截图
- Conventional Commits 里的 `Co-Authored-By: Claude` 等元数据也算证据

### 错误 3：8 周计划偏满

**v2.5 原文（07_ROADMAP_8WEEKS.md）**：
```
W1-W2  修硬伤
W3-W4  借鉴 CIMatrix
W5-W6  增强 Agent
W7     抽象 + 测试
W8     答辩
```

**为什么是错的**：
- 1.5-2 人在 8 周做 13+ 项，每项都浅
- 没有"产品化"特性（Evidence Center / ReportVersion）
- 没有为后续企业化预留缓冲

**final 修正**：
```
Phase 1 (W0-W2)   工程清理 + Git + baseline eval 骨架
Phase 2 (W2-W6)   L1/L2/L3 + ScenarioPack + Evidence + verify + QA rules
Phase 3 (W6-W10)  Evidence Center + ReportVersion + RedTeam + EvidenceGap
─────────────────────────────────────
Phase 4 (10w+)    Postgres + Workspace/Project + RBAC + AuditLog
Phase 5 (5m+)     Temporal 外层 + 周期监控 + 多租户
```

10 周 + 后续企业化，不再"贪多嚼不烂"。详见 [01_EXECUTION_ROADMAP_5_PHASES.md](./01_EXECUTION_ROADMAP_5_PHASES.md)。

## 0.4 v3 远景的具体误判（已修正）

### 误判 1：Temporal 替代 LangGraph

**v3 原文（03_ORCHESTRATION_TEMPORAL.md）**：
```
M3: Temporal 接管编排
M4: LangGraph 退役
```

**为什么是错的**：
- LangGraph 的 Send fan-out / RedoScope / HITL interrupt / 节点级 trace 是 plan_a 已经做得很好的护城河
- 用 Temporal 重写 = 重新造轮子，没有收益
- Temporal 真正擅长的是"长流程编排"（周期监控 / 审批 / 失败恢复 / 通知），不是"Agent DAG"

**正确架构**：
```
Temporal 外层 · 企业级长流程
├─ 周期监控（每天扫描 / 每周报告）
├─ 审批队列（提报告 → 主管审批 → 发布）
├─ 失败重试（API 限流 / 超时自动 backoff）
├─ 长任务恢复（断点续跑 24h+ 任务）
└─ 通知（飞书 / 邮件 / Slack）
        │
        │ Activity 调用单次 run
        ▼
LangGraph 内层 · 单次 run 内 Agent 推理
├─ Planner → Collector → Analyst → ...
├─ Send fan-out × (competitor × dimension)
├─ 5 级 RedoScope
├─ HITL interrupt
└─ 节点级 trace
```

**final 修正**：详见 [02_ARCHITECTURE_LAYERED.md](./02_ARCHITECTURE_LAYERED.md)。

### 误判 2：v3 一次性堆 18 项重型基础设施

**v3 同时要上**：
```
Temporal + Pydantic-AI + LiteLLM + Kafka + CQRS + Neo4j + RDF/OWL +
Qdrant + Meilisearch + Redis + GraphQL + Yjs + K8s + ArgoCD +
DeepEval + TLA+ + 联邦协作 + 因果推理
```

**为什么是错的**：
- 这不是 6 个月 2.5 人的正常产品路线
- 像"研究平台 + 企业 SaaS + 答辩满分 + 论文方向"全塞在一起
- 任何一项失败都拖垮主线
- 团队学习曲线指数爆炸

**final 修正** —— 砍 / 延后清单：

| 项 | final 决定 | 替代或延后 |
|---|---|---|
| Kafka Event Sourcing | 砍 | SQLite + Postgres 够用 |
| Neo4j + RDF/OWL | 砍 | Postgres + pgvector 替代 |
| Yjs 多人协作 | 砍 | 单人 + 评论 |
| GraphQL | 砍 | REST + SSE |
| TLA+ 形式化验证 | 砍 | 集成测试 + 状态机文档 |
| 联邦协作 | 砍 | 不需要 |
| 因果推理 do-calculus | 砍 | 不需要 |
| 自适应 Schema 演化 | 砍 | 手动 schema migration |
| 多 Agent 互评博弈 | 砍（保留 RedTeam） | RedTeam 已够 |
| 跨 run KG 累积 | 延后到企业化 | Phase 4-5 |
| Temporal | 延后到企业化 | Phase 5（外层） |

砍后剩下的"v3 真正值得吸收的核心"：
- ✅ Pydantic-AI（用在新 agent + 复杂 agent 重写）
- ✅ LiteLLM Gateway（多模型路由）
- ✅ Postgres + pgvector（取代 SQLite，企业化阶段）
- ✅ AgentOps 思想（Prompt 版本 / 评估 / 数据飞轮）
- ✅ K8s + ArgoCD（企业化阶段）

## 0.5 v2.5 草案的合理之处（保留）

Codex 也明确了 v2.5 哪些必须保留：

```
✅ L1/L2/L3 三层竞品建模
✅ ScenarioPack 动态生成
✅ evidence_seed.jsonl 流水线
✅ QA rules yaml 化
✅ verify_homepage 工具
✅ RunMetrics 补 schema_pass_rate / human_override_rate / acceptance_rate
✅ RedTeam / EvidenceGap
✅ baseline eval
```

这些进入 final 方案的 Phase 1-3。

## 0.6 final 新增的"产品化"特性

Codex 提的（v2.5 / v3 都没有）：

```
新增 P0/P1：
├─ Evidence Center（统一证据库视图，跨 run）
├─ ReportVersion（报告版本管理 + diff）
├─ scoring / recommender（规则化打分）
└─ 前端业务工作台（不只是评估视图）

新增企业化阶段（Phase 4）：
├─ Workspace / Project / Competitor Library 三层数据模型
├─ RBAC（多用户权限）
├─ AuditLog（操作审计）
├─ Source Registry（数据源注册中心）
├─ Report History（跨 run 报告库）
└─ Monitor Jobs（周期监控任务）
```

这些是真正的"产品化"特性，比研究方向重要 100 倍。详见 [03_PRODUCT_FEATURES.md](./03_PRODUCT_FEATURES.md) + [05_DATA_MODELS.md](./05_DATA_MODELS.md)。

## 0.7 设计哲学的转变

| 之前（v2.5/v3 草案） | 现在（final） |
|---|---|
| 答辩驱动 | 产品驱动 |
| 工具堆砌 | 渐进交付 |
| 研究方向优先 | 业务模型优先 |
| 一次到位 | 五阶段渐进 |
| 时间盒满载 | 时间盒留缓冲 |
| 伪造工程纪律 | 真实工程纪律 |
| Temporal 替代 LangGraph | Temporal 包 LangGraph |

## 0.8 评分预期重估

| 阶段 | 评分预期 | 备注 |
|---|---|---|
| plan_a 现状（v2） | 80 | D3/D4 几乎零分 |
| Phase 1 完成（W2） | 82 | 工程清理 + 真实 git |
| Phase 2 完成（W6） | 85 | + L1/L2/L3 + ScenarioPack + QA rules |
| Phase 3 完成（W10） | **88-90** | + Evidence Center + ReportVersion + RedTeam |
| Phase 4 完成（10w+ → 5m） | 90-92 | + 企业化数据层 |
| Phase 5 完成（5-12m） | 92-94 | + Temporal 外层 + 多租户 |

**没有"答辩满分 95"承诺**。final 给的是真实数字。

## 0.9 几条永远不忘的教训

### 教训 1：评分不是设计目标
**错误思维**：方案 X 能拿 95 分 → 选 X  
**正确思维**：方案 X 是不是能真的交付 + 维护 + 演化 → 再看分

### 教训 2：工程纪律不能伪造
**错误思维**：D3 缺 git history → 用 --date 还原  
**正确思维**：D3 缺 git history → 现在开始真实 commit + 文档说明

### 教训 3：架构判断要懂工具的本质
**错误思维**：Temporal 比 LangGraph 强（替代）  
**正确思维**：Temporal 擅长长流程，LangGraph 擅长 Agent DAG（正交）

### 教训 4：产品 > 研究
**错误思维**：自适应 Schema 演化 + TLA+ + 因果推理 = 前瞻性  
**正确思维**：Evidence Center + ReportVersion + Workspace = 用户真要的东西

### 教训 5：路线图要有缓冲
**错误思维**：8 周做满 13 项 = 高效  
**正确思维**：8 周做扎实 8 项 + 留 2 周缓冲 = 真高效

## 0.10 致谢与归功

- **Codex 的关键评审**：发现伪造 git/TRAE、Temporal 误判、贪多三大问题
- **plan_a 已有投入**：6285 行 LangGraph + 5 级 RedoScope + 双层 trace 是真实护城河
- **CIMatrix 业务深度**：L1/L2/L3 + ScenarioPack + 规则引擎 + MemoryAgent 提供了产品化思路

## 0.11 后续维护

- 这份 LESSONS 文档**永久保留**，作为团队设计原则参考
- 未来重大架构决策前，先回看本文档
- 添加新的 lessons learned 到本文档（追加，不替换）

---

> 下一步：阅读 [01_EXECUTION_ROADMAP_5_PHASES.md](./01_EXECUTION_ROADMAP_5_PHASES.md) 了解 5 阶段执行路线。
