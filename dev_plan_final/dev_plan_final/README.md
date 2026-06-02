# Competiscope · 最终执行方案（dev_plan_final v2.0）

> **代号**：plan_a final v2.0 / "Codex-Reviewed Executable Plan, Enterprise-Skeleton First"  
> **定位**：经 Codex **二次评审**后的最终执行方案。v2.0 修正 v1.0 的"先 SQLite 后 PG"路线，改为企业骨架前置。  
> **版本**：final v2.0  
> **日期**：2026-05-28  
> **关键判断（v2.0 修订）**：
> - **企业级架构骨架前置**（Phase 1 直接 PG + Workspace + EvidenceRecord 抽离 + 稳定 ID + AuditLog skeleton）
> - **企业级复杂能力后置**（RBAC / Temporal / pgvector / 监控 / 通知 在 Phase 4-5）
> - **总时间盒**：12 周雏形（v1.0 是 10 周）+ 5-12 月企业化
> - **核心修订**：稳定 evidence_id / claim_id（sha256-based）+ project_competitors 唯一事实来源 + ReportVersion 5 维分组规则 + Temporal replay 限制说明

---

## 一、本方案是什么

**Codex 评审后的最终版**。比 v2.5 更扎实、比 v3 更克制。

```
v2 (现状)        v2.5 (折中草案)      v3 (远景蓝图)
─────────         ──────────────       ──────────────
80 分             ~89 分但有"答辩味"   ~93 分但过度设计
plan_a 现状       L1/L2/L3 + 借鉴      Temporal + Neo4j + KG
                  CIMatrix 8 项        + 6 大研究方向
                  
                              │
                              │ Codex 评审：
                              │ ① 删伪造 git/TRAE
                              │ ② 改 Temporal 替代为外层
                              │ ③ 8 周→ 10 周 + 5 阶段
                              │ ④ 加产品化模块
                              │ ⑤ 砍研究方向
                              ▼
                  ┌────────────────────────────┐
                  │    final（本方案）         │
                  │  ─────────────             │
                  │ 产品雏形 → 企业化          │
                  │ 10 周 + 6-12 月渐进         │
                  │ ~88-92 分（无虚高）        │
                  └────────────────────────────┘
```

## 二、行动口号（v2.0 修订）

> **第一天起就建立 Workspace → Project → Competitor → Run → Evidence → Claim → ReportVersion → Audit 这条链路；后续 Temporal、Pydantic-AI、pgvector、RBAC、Source Registry 都是自然扩展，而不是推倒重来。**

## 三、与 v2.5 / v3 的关键差异

| 维度 | v2.5 (草案) | **final（本方案）** | v3 (远景) |
|---|---|---|---|
| Git history | 还原 25+ commits ❌ | **现在开始真实 commit** ✅ | 完整 ADR |
| TRAE 痕迹 | 截图≥10 张 ❌ | **AI_ASSISTED_DEVELOPMENT.md 真实记录** ✅ | - |
| 时间盒 | 8 周（偏满） | **10 周 + 后续企业化** | 6 月（过度） |
| 编排架构 | LangGraph 不动 | **LangGraph 内层 + Temporal 外层（企业化阶段）** | Temporal 替代 LangGraph ❌ |
| MemoryAgent | P1 强建议 | **P2 可选** | 完整方案 |
| 飞书问卷 | P0 必做 | **P2 可选** | - |
| Pydantic-AI | P2 兼容层 | **P1 用在新 agent**（Codex 也没反对） | 全栈替换 |
| Evidence Center | 隐含 | **P0 一等公民** ✅ | 隐含 |
| ReportVersion | 无 | **P1 一等公民** ✅ | 隐含 |
| Workspace/Project | 无 | **企业化阶段引入** ✅ | M6+ |
| Kafka / Neo4j / RDF | 不上 | **不上** | M6-M7 上 ❌ |
| Yjs / GraphQL / TLA+ | 不上 | **不上** | M5-M6 上 ❌ |
| 联邦 / 因果推理 | 不上 | **不上** | M6 上 ❌ |

## 四、五阶段路线图（Codex 提出 + 我细化）

```
Phase 1 (W0-W2)  工程清理 + 真实 Git + baseline eval 骨架
Phase 2 (W2-W6)  L1/L2/L3 + ScenarioPack + Evidence schema + verify_homepage + QA rules yaml
Phase 3 (W6-W10) Evidence Center + ReportVersion + RedTeam + EvidenceGap + scoring
─────────────────────────────────────────────────────────────────────────
Phase 4 (10w+)   Postgres + Workspace/Project + RBAC + AuditLog + Source Registry
Phase 5 (5月+)   Temporal 外层（不替代 LangGraph）+ 周期监控 + 多租户
```

详见 [01_EXECUTION_ROADMAP_5_PHASES.md](./01_EXECUTION_ROADMAP_5_PHASES.md)

## 五、文档导航

> 共 10 个 Markdown + 1 个 HTML 入口。

| 文件 | 内容 | 优先阅读 |
|---|---|---|
| **[README.md](./README.md)** | 入口（本页） | 所有人 |
| **[00_LESSONS_FROM_CODEX_REVIEW.md](./00_LESSONS_FROM_CODEX_REVIEW.md)** | Codex 评审收获 + v2.5/v3 修正点 | 必读 |
| **[01_EXECUTION_ROADMAP_5_PHASES.md](./01_EXECUTION_ROADMAP_5_PHASES.md)** | 5 阶段路线图（产品雏形 → 企业化）| **核心** |
| **[02_ARCHITECTURE_LAYERED.md](./02_ARCHITECTURE_LAYERED.md)** | Temporal 外层 + LangGraph 内层正确架构 | **核心** |
| **[03_PRODUCT_FEATURES.md](./03_PRODUCT_FEATURES.md)** | Evidence Center / ReportVersion / Workspace 等产品特性 | **核心** |
| **[04_AI_ASSISTED_DEVELOPMENT.md](./04_AI_ASSISTED_DEVELOPMENT.md)** | 真实 AI 协作模板（替代伪造 TRAE 截图） | 必读 |
| **[05_DATA_MODELS.md](./05_DATA_MODELS.md)** | Workspace/Project/Competitor Library 三层数据模型 | **核心** |
| **[06_QUALITY_AND_BASELINE_EVAL.md](./06_QUALITY_AND_BASELINE_EVAL.md)** | 评测 + 黄金集（精简 30 条）| 重要 |
| **[07_ENTERPRISE_ROADMAP.md](./07_ENTERPRISE_ROADMAP.md)** | 第四 + 五阶段（10 周后企业化路线） | 中长期 |
| **[08_RISK_AND_DECISIONS.md](./08_RISK_AND_DECISIONS.md)** | 风险登记 + 关键决策 ADR | PM |
| **[09_SECONDARY_REVIEW.md](./09_SECONDARY_REVIEW.md)** | ★ 二次评审记录（v2.0 核心，必读） | 架构师、PM |
| **[10_HIGH_SCORE_FUSION_BACKLOG.md](./10_HIGH_SCORE_FUSION_BACKLOG.md)** | 高分审查报告吸收项 + 课题适配增强 backlog | 后续开发 |
| **[INDEX.html](./INDEX.html)** | 浏览器打开，可视化导航 | - |

## 六、几个关键判断（与 v2.5/v3 不同）

### 判断 1：现在就开始真实 Git，不伪造历史
```bash
cd D:/codex_workspace/plan_a
git init
git add .
git commit -m "chore: initial baseline at $(date +%F), migrating to git"
# 之后每个改动真实 commit
# 写 docs/AI_ASSISTED_DEVELOPMENT.md 说明开发过程
```

D3 评分会拿 5-6 分（不是满分 8）但**比伪造被识破后归零强 100 倍**。详见 [04_AI_ASSISTED_DEVELOPMENT.md](./04_AI_ASSISTED_DEVELOPMENT.md)。

### 判断 2：Temporal 不替代 LangGraph，是包在外层
```
Temporal 外层 · 长流程 / 周期监控 / 审批 / 失败恢复 / 通知
       │
       │ Activity 调用
       ▼
LangGraph 内层 · 单次 run 内 Agent 推理图 / Send fan-out / RedoScope / HITL
```

详见 [02_ARCHITECTURE_LAYERED.md](./02_ARCHITECTURE_LAYERED.md)。

### 判断 3：先做证据和业务模型，再做更多 Agent
**P0 排序**（按 Codex 优先级）：
1. 工程清理 + Git
2. L1/L2/L3 三层竞品建模
3. **Evidence Center 雏形**（plan_a 之前没有）
4. ScenarioPack
5. QA rules yaml
6. 评测指标补齐 (RunMetrics)

**P1 第二批**：
7. RedTeam
8. EvidenceGap
9. **ReportVersion**（plan_a 之前没有）
10. baseline eval

**P2 可选**：
11. MemoryAgent
12. 飞书问卷接入
13. LiteLLM Gateway
14. Pydantic-AI wrapper
15. 前端新视图

详见 [01_EXECUTION_ROADMAP_5_PHASES.md](./01_EXECUTION_ROADMAP_5_PHASES.md)。

### 判断 4：v3 的研究化方向延后或砍掉

| v3 研究方向 | final 决定 | 原因 |
|---|---|---|
| 自适应 Schema 演化 | 砍 | 研究方向，非产品 |
| 多 Agent 互评博弈（GeneratorCriticJudge）| 砍（保留 RedTeam 即可） | 同上 |
| 因果推理 do-calculus | 砍 | 同上 |
| TLA+ 形式化验证 | 砍 | 同上 |
| 联邦协作 + DP + HE | 砍 | 同上 |
| 跨 run KG 累积 | **延后到企业化阶段** | 产品化时再做 |
| Neo4j + RDF/OWL | 砍 | 用 Postgres + pgvector 替代 |
| Kafka Event Sourcing | 砍 | SQLite + Postgres 够用 |
| Yjs 多人协作 | 砍 | 单人编辑 + 评论够用 |
| GraphQL | 砍 | REST + SSE 够用 |

## 七、设计哲学

1. **真实 > 答辩** —— 不伪造任何工程产物
2. **产品 > 研究** —— Evidence Center / ReportVersion / Workspace 比 TLA+ / 因果推理重要 100 倍
3. **正交 > 替代** —— Temporal 和 LangGraph 各自擅长，正交组合
4. **渐进 > 一次到位** —— 雏形 → 产品 → 企业化，每阶段独立交付
5. **克制 > 贪多** —— 5 阶段每阶段都不超过团队消化能力
6. **数据 > 代码** —— 黄金集 / evidence_seed / Workspace 数据模型先于功能
7. **优先级先于时间盒** —— 任何阶段做不完都按 P0/P1/P2 优雅降级

## 八、阅读建议

| 你的角色 | 推荐顺序 |
|---|---|
| **PM / 技术负责人** | README → 00 评审收获 → 01 路线图 → 08 风险 |
| **架构师** | 00 评审收获 → 02 分层架构 → 03 产品特性 → 05 数据模型 |
| **后端工程师** | 02 架构 → 05 数据模型 → 03 产品特性 → 06 评测 |
| **前端工程师** | 03 产品特性（前端部分）→ 05 数据模型（API） |
| **答辩** | 00 评审收获 → 01 路线图 → 04 AI 协作 |

## 九、版本关系

```
v2 评审 (review/)        v2.5 草案 (dev_plan_v2_5/)
        │                          │
        └──────────┬───────────────┘
                   │
                   ▼
                                    v3 远景 (dev_plan_v3/)
                                          │
                                          │
            Codex 评审 ──────────────────┘
                   │
                   ▼
        ╔══════════════════════════════════╗
        ║   final（本方案）                ║
        ║   dev_plan_final/                ║
        ║                                  ║
        ║   产品雏形（10w）→ 企业化（5m+）║
        ╚══════════════════════════════════╝
```

> **下一步**：阅读 [00_LESSONS_FROM_CODEX_REVIEW.md](./00_LESSONS_FROM_CODEX_REVIEW.md) 了解 Codex 评审的关键收获。
