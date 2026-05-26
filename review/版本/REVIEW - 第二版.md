# Plan A vs CIMatrix —— 课题《AI 驱动的竞品分析 Agent 协作系统》评审报告 · v2

**评审范围**

0. 重审：课题不强制 LangGraph/CrewAI，比较各类编排架构选型
1. plan_a 对课题完整评分细则的符合度（**24 条**，覆盖 5 大评分维度）
2. CIMatrix 对同一份评分细则的符合度
3. 两项目优劣对比 · **双方亮点榜** · 改进建议
4. 后续可扩展方向
5. 优先行动清单

**评审日期**：2026-05-28
**评审依据**：`课题概要.txt`、`课题详情.txt`、`方案A_图驱动优化版.md`，以及对两项目代码与文档的实际审计

---

## 第 0 章 架构选型重审：LangGraph 不是唯一解，但仍是当前最优

### 0.1 课题原文

> 课题详情第 17 行：「主要使用 LangGraph 或 CrewAI 进行多 Agent 编排」
> 评分项 A2：「编排框架（LangGraph / CrewAI）使用合理，DAG 任务流转可视化、可追溯」

「主要使用」是建议而非强制；评分项也只看「编排框架使用合理 + DAG 可视化 + 可追溯」三件事，未规定具体框架名。**自研编排器（CIMatrix 路线）和其他社区方案（DeerFlow / MiroFlow）理论上都满足条件。**

### 0.2 候选架构横评

| 框架 | 成熟度（2026） | 核心抽象 | 子 agent 上下文隔离 | 流式 / SSE | Pydantic 强制 | HITL 中断 | 可观测 | 学习曲线 | 适用场景 |
|---|---|---|---|---|---|---|---|---|---|
| **LangGraph** | 高 | StateGraph + Send + Command | 子图 / 手动 | 原生 | 一等 | 原生 `interrupt` | LangSmith | 中-高 | **结构化 DAG + 反馈环** ✓ |
| **DeerFlow（字节）** | 中-高 | 在 LangGraph 之上的「super-agent harness」+ 文件沙盒 | 原生（每子 agent 独立 ctx） | 原生（继承 LG SSE） | 一等（dict + CI 校验） | 继承 LG | 继承 LG | 中 | **自由探索式 deep research** |
| **MiroFlow（MiroMind）** | 中 | 层级化 sub-agent + 多轮对话 | 隐式（层级） | 不明显 | 不强 | 弱 | 弱 | 高 | **GAIA / HLE 类基准任务** |
| **Anthropic Claude Research 模式** | 论文模式（非框架） | Lead → 并行 sub-agent → CitationAgent → 压缩回 Lead | 强 | 不适用（自实现） | 不适用 | 不适用 | 不适用 | 设计哲学 | **作为思想，叠加在任意框架之上** |
| **CrewAI** | 高 | Crew + Agent + Task + Process / Flows | 通过 Flows 实现 | 支持 | 一等（`output_pydantic`） | 弱 | 中 | 低 | 顺序 / 层级化角色扮演 |
| **AutoGen（微软）** | **维护期** | 多人聊天群 | 弱 | 支持 | 一般 | 弱 | 一般 | 中 | 自由对话谈判（**已被 MS Agent Framework 取代**） |
| **OpenAI Swarm** | **教学品** | Agent → Agent handoff | 无（无状态） | 一般 | 一般 | 无 | 无 | 低 | 教学（**已被 Agents SDK 取代**） |
| **完全自研（CIMatrix 路线）** | n/a | 自定义 supervisor + asyncio fan-out + EventBus | 完全自主 | 自实现 | 自实现 | 自实现 | 自实现 | 中 | **业务模型重于编排** |

### 0.3 五条候选路径与得分天花板预估

| 路径 | 短描述 | 3 周可交付度 | 评分天花板 | 关键风险 |
|---|---|---|---|---|
| **A 维持 LangGraph（plan_a 现路线）** | 当前已构建 8.5/9 的方案 A 实现 | ✅ 已交付 | **88–92** | 无 |
| **B 重写到 DeerFlow** | 让子 agent 享受原生 ctx 隔离 + 沙盒 | ⚠️ 风险高 | 80–85 | 评委不熟、harness 仍快速演进 |
| **C 改用 MiroFlow** | 层级化 deep research | ❌ 不匹配 | < 80 | 课题输出结构化 schema，不是研究类基准 |
| **D 完全自研（CIMatrix 路线但修复缺口）** | 业务建模深度 + 全自研 plumbing | ⚠️ 风险中 | 80–86 | 3 周做不完 plumbing；缺 LangGraph 的"标配感" |
| **E 混合：LangGraph 骨架 + DeerFlow / Anthropic 模式叠加** ⭐ | LG 做骨架，借 Plan-Execute / sub-agent ctx 隔离 / CitationAgent 模式 | ✅ 增量可达 | **90–94** | 需设计纪律：每个借鉴必须落到具体节点 |

### 0.4 立场与建议

- **不要重写**。LangGraph 给的 `interrupt() / Send / checkpointer / SSE / Pydantic state` 五件套，每一件都能直接对应课题评分项。重写换框架，3 周时间会全花在 plumbing 上，评分天花板反而更低。
- **不要"为自研而自研"**。CIMatrix 用自研编排有它的合理性（业务建模深、规则引擎为主），但代价就是 token cost / robots / HITL interrupt 这些原本框架免费给的能力都得自己写——结果就是它现在的状态：业务亮点很多，但若干工程细节缺失。
- **应该混合借鉴**。具体分四步叠加在 plan_a 现有 LangGraph 骨架上：
  1. **Anthropic Plan-Execute**：把 `planner` 升级为 Plan 节点输出 `AnalysisPlan`，写入"Lead Memory"（对应当前 `kb_cache.db`）；
  2. **DeerFlow sub-agent ctx 隔离**：把 `SubagentContext.messages` 真填充（修 Gap-2），让每个 collector / analyst 子 agent 拥有完整独立 chat history；
  3. **CitationAgent 模式**：现在 plan_a 的 phantom-citation 是 QA 内嵌检查；可拆出独立 `citation` 节点放在 writer 之后、qa 之前，专门 link 校验 → 评委容易看见；
  4. **CIMatrix 规则引擎模式**：QA 检查从 hard-code 抽到 yaml，每条规则有 id / severity / target / rationale → 直接对应评分项 A2「DAG 流转可追溯」。
- **答辩话术**：「我们以 LangGraph DAG 为骨架，叠加了 Anthropic 的 sub-agent context isolation、DeerFlow 的 Plan-Execute 思路、CIMatrix 同行的规则引擎驱动 QC，并用 KB cache 实现跨轮记忆。」—— 这套叙事直接覆盖了"考察要点"里的"多 Agent 编排 + Schema 设计 + 通信协议 + 反馈闭环"四项。

> **结论**：**plan_a 维持 LangGraph 骨架，叠加 Anthropic / DeerFlow / CIMatrix 三家的最佳实践**。这是最稳妥也最接近 90+ 分的路径。

---

## 第 1 章 plan_a 对课题完整评分细则的符合度

课题详情的 5 大评分维度共拆出 **24 条具体要求**，逐条核对。

### 1.A 多 Agent 协作与输出可信度（35%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **A1** | 角色划分清晰，多个专职 Agent，职责边界明确无重叠 | ✅ Y | 7 个 Agent：planner / collector / analyst / comparator / reflector / writer / qa，每个独立目录与 logic.py；comparator 与 analyst 边界明确（前者出 ComparisonMatrix，后者出 CompetitorKnowledge）|
| **A2** | 编排框架使用合理 + DAG 任务流转可视化、可追溯 | ✅ Y | LangGraph `StateGraph + Send + interrupt` 全用；`docs/graph.mmd + graph.png` 自动导出；前端 `StaticGraphView.tsx` 渲染 mermaid + `SwimlaneView.tsx` 实时点亮当前节点 |
| **A3** | Agent 间结构化消息传递（function calling / 标准 Schema），非自然语言 | ✅ Y | `AgentMessage`（id / from_agent / to_agent / message_type / payload_schema / payload）+ `ToolCallMessage`（tool_name / arguments / result / status）双 Pydantic 模型（`schema/models.py:237-269`）；落 SQLite `agent_messages` / `tool_call_messages` 两表 |
| **A4** | 反馈闭环真实可触发，重做后输出有改善（非伪闭环） | ⚠️ Mostly Y | 5 级 RedoScope 路由 + `RevisionRecord.convergence_ratio`（`schema/models.py:208`）记录每轮 issue 数变化；`audit.py` 落 before_md / after_md。**短板**：3 个 seed case 未严格断言每一种 scope 真触发（Gap-4） |
| **A5** | 输出严格符合预定义竞品 Schema，字段完整、格式一致 | ✅ Y | 全 Pydantic `extra="forbid"`：FeatureTree / PricingModel / UserPersonaModel / CompetitorKnowledge / ComparisonMatrix；6 个 yaml skill 定义维度 schema；analyst 出口强 model_validate |
| **A6** | 信息溯源完整：可定位到原始数据源，支持一键跳转 | ✅ Y | 前端 `ReportView.tsx`：每条 source 有 `id="source-{id}"` 锚点 + 外链 `<a target="_blank">` + 内嵌 snippet + content_hash 显示；后端 `RawSource.url / content_hash / confidence / source_type` 全留痕 |

**A 维度小结**：6 项 全过 1 项弱（A4 的 seed case 未严格断言），按 35% 权重折算约 **31–32 分**。

### 1.B 技术深度与工程完整度（25%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **B1** | 端到端链路完整：采集→编排→存储→后端→前端，可现场演示 | ✅ Y | FastAPI（health / runs / stream / hitl / kb / trace / revisions / skills / runtime 9 路由）+ React 10 features + 4 个 SQLite + nginx + `make demo` 一键 |
| **B2** | 可观测性：Prompt / 输入 / 输出 / 决策 / Token / 成本均可查 | ✅ Y | `TraceSpan` 含 `full_input / full_output / input_preview / output_preview / input_tokens_estimate / output_tokens_estimate / cost_estimate_usd / metadata`（`schema/models.py:212-234`）；前端 TracePlayback 时间轴 scrubber；CostPanel 成本面板 |
| **B3** | 上下文管理 + 错误恢复 + 幻觉抑制策略明确 | ⚠️ Mostly Y | 抗幻觉：reflector 主动找 gap + phantom citation 检测（`qa/logic.py:673-682`）+ Pydantic forbid；引用强制：`KnowledgeClaim.source_ids: min_length=1`；上下文：SubagentContext 结构存在但 messages 列表实际未填充（Gap-2）|
| **B4** | 系统稳定性：异常处理、超时重试、降级 | ⚠️ Partial | 超时：LLM `llm_timeout_seconds` 配置化、`fetch_page=12s`、`robots_check=4s`、`max_iterations=2`；降级：scoped redo + checkpointer 断点续跑 + demo_mode 兜底；**无指数退避、无显式重试次数**；Langfuse 静默吞错（Gap-8）|
| **B5** | 技术前瞻性：自适应任务拆分 / Agent 自评估 / 动态 Schema 演化 | ✅ Y | reflector 是 agent 自评估的雏形（产出 ReflectionRecord with coverage_gaps + cross_competitor_gaps）；KB cache 跨轮记忆（`memory/kb_cache.py`）；6 个 yaml skill 已实现"加新维度只需写 yaml"（动态 schema 半成）|

**B 维度小结**：3 项全过 2 项部分，按 25% 权重折算约 **20–22 分**。

### 1.C 业务价值与产品体验（20%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **C1** | 量化提升：时间 / 覆盖度 / 一致性 vs 人工 baseline | ⚠️ Partial | RunMetrics 内置 `source_coverage_rate / verified_source_rate / claim_citation_rate / total_duration_ms / cost_estimate_usd`；**但无人工 baseline 对比数据，无"节省 X 倍时间"的实测**|
| **C2** | 可落地、可扩展（换行业 / 换竞品对象） | ✅ Y | 6 个维度 yaml 即插即用；planner 接受任意 topic + competitors；KB cache 按 (competitor, dimension) 隔离，换行业不冲突 |
| **C3** | 交互流畅：报告查看 + 溯源跳转 + 人工介入 + 决策回放 | ✅ Y | 10 个 feature 视图：StaticGraph / Swimlane / Trace / TracePlayback / KbMatrix / Report / RevisionDiff / PlanReviewModal / QaReviewModal / CostPanel / Discovery / Messages；HITL 双 modal 真 interrupt + resume + 60s 超时回退 |
| **C4** | 业务闭环 metrics（准确率 / 覆盖率 / 人工修正率） | ⚠️ Partial | RunMetrics 6 项数值化指标已落；**但缺"人工修正率"（HITL override 计数）、"用户接受率"（report 反馈）等运营向 metric** |

**C 维度小结**：2 项全过 2 项部分，按 20% 权重折算约 **15–17 分**。

### 1.D 代码质量与文档（10%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **D1** | 代码风格规范、模块化、注释充分 | ✅ Y | ruff `E/F/I/UP/B` 全开 + line-length 100；模块化清晰（schema / llm / tools / skills / agents / orchestrator / memory / observability 八包）；类型注解齐全 |
| **D2** | 文档齐全：README / 架构图 / Agent 协议 / 部署 | ✅ Y | `docs/architecture.md`（含 15 步 DAG 详解 + Persistence + Observability）+ `schema.md`（Pydantic 字段说明）+ `api_contract.md`（HTTP/SSE 契约）+ `skill_authoring.md`（怎么加新 dim）+ `seed_cases.md` + 自动导出的 `graph.mmd / graph.png` |
| **D3** | Git 提交记录规范、分支管理 | ❌ N | **plan_a 根目录及 backend 均无 .git** —— Git 实践完全缺位 |
| **D4** | TRAE 等 AI 编程工具使用痕迹 | ❌ N | 未见 TRAE / Claude Code / Codex / Cursor 痕迹标注；docs 与 README 未提"用 X 工具开发"|

**D 维度小结**：2 项全过 2 项缺失，按 10% 权重折算约 **5–6 分**。**这是 plan_a 最大的丢分点**。

### 1.E 合规、材料与答辩（10%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **E1** | robots.txt 合规 + 数据来源声明 | ✅ Y | `tools/robots.py` httpx + 标准 robotparser 语义；fetch 前置 `_trace_robots`，不允许时 short-circuit + audit log |
| **E2** | 数据隐私脱敏（用户访谈 / 问卷） | ⚠️ Partial | `observability/tracing.py` 有 `sanitize_for_trace`：自动 redact `api_key / password / secret / token / bearer / authorization` 等 **基础设施敏感字段**；**但用户访谈姓名 / 邮箱 / 手机号未脱敏**（survey_simulator 出口未走 sanitize）|
| **E3** | 工具 / 模型 / 数据使用合规 | ✅ Y | `.env.example` 仅含 ARK_API_KEY 等敏感项；`.gitignore` 屏蔽 .env；模型走官方 Doubao endpoint；Perplexity 可选 |
| **E4** | 提交材料：方案文档 + 演示视频 + 代码库 | ⚠️ Partial | 方案文档（`方案A_图驱动优化版.md`）+ 代码库齐全；**未发现 mp4 / mov / pptx 等演示视频或答辩 PPT**|
| **E5** | 答辩素材准备：seed_cases / 演示流程 / FAQ | ⚠️ Partial | `scripts/seed_cases.py` + `docs/seed_cases.md` 在；**无答辩讲稿、无 demo 流程脚本**|

**E 维度小结**：2 项全过 3 项部分，按 10% 权重折算约 **6–7 分**。

### 1.X plan_a 综合得分预估

| 维度 | 权重 | 得分 | 加权 |
|---|---|---|---|
| A 多 Agent 协作与可信度 | 35% | 31–32 | 31.5 |
| B 技术深度与工程完整度 | 25% | 20–22 | 21 |
| C 业务价值与产品体验 | 20% | 15–17 | 16 |
| D 代码质量与文档 | 10% | 5–6 | 5.5 |
| E 合规、材料与答辩 | 10% | 6–7 | 6.5 |
| **合计** | | | **≈ 80.5 / 100** |

**评注**：之前粗估 88 偏乐观；按 24 条细则严打分约 **80–82**。要冲 88+，必须补 D3（git）+ D4（TRAE 痕迹）+ E4（演示视频）+ A4（seed case 严格断言）+ C1（人工 baseline 对比数据）这五个硬伤。

---

## 第 2 章 CIMatrix 对课题完整评分细则的符合度

### 2.A 多 Agent 协作与输出可信度（35%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **A1** | 角色划分清晰，专职 Agent，职责边界明确 | ✅ Y | 12 个 Agent 各自独立文件；主链 8 个 + 旁路 4 个（EvidenceGap / RedTeam / Benchmark / Memory）|
| **A2** | 编排框架使用合理 + DAG 可视化、可追溯 | ⚠️ Mostly Y | 自研 `AnalysisOrchestrator`；`PlanningAgent` 写入 `agent_dag` 列表；前端 `<div id="dag-flow">` 实时点亮；`docs/architecture-evolution-p0-p1.md` 有 ASCII 架构图；`docs/insights/design.md` 有 mermaid。**但 DAG 是顺序硬编码非数据驱动，不能像 LangGraph 那样自动可视化**|
| **A3** | Agent 间结构化消息传递 | ✅ Y | `backend/schemas/`：ProductBrief / ResearchPlan / CompetitorMap / L1ProductCompetitor / L2 / Evidence / Claim / RuleEvaluation / MemoryCandidate / EvidenceGap / RedTeamChallenge / AuditResult / AgentEvent —— 全 Pydantic v2 强类型；CLAUDE.md 明文规定"不用裸 dict 传业务数据" |
| **A4** | 反馈闭环真实可触发，重做后有改善 | ⚠️ Partial | `MAX_QC_RETRIES=2`；`runtime/local.py:33-75 execute_with_qc` 把 reject 规则的 reason 注入下轮 prompt；**但闭环仅触发 Analyst，规则虽指 Discovery / Collector 也只重跑 Analyst**；`AnalystAgent._fallback_claims` 在 first_pass 时人为塞入坏 claim 演示 QC 打回（教学装置而非真实工程逻辑）|
| **A5** | 输出严格符合预定义竞品 Schema | ✅ Y | L1 / L2 / L3 三层各自独立 schema；ScenarioPack 含 ProductBrief；`numeric_fact_source_required` 用正则保护数字事实；唯一裸 dict 处 `structured_data: Dict[str, Any]` 已 model_dump |
| **A6** | 信息溯源完整：可定位 + 一键跳转 | ✅ Y | `Claim.evidence_ids` 强约束 + `EvidenceAuditAgent` 三档判定（pass/weak/fail）+ `EvidenceTrace` claim→evidences 映射 + `audit_logs` 表落盘 + 前端 `evidence-drawer` 抽屉；real evidence JSONL 143 条带 source_url |

**A 维度小结**：4 全过 2 部分，按 35% 折算约 **27–29 分**。

### 2.B 技术深度与工程完整度（25%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **B1** | 端到端链路完整 | ✅ Y | WebScraper + ChromaDB + Postgres + FastAPI + 单页 HTML 2069 行 + docker-compose（含 postgres + chromadb + nginx）|
| **B2** | 可观测性：Prompt / 输入 / 输出 / 决策 / Token | ❌ Partial | EventBus 30+ 事件类型 + audit_logs 表齐全；**但 `llm/__init__.py` 完全未读 `response.usage`，token cost 零采集**；prompt 文本硬编码在各 agent 内部，未抽出 prompt 仓库与版本号 |
| **B3** | 上下文管理 + 错误恢复 + 幻觉抑制 | ✅ Y | 抗幻觉多层叠加：(1) Analyst 仅认 evidence_id 出现于已有 evidences 列表；(2) `R-EVIDENCE-001` + `claim_evidence_required` 双重 reject 空证据；(3) RedTeamAgent 阈值化检测 bias / evidence_gap / risk / alternative；(4) EvidenceGapAgent 三态 missing/low_confidence/outdated（90 天阈值）；上下文截断：evidence_summary 仅前 15 条，competitors 前 8 条 |
| **B4** | 系统稳定性：异常 / 超时 / 重试 / 降级 | ⚠️ Partial | LLM timeout=60s（无重试，失败返回 ""）；WebScraper timeout=45s（异常返回 []）；Active scrape L1≤5 / L2≤3；旁路 agent 失败 try/except 仅 logger.debug；Collector 三段降级：real_evidence_jsonl → structured fallback → active_scrape；Discovery 三段降级：local JSON → LLM → deterministic fallback。**LLM 无指数退避** |
| **B5** | 技术前瞻性 | ✅ Y | 动态场景 `scenario_packs/dynamic_*.json` 自动落盘；DiscoveryAgent LLM 生成未知 L1/L2；MemoryCandidate→FeedbackApplier 调权（归一化 + 排除竞品）；Sidecar 自评（red_team / evidence_gap / benchmark 三件套）|

**B 维度小结**：2 全过 1 严重部分（token cost 零）2 部分，按 25% 折算约 **17–19 分**。

### 2.C 业务价值与产品体验（20%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **C1** | 量化提升：时间 / 覆盖度 / 一致性 vs 人工 | ⚠️ Partial | `CODEX_DATA_SPEC.md` 给 143 条真实证据 / 3 场景 gap_score=1.0；`docs/p1-real-case-quality-report.md` 有质量报告；**但缺人工 baseline 时长对比、覆盖率%/一致性具体数字** |
| **C2** | 可落地、可扩展（换行业 / 换竞品对象） | ✅ Y | 4 个 scenario_packs（3 预设 + 1 动态示例）；自定义场景走 RequirementAgent LLM 扩展；L1/L2/L3 三层建模可换 SaaS / 平台 / 模型供应商 |
| **C3** | 交互流畅：报告 / 溯源 / 人工介入 / 决策回放 | ✅ Y | 单页 96KB / 2069 行 / 17+ 面板：scenario-grid / brief / competitor / report / dag-flow / timeline / rules / scoring / radar(canvas) / rec / evidence-chain / evidence-gap(矩阵热图) / red-team / benchmark / kb-status / history-list / memory-candidate-box / evidence-drawer。**雷达图为手写 canvas**|
| **C4** | 业务闭环 metrics | ✅ Y | `/api/feedback` → MemoryAgent → MemoryCandidate (`confirmed=False`) → FeedbackApplier 调权；双存储（内存 JSON + Postgres `memory_candidates` 表）|

**C 维度小结**：3 全过 1 部分，按 20% 折算约 **17–18 分**。**CIMatrix 在 C 维度反超 plan_a**。

### 2.D 代码质量与文档（10%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **D1** | 代码风格 + 模块化 + 注释 | ✅ Y | 全文件 type hints；agents 平均 200–500 行单一职责；`engine.py` 1774 行偏胖（OFFLINE_MODELS_FALLBACK 数据夹杂代码）；规则评估异常自动转 warn 级避免崩溃 |
| **D2** | 文档齐全 | ✅ Y | README 224 行（含 ASCII 架构图 + API 表 + Memory 流程示例）+ CLAUDE.md（构建规范）+ CODEX_DATA_SPEC.md（数据治理）+ `docs/architecture-evolution-p0-p1.md` + `docs/p1-real-case-quality-report.md` + `docs/insights/{design,spec,tasks,brief}.md`（含 mermaid graph TD）|
| **D3** | Git 实践 | ✅ Y | **git log 11 commits**，分支 main + codex-persist-real-evidence-db；commit message 规范（feat/chore/style 前缀）；2026-05-27 单日 P0→P1 5 次提交节奏密集 |
| **D4** | TRAE 等 AI 编程工具使用痕迹 | ✅ Y | **CLAUDE.md（Claude Code 协作规范）+ CODEX_DATA_SPEC.md（Codex 数据补全方案）+ commit 含 "codex-persist-real-evidence-db" 分支** —— AI 协作痕迹清晰 |

**D 维度小结**：4 项全过，按 10% 折算约 **9 分**。**CIMatrix 在 D 维度全面碾压 plan_a**。

### 2.E 合规、材料与答辩（10%）

| # | 评分细则 | 评级 | 证据 |
|---|---|---|---|
| **E1** | robots.txt 合规 | ❌ N | 全仓库无 robotparser / robots.txt 解析；WebScraper 仅设 User-Agent 直接 GET |
| **E2** | 数据隐私脱敏 | ❌ N | **关键缺口**：当前代码无任何 redact / mask / anonymize 逻辑；`docs/architecture-evolution-p0-p1.md:39` 提及 P0 曾有 Sanitizer Agent（正则匹配电话/API Key），但 P1 已下线；用户 feedback_text 与 evidence snippet 直接落库无脱敏 |
| **E3** | 工具 / 模型 / 数据使用合规 | ⚠️ Partial | scenario_pack `risks` 含合规条目；`mock_source_disclosure` 强制披露 mock 来源；隐式需求列出 GDPR / 个保法风险——披露式合规 |
| **E4** | 提交材料：方案 + 视频 + 代码 | ⚠️ Partial | README + 5 篇 docs + README.html；**未发现 mp4 / pptx / demo 等答辩资产**；`docs/p1-real-case-quality-report.md` 是最接近答辩材料的产物 |
| **E5** | 答辩素材：seed_cases / 演示流程 / FAQ | ⚠️ Partial | scenario_packs 提供演示数据；**无答辩讲稿、无 demo 流程脚本**|

**E 维度小结**：0 全过 3 部分 2 不达标，按 10% 折算约 **3–4 分**。**E 维度严重失分**。

### 2.X CIMatrix 综合得分预估

| 维度 | 权重 | 得分 | 加权 |
|---|---|---|---|
| A 多 Agent 协作与可信度 | 35% | 27–29 | 28 |
| B 技术深度与工程完整度 | 25% | 17–19 | 18 |
| C 业务价值与产品体验 | 20% | 17–18 | 17.5 |
| D 代码质量与文档 | 10% | 9 | 9 |
| E 合规、材料与答辩 | 10% | 3–4 | 3.5 |
| **合计** | | | **≈ 76 / 100** |

---

## 第 3 章 plan_a vs CIMatrix —— 对比 + 双方亮点榜

### 3.1 维度得分对照

| 维度 | 权重 | plan_a | CIMatrix | 谁更强 | 差距来源 |
|---|---|---|---|---|---|
| A 多 Agent 协作与可信度 | 35% | **31.5** | 28 | plan_a +3.5 | A2/A3/A4 plan_a 全完整；CIMatrix 反馈环退化 |
| B 技术深度与工程完整度 | 25% | **21** | 18 | plan_a +3 | B2 plan_a 有 token cost；CIMatrix 零 token |
| C 业务价值与产品体验 | 20% | 16 | **17.5** | CIMatrix +1.5 | CIMatrix 三层竞品 + MemoryAgent 闭环胜出 |
| D 代码质量与文档 | 10% | 5.5 | **9** | CIMatrix +3.5 | plan_a 无 .git、无 TRAE 痕迹两项硬伤 |
| E 合规、材料与答辩 | 10% | **6.5** | 3.5 | plan_a +3 | plan_a robots + 隐私 sanitize 有；CIMatrix 都缺 |
| **合计** | | **≈ 80.5** | **≈ 76** | plan_a +4.5 | 工程纪律 vs 业务深度 |

### 3.2 plan_a 核心亮点榜（10 大）

> 这些是 plan_a 在课题语境下做对、且明显优于 CIMatrix 或同类项目的地方。

| # | 亮点 | 课题加分项 | 关键文件 |
|---|---|---|---|
| **P1** | **5 级 RedoScope 真窄化重跑**（writer_only / comparator / analyst / collector / full） | A4 反馈闭环可触发 | `orchestrator/scoping.py` + `graph.py:47-58` |
| **P2** | **LangGraph `interrupt()` 真 HITL** + 60s 超时回退 + REST resume + 前端双 modal | A2 编排框架使用合理 + C3 人工介入 | `service.py:_maybe_interrupt` + `routers/hitl.py` + `PlanReviewModal.tsx` + `QaReviewModal.tsx` |
| **P3** | **双层 trace + Token / 美元成本完整采集** | B2 可观测性硬指标 | `TraceSpan` 含 14 个字段 + `cost_estimate_usd` + Langfuse 可选 |
| **P4** | **SubagentContext 结构化隔离 + 独立 context_id** | A1 职责边界无重叠 | `agents/context.py:7-30` |
| **P5** | **KB cache `(competitor, dim, content_hash) → SQLite`** 跨轮记忆 | B5 前瞻性 | `memory/kb_cache.py:25-108` |
| **P6** | **Reflector 自评估**（产出 ReflectionRecord 含 coverage_gaps / cross_competitor_gaps） | B5 Agent 自评估 | `reflector/logic.py:11-70` |
| **P7** | **6 个 yaml skill 即插即用**（pricing / feature / persona / review / integrations / security） | B5 动态 schema 雏形 | `packages/skills/*.yaml` |
| **P8** | **AgentMessage / ToolCallMessage 双 Pydantic 协议落 SQLite** | A3 结构化通信 | `schema/models.py:237-269` |
| **P9** | **前端 10 features 视图**：StaticGraph / Swimlane / Trace / TracePlayback / KbMatrix / Report / RevisionDiff / HITL × 2 / CostPanel / Discovery / Messages | C3 交互流畅 | `frontend/src/features/*` |
| **P10** | **robots.txt 合规真实落地** + sanitize_for_trace 自动 redact 敏感字段 | E1 合规 + E2 隐私 | `tools/robots.py` + `observability/tracing.py:7-35` |

### 3.3 CIMatrix 核心亮点榜（10 大）

> 这些是 CIMatrix 业务理解 / 数据治理 / 闭环设计层面的独特优势，**plan_a 应主动借鉴**。

| # | 亮点 | 课题加分项 | 关键文件 |
|---|---|---|---|
| **M1** | **三层竞品建模 L1/L2/L3**（直接产品 / 平台方案 / 模型供应商） + 16 家 LLM 供应商离线兜底 | C2 可换行业 / 可换竞品对象 | `schemas/competitor.py` + `engine.py:64-100` |
| **M2** | **真实 evidence JSONL 数据资产**（143 条带 source_url / confidence / collected_at） + `validate_real_evidence.py` schema 校验 + ChromaDB 同步 | C1 量化覆盖度 | `data/real_evidence/evidence.jsonl` + `validate_real_evidence.py` + `seed_real_evidence.py` |
| **M3** | **7 条 yaml 规则引擎 + 三档 action**（reject / warn / block） + 数字事实正则保护 | A2 DAG 可追溯 + B3 抗幻觉 | `rules/definitions.py:230-285` + `numeric_fact_source_required` |
| **M4** | **MemoryAgent 偏好学习闭环**：feedback → MemoryCandidate（confirmed=False） → 用户确认 → FeedbackApplier 调权 / 排除竞品 | C4 业务闭环 metrics | `agents/memory_agent.py` + `feedback/applier.py` |
| **M5** | **3 旁路增强 Agent 非阻塞**（EvidenceGap 三态 missing/low_conf/outdated + RedTeam 4 类挑战 + Benchmark 对照） | B5 Agent 自评估前瞻性 | `agents/{evidence_gap,red_team,benchmark}_agent.py` |
| **M6** | **EvidenceAudit 三档判定**（pass / weak / fail，min_confidence ≥ 0.6 + 至少一条非 mock 源） | A6 信息溯源完整 | `evidence/audit_agent.py:42-94` |
| **M7** | **动态场景生成**：`scenario_id="custom"` 时 LLM 现场合成 ScenarioPack 落盘复用 | C2 可扩展 | `main.py:286-300` + `scenario_packs/dynamic_*.json` |
| **M8** | **Postgres + ChromaDB 双库持久化**（结构化 + 向量），AuditLog / ReportHistory / FeedbackStore 都有 in-memory + DB 双适配器 | B1 端到端链路 + B5 前瞻性 | `db/models.py` + `main.py:82-93` |
| **M9** | **198 个 test_***（19 文件 / 3625 行）覆盖 orchestrator / agents / rules / runtime / scenario / scoring / kb / feedback | D1 代码质量 | `backend/tests/` |
| **M10** | **AI 协作痕迹清晰**：CLAUDE.md（Claude Code 协作规范） + CODEX_DATA_SPEC.md（Codex 数据补全方案） + commit 含 "codex-persist-real-evidence-db" 分支 | D4 TRAE/AI 工具使用痕迹 | `CLAUDE.md` + `CODEX_DATA_SPEC.md` + git log |

### 3.4 互补性总结

```
        plan_a 强项                        CIMatrix 强项
        ━━━━━━━━━━━━━━━━━━━━              ━━━━━━━━━━━━━━━━━━━━
   ◉ LangGraph 骨架（HITL/SSE/             ◉ 三层竞品建模 L1/L2/L3
     checkpoint/Send 全用上）              ◉ 7 条 yaml 规则引擎
   ◉ 5 级 RedoScope 真窄化                 ◉ MemoryAgent 偏好学习闭环
   ◉ Token / 美元成本完整采集              ◉ 真实 evidence JSONL 数据资产
   ◉ 6 yaml skill 即插即用                 ◉ EvidenceAudit 三档判定
   ◉ Pydantic 全 forbid + AgentMsg         ◉ 3 旁路增强 Agent 非阻塞
   ◉ 10 features 前端视图                  ◉ 动态场景生成
   ◉ robots + sanitize_for_trace           ◉ Postgres + Chroma 双库
   ◉ 4 SQLite 持久化（含 KB cache）        ◉ 198 测试 + AI 协作痕迹
                ↓                                       ↓
        工程纪律 / 框架红利                  业务理解 / 数据治理 / 用户闭环
```

**核心洞察**：plan_a 在"骨架与纪律"上对方案 A 落地度高；CIMatrix 在"业务深度与数据治理"上更接近真实企业场景。**两者合并可达 90+ 分**。

---

## 第 4 章 后续可扩展方向

### 4.1 短期（1 周内可落，对应 plan_a 当前丢分项）

| # | 行动 | 对应丢分项 | 预期加分 |
|---|---|---|---|
| **S1** | `git init` + 30+ 提交补做 + 写规范 commit message | D3 Git 实践 | +2 |
| **S2** | docs 顶部加 "AI 协作声明"，标注哪些用 Claude Code / Codex / Cursor 写 | D4 TRAE 痕迹 | +1.5 |
| **S3** | 录 5 分钟演示视频（topic 输入 → 实时 swimlane → HITL → 报告 + 溯源 → trace playback） | E4 演示视频 | +2 |
| **S4** | 5 个 seed case × 5 种 RedoScope，每个落 expected.json 快照 | A4 反馈闭环可信 | +1 |
| **S5** | RunMetrics 加 `schema_pass_rate` / `human_override_rate` / `acceptance_rate` 三个字段 | C1 / C4 量化 | +1.5 |
| **S6** | 在 README 加"vs 人工 baseline"对照表（哪怕只有 3 条估算）| C1 量化 | +1 |

短期合计预期 **+9 分**，把 plan_a 从 ≈80.5 推到 ≈89–90。

### 4.2 中期（2–3 周，借鉴 CIMatrix 业务深度）

| # | 行动 | 借鉴自 | 预期加分 |
|---|---|---|---|
| **M1'** | AnalysisPlan 加 `competitor_layer: Literal["product","platform","model"]`，演示 L1+L2 两层 | M1 | +1.5（C2）|
| **M2'** | `runs/evidence_seed/*.jsonl` 离线 evidence 数据资产，启动校验 schema | M2 | +1.5（C1 / B1）|
| **M3'** | QA hard-coded 检查抽成 `qa/rules/*.yaml`（id / severity / target / rationale_template） | M3 | +1（A2 / B3）|
| **M4'** | `packages/memory/preference_store.py`：HITL 拒绝 plan / 通过 issue 抽 Preference，下次 system prompt 注入 | M4 | +1.5（C4 业务闭环）|
| **M5'** | reflector 拆分为 RedTeam / EvidenceGap / Benchmark 三个旁路节点（try/except 包裹） | M5 | +1（B5 前瞻性）|
| **M6'** | EvidenceAudit 节点产出三档 verdict（pass/weak/fail），写入 RawSource | M6 | +0.5（A6）|

中期合计 **+7 分**，可推到 ≈ 95+。

### 4.3 长期（>1 月，研究 / 前瞻方向）

1. **自适应任务拆分** —— Planner 根据 complexity 动态决定 sub-agent 数量与 max_turns
2. **多 Agent 互评矩阵** —— 每个 agent 都被 1 个 peer review
3. **动态 Schema 演化** —— reflector 反复发现的 cross_competitor_gap 自动生成 yaml 草稿到 `skills/_pending/`
4. **多模态证据** —— 截图 + OCR + 视频转写
5. **Embedding 去重** —— content_hash 之上叠 embedding similarity > 0.95
6. **联邦 / 团队协作** —— 多人同 run、批注、Git-style branch / merge
7. **跨 run 知识库累积** —— 全局 KB，下次同名 competitor 自动 prefill
8. **答辩可视化升级** —— Sankey 流量图替换 swimlane；token 消耗双轴回放
9. **A/B run 对比** —— 同 topic 不同 LLM / skill 组合横向对比
10. **跨竞品价格归一化** —— `normalized_monthly_usd` 处理币种 / 折扣 / per-seat vs flat
11. **混合架构演进** —— LangGraph 骨架 + DeerFlow Plan-Execute + Anthropic CitationAgent 模式叠加（见 §0.4）
12. **PII 脱敏 Agent** —— 复活 CIMatrix 的 P0 Sanitizer Agent，加正则 + LLM-based 双重脱敏

---

## 第 5 章 优先行动清单

### 5.1 plan_a P0（必做，本周内）

- [ ] **S1**：`git init` + 补 30+ 规范提交（按模块切分历史）
- [ ] **S2**：docs 顶部 "AI 协作声明" + 关键 commit 标注 `Co-authored-by: Claude / Codex`
- [ ] **S3**：录 5 分钟演示视频
- [ ] **S4**：5 个 seed case × 5 种 RedoScope + expected.json
- [ ] **S5**：RunMetrics 补三个字段 + 前端 CostPanel 展示
- [ ] **Gap-1**：Planner verify_homepage + cross_check_search 工具

### 5.2 plan_a P1（强烈建议，2 周内）

- [ ] **M1'**：competitor_layer L1/L2 两层
- [ ] **M2'**：离线 evidence 数据资产
- [ ] **M3'**：QA 规则 yaml 化（先抽 3 条示例）
- [ ] **Gap-3**：integration / replay 测试覆盖 5 条 redo 路径
- [ ] **S6**：人工 baseline 对照表

### 5.3 plan_a P2（锦上添花）

- [ ] **M4'**：MemoryAgent 偏好闭环
- [ ] **M5'**：旁路 RedTeam / EvidenceGap 节点
- [ ] **Gap-2**：SubagentContext.messages 真填充
- [ ] **Gap-6**：三个 graph 抽公共 install 函数
- [ ] **Gap-7**：final_qa_attempts 计数器

### 5.4 CIMatrix 优先（如果两项目合并交付）

**P0**
- [ ] **A-3**：补 token cost（`response.usage`）
- [ ] **A-4**：补 robots.txt 合规
- [ ] **A-2**：RedoScope 5 级路由（修反馈环退化）
- [ ] **A-PII**：复活 P0 Sanitizer Agent

**P1**
- [ ] **A-1**：迁移到 LangGraph（或保自研但补完工程项）
- [ ] **A-5**：持久化 prompt 文本
- [ ] **A-6**：HITL 真 interrupt
- [ ] **A-7**：KB cache

---

## 附录 · 评审依据与方法

- **评分细则来源**：`课题详情.txt` 第 25–63 行（5 大维度 × 24 条具体要求）
- **方案 A 决策**：`方案A_图驱动优化版.md` D1–D9 + 节点架构 + Schema 增量
- **plan_a 实证**：通读 `backend/packages/{agents,orchestrator,schema,memory,observability,skills,tools}` + 全部 docs + 前端 features
- **CIMatrix 实证**：通读 `backend/{agents,runtime,rules,evidence,schemas,db}` + docs + scripts/tests + git log
- **架构调研**：DeerFlow / MiroFlow / CrewAI / AutoGen / Swarm / Anthropic Research 模式公开资料（2025–2026）
- **打分方式**：每条评分细则 Y / Mostly Y / Partial / N 四档；按权重加权折算

> 报告 v2 生成于 2026-05-28 ｜ plan_a vs CIMatrix · 24 条评分细则全量对照 · 含架构选型重审 + 双方亮点榜
