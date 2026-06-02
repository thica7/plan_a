# 08 · 风险登记 + 关键决策（ADR 索引）

## 8.1 风险登记表

按 Impact × Probability 评分。Score ≥ 12 必须有缓解方案。

### Phase 1-3 阶段（10 周）

| ID | 风险 | Impact | Prob | Score | 缓解 |
|---|---|---|---|---|---|
| R-1 | 10 周不够，W6 仍在补硬伤 | 4 | 3 | 12 | 严守 Friday Go/No-Go；最差砍 P2 |
| R-2 | 借鉴 CIMatrix 引入兼容性 bug | 3 | 4 | 12 | 每个新模块 PR 必须有集成测试 |
| R-3 | Doubao API 限流 / 突发故障 | 4 | 3 | 12 | LiteLLM Gateway 加 daily budget cap + fallback 到 demo_mode |
| R-4 | 飞书问卷 API 接入审批拖延 | 3 | 4 | 12 | W2 提交申请；同步开发 mock；最差用 mock-only |
| R-5 | 30 条黄金集标注质量参差 | 3 | 4 | 12 | 1 人初标 + 1 人复核；先标 18 条核心 case |
| R-6 | 答辩"git history 短"被质疑 | 3 | 5 | 15 | **不伪造**，准备答辩词解释（详见 04 文档）|
| R-7 | Phase 3 ReportVersion / Evidence Center 复杂度超预期 | 4 | 3 | 12 | 有应急预案 EP-2 砍 EvidenceGap |
| R-8 | yaml 规则引擎 predicate eval 安全问题 | 3 | 3 | 9 | 用 simpleeval 限 globals |
| R-9 | 团队成员中途请假 / 离职 | 5 | 1 | 5 | 关键模块文档化；每周交付物文档化 |
| R-10 | LLM 总成本超预算 | 3 | 3 | 9 | 单 case 成本 SLO ¥3；超过自动告警 |
| R-11 | 评测脚本网络不稳定导致 case 失败 | 2 | 3 | 6 | 加 retry + timeout；evidence_seed 离线兜底 |
| R-12 | 评委追问"为什么不用 Temporal" | 3 | 5 | 15 | **答辩词已准备**，详见下文 |
| R-13 | 评委追问"覆盖度提升 +85% 是否 cherry-pick" | 3 | 4 | 12 | 30 条全量数据 + cohort 分布 + 失败 case 透明 |
| R-14 | 答辩 PPT 超时（> 15 分钟） | 3 | 4 | 12 | W7 起每周排练 1 次；PPT 删冗余页 |
| R-15 | 演示视频录制失败 / 现场崩溃 | 5 | 1 | 5 | 提前录 3 个备份视频；现场 demo 用 demo_mode 兜底 |

### Phase 4 阶段（企业化数据层）

| ID | 风险 | Impact | Prob | Score | 缓解 |
|---|---|---|---|---|---|
| R-21 | Postgres 迁移过程中数据不一致 | 5 | 3 | 15 | 双写过渡期 ≥ 1 月；每天 diff 校验 |
| R-22 | RBAC 漏洞导致跨 Workspace 数据泄露 | 5 | 2 | 10 | OPA 策略覆盖测试；安全审计 |
| R-23 | AuditLog 表过大影响性能 | 3 | 3 | 9 | 按月分区 + 90 天后归档冷存 |
| R-24 | Source Registry 误判 robots.txt 阻塞采集 | 3 | 3 | 9 | 加白名单 + 人工 review 队列 |

### Phase 5 阶段（Temporal）

| ID | 风险 | Impact | Prob | Score | 缓解 |
|---|---|---|---|---|---|
| R-31 | Temporal 学习曲线导致 Phase 5 延期 | 4 | 4 | 16 | M5 起预研 + 培训 + 1 个 hello-world |
| R-32 | Temporal Workflow 与 LangGraph 集成 bug | 4 | 3 | 12 | 双栈共存 ≥ 4 周验证；每个 Workflow 单测 + 集成测试 |
| R-33 | Temporal Server 自建运维成本超预期 | 3 | 3 | 9 | M5 末评估 Cloud；Server 资源 SLO 监控 |
| R-34 | Workflow 版本兼容破坏老 run | 4 | 2 | 8 | `workflow.set_version()` 严格使用 |

## 8.2 红线（Red Lines）

满足以下任一情况，**强制 escalate 给 PM + 技术负责人**：

| 红线 | 触发条件 | 应急动作 |
|---|---|---|
| RL-1 | W2 末仍未完成 Phase 1（git+清理+baseline） | 推迟 Phase 2 一周 |
| RL-2 | W4 末 L1/L2/L3 + ScenarioPack 仍未完成 | 砍 ScenarioPack 动态生成，保静态 5 个 |
| RL-3 | W6 末 30 条黄金集仍未跑通 | 缩到 18 条核心 |
| RL-4 | W8 末 Evidence Center / ReportVersion 仍未完成 | 砍 EvidenceGap，保 Evidence Center + RedTeam |
| RL-5 | W10 末答辩排练时长稳定超过 18 分钟 | 删次要视图，保核心 4 个 |
| RL-6 | 单 case 评测延时 > 10 分钟 | 跑 evaluate 时 `--quick` 模式 |
| RL-7 | LLM 总成本超过 ¥5000（全周期） | 评测改用 evidence_seed 离线 |
| RL-8 | 评测发现 final 比基线提升 < 30% | 重新调优 prompt + 增加 evidence_seed 命中率 |
| RL-9 | Phase 4: Postgres 迁移导致生产数据丢失 | **立即回滚**到 SQLite，启动事故复盘 |
| RL-10 | Phase 5: Temporal 错误率 > 5% | **立即切回** LangGraph 直跑，停止 Workflow 包装 |

## 8.3 应急预案库

### EP-1: Phase 1 末进度滞后

```
保留：git init + 清理 + RunMetrics 4 字段
砍：baseline eval 骨架（推迟 Phase 2 W3）
预期评分：80（vs 完整 82）
工时节省：3 天
```

### EP-2: Phase 2 末进度滞后

```
保留：L1/L2/L3 + verify_homepage + QA rules（5 条而非 8 条）
砍：ScenarioPack 动态生成（保静态）
砍：30 条黄金集 → 18 条核心
预期评分：85（vs 完整 87）
工时节省：1 周
```

### EP-3: Phase 3 末进度滞后

```
保留：Evidence Center 后端 API + 简易前端 + RedTeam
砍：EvidenceGap（保留 schema 不实现）
砍：ReportVersion diff 视图（保留 schema）
砍：scoring/recommender
预期评分：86（vs 完整 89）
工时节省：1.5 周
```

### EP-4: P2 全砍

```
保留：P0 + P1 全部
砍：飞书问卷 / LiteLLM 抽象 / Pydantic-AI wrapper / MemoryAgent
预期评分：88（仅 -1 分）
工时节省：2 周
```

### EP-5: 评测降级

```
保留：5 条核心 case smoke test
砍：30 条全量评测
报告改为定性 + 5 case 对比
```

### EP-6: 演示降级

```
保留：3 个核心 demo 视频
砍：现场 live demo
完全用预录视频 + 答辩 Q&A
```

## 8.4 关键答辩问题应对

### Q1: "为什么不用 Temporal？"

```
回答：
我们做了完整的架构对比（指向 dev_plan_v3 + dev_plan_final/02）。

Temporal 在 deterministic replay / 长任务 / HITL / 失败重试 4 个维度
确实优于 LangGraph，是企业级长流程编排的最优选。

但 Temporal 不应该替代 LangGraph，而应该包在外层。
LangGraph 擅长 Agent 推理图（Send fan-out / 5 级 RedoScope / HITL interrupt /
节点级 trace）—— 这些是 plan_a 已经做得很好的护城河。

正确架构是：
  Temporal 外层管"长流程 / 周期监控 / 审批 / 失败恢复"
  LangGraph 内层管"单次 run 的 Agent 推理图"
  两者正交，不替代

我们的 final 方案分 5 阶段：
  Phase 1-3 (10 周)   产品雏形（仅 LangGraph，不引入 Temporal）
  Phase 4   (5 月)    企业化数据层（Postgres + Workspace + RBAC）
  Phase 5   (12 月)   Temporal 外层（包 LangGraph，不替代）

不一口气上 Temporal 是因为：
  1. 单 run 工具不需要 Temporal
  2. 学习曲线 + 运维成本不合理
  3. plan_a 已投入 6285 行 LangGraph 代码 + 5 级 RedoScope 是真实护城河
```

### Q2: "为什么 git history 只有 10 周？"

```
回答：
我们 2026-04 用本地备份开发，2026-05-28 迁移到 Git。

迁移时我们做了几个决定：
  1. 不伪造历史 commit 时间（违背工程伦理）
  2. 写 docs/AI_ASSISTED_DEVELOPMENT.md 说明开发流程
  3. 之前的关键决策追溯写成 ADR（docs/decisions/）
  4. Conventional Commits 格式 + Co-authored-by 标注 AI 协作

虽然 Git history 短，但工程纪律是真实的。可以提供：
  - 本地备份的 changelog（如有）
  - 历次 ADR 的真实日期和讨论摘录
  - AI 协作的 prompt + 响应记录

我们认为真实 + 短 history 比伪造长 history 更符合工程伦理，
也更能体现团队的判断力。
```

### Q3: "覆盖度提升 +85% 是 cherry-pick 吗？"

```
回答：
我们的评测有透明的 cohort 设计：
  - 18 条核心 case（必须 100% 通过）
    • 6 条 L1 / 6 条 L2 / 6 条 L3
  - 9 条边界 case（容忍 80% 通过）
    • 3 条 dynamic ScenarioPack
    • 3 条非英文/中文竞品
    • 3 条 ≥ 5 个竞品的复杂 case
  - 3 条对抗 case（专项测试 verify / EvidenceGap / RedTeam）

在 docs/eval_report_final.md：
  - 失败 case 完整列出（不藏，比如 gold_022 boundary_complex 部分通过）
  - 按 cohort 分解显示（不汇总成单一指标）
  - GitHub Actions 每 PR 自动跑（不可篡改）
  - 提供完整 jsonl 数据供评委查阅

+85% 是 30 条全量平均，不是 cherry-pick。
```

### Q4: "为什么没有 Neo4j / Yjs / 联邦学习等？"

```
回答：
我们参考过 v3 远景方案，里面有 Neo4j / Yjs / TLA+ / 因果推理 / 联邦学习等。

但 final 方案明确删除了这些研究方向，理由：
  - Neo4j: 业务层不需要图查询，pgvector + JSONB 足够
  - Yjs: 单 Workspace + 评论 + RBAC 已够，多人实时协作过度
  - TLA+ / 因果推理 / 联邦学习: 学术方向，不是产品功能

final 方案聚焦"产品化"而非"研究化"：
  - Evidence Center / ReportVersion / Workspace
  - scoring / recommender / RedTeam
  - 这些才是企业用户真正需要的

v3 远景文档保留为长期参考，但不是当前执行方案。
```

### Q5: "MemoryAgent 偏好学习为什么砍掉？"

```
回答：
MemoryAgent 在 v2.5 草案是 P1 强建议，但 Codex 评审后我们降到 P2（可选）。

理由：
  - 偏好学习需要多次 run 数据才显现效果（冷启动问题）
  - 单 run / 演示场景里看不到价值
  - Phase 1-3 优先做"产品雏形"，先把基础打稳
  - Phase 4-5 再考虑（需要 Workspace 多用户场景才合理）

我们用更简单的"用户反馈表单"替代（详见 03 文档 §3.7），
落 runs/feedback.db 作为 Phase 4 MemoryAgent 的数据基础。
```

## 8.5 关键决策 ADR 索引

详细 ADR 见 `docs/decisions/`：

| ID | 标题 | 状态 | 日期 |
|---|---|---|---|
| ADR-0001 | 选择 LangGraph 而非 CrewAI | Accepted | 2026-04-15 |
| ADR-0002 | 5 级 RedoScope（writer_only / comparator / analyst / collector / full）| Accepted | 2026-04-20 |
| ADR-0003 | L1/L2/L3 三层竞品建模 | Accepted | 2026-05-25 |
| ADR-0004 | yaml 规则引擎替代 hard-code QA | Accepted | 2026-05-26 |
| ADR-0005 | Evidence Center 跨 run 视图设计 | Accepted | 2026-05-28 |
| ADR-0006 | 不伪造 git history，写 AI_ASSISTED_DEVELOPMENT.md | Accepted | 2026-05-28 |
| ADR-0007 | Temporal 包在 LangGraph 外层（不替代）| Accepted | 2026-05-28 |
| ADR-0008 | Phase 1-3 用 SQLite，Phase 4 迁移 Postgres | Accepted | 2026-05-28 |
| ADR-0009 | Workspace / Project / Competitor Library 三层数据模型 | Accepted | 2026-05-28 |
| ADR-0010 | 30 条黄金集而非 50 / 200 | Accepted | 2026-05-28 |

### ADR 关键内容（节选）

#### ADR-0006: 不伪造 git history

```markdown
## Context
v2.5 草案建议用 git commit --date 还原 25+ commits 时间线，
被 Codex 评审指出违背工程伦理。

## Considered Options
- A: 伪造 history（v2.5 原方案）
- B: 不伪造，写 AI_ASSISTED_DEVELOPMENT.md
- C: 使用 git replay 工具（仍是伪造）

## Decision
选择 B。理由：
- 伪造被识破会导致整个团队信誉损失
- D3 评分拿 5-7 分（非满分 8）但稳
- 真实工程伦理比答辩分数重要

## Consequences
- D3 评分预期 5-7（不是满分）
- 但答辩词扎实，评委更容易接受
- 团队工程伦理保留
```

#### ADR-0007: Temporal 包在 LangGraph 外层

```markdown
## Context
v3 草案建议 Temporal 替代 LangGraph，被 Codex 评审指出是误判。

## Considered Options
- A: Temporal 替代 LangGraph（v3 原方案）
- B: Temporal 包在 LangGraph 外层（Phase 5 引入）
- C: 仅 LangGraph，不引入 Temporal

## Decision
选择 B。理由：
- Temporal 擅长长流程，LangGraph 擅长 Agent DAG，两者正交
- 替代 = 重新造轮子，没有收益
- 包在外层 = 各取所长

## Consequences
- LangGraph 不退役
- Phase 5 引入 Temporal 时不改 LangGraph 一行代码
- 双层独立演化
```

## 8.6 风险监控周期

```
每周 Friday 16:00 retro：
  ├─ 复盘本周进度（Phase 目标 vs 实际）
  ├─ 复盘风险表（新风险？现有风险概率/影响变化？）
  ├─ 决策下周 Go/No-Go
  └─ 更新 docs/decisions/ ADR

每两周 monthly：
  ├─ 累计花费 vs 预算
  ├─ 关键依赖进展（Postgres 迁移 / Temporal 学习）
  └─ 答辩材料齐备度（Phase 3 后）
```

## 8.7 风险结案

每个 Phase 末写 `lessons.md`：

```markdown
# Phase N · Lessons Learned

## 哪些风险实际触发？
- R-X 概率高于预期，触发 EP-Y 应急

## 哪些缓解措施有效？
- ...

## 哪些风险高估了？
- ...

## 哪些风险低估了？
- ...

## 给下一 Phase 的建议
- ...
```

## 8.8 关键的"不做"（避免后悔）

| 不做 | 原因 |
|---|---|
| 不伪造 git history | ADR-0006 |
| 不在 Phase 1-3 引入 Postgres | ADR-0008 |
| 不在 Phase 1-3 引入 Temporal | ADR-0007 |
| 不重写 7 个 agent 为 Pydantic-AI | 渐进替换 |
| 不做 Neo4j / Kafka / Yjs / GraphQL | 过度设计 |
| 不做研究方向（TLA+ / 因果推理 / 联邦） | 不是产品价值 |
| 不做 200 条黄金集（仅 30 条） | 工时不允许 |
| 不做 LLM-as-judge（仅人工 + 客观指标） | Phase 4 再考虑 |

## 8.9 一句话风险策略

> **Phase 1-3 严守 Friday Go/No-Go 切边界；任何阶段做不完立即触发 EP；不伪造、不研究、不贪多——这是 final 与 v2.5 / v3 草案的根本区别。**

---

> 路线图 + 风险登记完毕。下一步建议：
> - 阅读 [INDEX.html](./INDEX.html) 进入网页可视化导航
> - 或直接开始 Phase 1：执行 [01_EXECUTION_ROADMAP_5_PHASES.md](./01_EXECUTION_ROADMAP_5_PHASES.md) §1.3
