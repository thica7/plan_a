# Plan A vs CIMatrix —— 课题《AI 驱动的竞品分析 Agent 协作系统》评审报告

**评审范围**

1. `D:/codex_workspace/plan_a/` 对照 `方案A_图驱动优化版.md` 的符合度与差距
2. `D:/codex_workspace/CIMatrix/` 对照《课题概要》《课题详情》的符合度
3. 两项目逐维度优劣对比与改进建议
4. 后续可扩展方向

**评审日期**: 2026-05-27

---

## 第 1 章 plan_a 对课题 + 方案 A 的符合度审查

先核对**课题概要 / 详情**的 9 项硬要求，再逐条核对方案 A 的 D1–D9。

### 1.0 plan_a 对课题 9 项核心要求的符合度

| # | 要求 | 评级 | 关键证据 |
|---|---|---|---|
| 1 | 多 Agent 角色划分（采集 / 分析 / 撰写 / 质检） | ✅ Y | 7 个 Agent: planner / collector / analyst / comparator / reflector / writer / qa；QA 独立成节点；职责互不重叠（`packages/agents/{planner,collectors,analysts,comparator,reflector,writer,qa}`） |
| 2 | Pydantic 知识 Schema（功能树 / 定价 / 画像） | ✅ Y | `FeatureTree` / `PricingModel` / `UserPersonaModel` / `CompetitorKnowledge`（`schema/models.py:79-138`），全 `extra="forbid"` 严格校验；并额外定义 `ComparisonMatrix / RedoScope / QCIssue / ReflectionRecord` |
| 3 | DAG + 反馈闭环（QC 打回触发上游重做） | ✅ Y | LangGraph + Send fan-out + 5 级 RedoScope（writer_only / comparator / analyst / collector / full）真窄化重跑（`orchestrator/scoping.py` + `graph.py:47-58`）；phase QA 也走 retry 边 |
| 4 | 信息溯源 | ✅ Y | `KnowledgeClaim.source_ids: min_length=1` 强约束；`RawSource.url + content_hash + confidence`；`qa/logic.py:673-682` 检测 phantom citation；前端 ReportView `[^src_id]` 悬浮卡 |
| 5 | 可观测（prompt / IO / decision / token cost） | ⚠️ Mostly Y | `trace_spans` 表带 full_input / full_output / input_tokens_estimate / output_tokens_estimate / cost_estimate_usd / latency_ms / metadata（`schema/models.py:212-234`）；`agent_messages` + `tool_call_messages` 三表齐；Langfuse 可选 mirror。**唯独 `schema_pass_rate` 未作为 RunMetrics 字段暴露**（Gap-5） |
| 6 | LangGraph / CrewAI 编排 | ✅ Y | LangGraph `StateGraph` + `Send` fan-out + `interrupt()` HITL + SQLite checkpointer（`orchestrator/graph.py + checkpointer.py`）—— 三框架核心特性全用上 |
| 7 | 抗幻觉 / 上下文 / 错误恢复 / 超时降级 | ⚠️ Mostly Y | 抗幻觉：reflector 主动找 gap + qa phantom citation 强校验 + Pydantic forbid；上下文：SubagentContext 结构隔离（**但 messages 列表实际未填充**，Gap-2）；错误恢复：scoped redo + checkpointer 断点续跑 + ReAct max_turns 兜底；超时：`fetch_page timeout=12s` / `robots_check timeout=4s` 已设；**无指数退避**，失败一次走 fallback |
| 8 | E2E 链路：采集 → 编排 → KB → 后端 → 前端 | ✅ Y | LangGraph orchestrator + SQLite KB cache + FastAPI（runs / stream / hitl / kb / trace / revisions / skills）+ React + Vite + TS（10 个 feature 视图）+ docker-compose + nginx 反代，`make demo` 一键起 |
| 9 | robots.txt 等合规 | ✅ Y | `tools/robots.py` 真实实现（httpx + 标准 robotparser 语义）；collector ReAct 把 `robots_check` 列为合法 action（`collectors/logic.py:194-207`）；fetch 前置走 `_trace_robots`（`service.py:1655-1664`），不允许时直接 short-circuit 写 `Blocked by robots.txt` |

> **课题 9 项总评**：7 项全过 / 2 项基本满足（仅 `schema_pass_rate` 未作 metric 暴露 + SubagentContext.messages 未真填充）。**0 项缺失** —— 显著强于 CIMatrix 的 5/3/2。

### 1.1 D1–D9 符合度矩阵（方案 A）

| ID | 决策 | 状态 | 关键证据 |
|---|---|---|---|
| **D1** | Planner = LLM + web_search，验证竞品名，输出 `AnalysisPlan` | **部分** | `planner/logic.py:38-99` 走 LLM scope step；`:120-178` `_discover_competitors` 用 `_trace_search` + LLM JSON。**短板**：未对 competitor 名做权威验证（无域名探活/反证搜索）；`homepage_hints` 退化为 `google.com/search?q=…` 占位 URL（`service.py:142`） |
| **D2** | Collector / Analyst 子 agent 内部 ReAct loop，出口 `RawSource[]` / partial KB | ✅ 完整 | Collector ReAct: `collectors/logic.py:39-130`（topic 级）、`:132-313`（per-competitor，7 actions）；Analyst ReAct: `analysts/logic.py:92-196`（强制 inspect_sources / validate_citations 才能 finish）。出口模型严格 |
| **D3** | yaml 驱动 skill registry，≥ 4 维度 | ✅ 完整 | 6 个 skill: `pricing / feature / persona / review / integrations / security`，`registry.py` 自动发现。**小瑕疵**：`integrations / security / review` 在结构化 KB 容器里只能塞进 `feature_tree` 分支（`analysts/logic.py:910-917`），还没拿到一等公民槽位 |
| **D4** | QCIssue 携 RedoScope，按 scope 路由 | ✅ 完整 | `RedoScope.kind` 五值 enum；`orchestrator/scoping.py:4-29` 定中心化映射；最终 QA HITL 走 `qa_hitl` 条件边（`graph.py:47-58`） |
| **D5** | comparator 节点产出 `ComparisonMatrix` | ✅ 完整 | `comparator/logic.py:10-83` 完整 cell + winner_by_dimension + summary，QA 一致性校验在 `qa/logic.py:693-820` |
| **D6** | reflector 节点主动找 self-found gaps | ✅ 完整 | `reflector/logic.py:11-70` 在 comparator 之后、writer 之前；`_build_reflector_qa_issues:72-106` 把覆盖空缺/置信度异常喂回最终 QA |
| **D7** | KB cache `(competitor, dim, content_hash)` → SQLite | ✅ 完整 | `memory/kb_cache.py:25-108`，PK `(competitor, dimension, content_hash)`；hit 路径 `analysts/logic.py:442-478` |
| **D8** | HITL `interrupt()` × 2（planner / qa） | ✅ 完整 | `service.py:11` 引入 LangGraph `interrupt`，`_maybe_interrupt:820-876` + REST resume `routers/hitl.py:12-25` |
| **D9** | 双层 trace（SQLite + Langfuse）+ SSE swimlane | ✅ 完整 | 本地 SQLite 三表（trace_spans / agent_messages / tool_call_messages）；Langfuse 可选 mirror；SSE `routers/stream.py:10-25` |

**总评**：D2–D9 全部落地，D1 部分实现。落地度 ≈ **8.5 / 9**，骨架与脉络已贴合方案 A。

### 1.2 文档/工程纪律达标项

- **Schema-first**：所有节点出口 Pydantic `extra="forbid"`（RedoScope / QCIssue / RawSource / CompetitorKnowledge / ComparisonMatrix / TraceSpan / AgentMessage / ToolCallMessage / SkillSpec / KBCacheEntry 全覆盖）。
- **目录结构**：与方案 A §4 几乎逐行对齐（`packages/{schema,llm,tools,skills,agents,orchestrator,memory,observability}` + `app/{main,deps,routers,events}`），`docs/{architecture,schema,api_contract,skill_authoring,graph}` 齐备。
- **前端**：方案 A 列的 7 类视图全到（swimlane / graph / trace / kb / report / revisions / hitl / cost / discovery / messages，10 个 features 目录）。
- **dev/prod 双路径**：conda + pnpm dev、Docker + nginx demo，`Makefile` 命令固化。
- **契约同步**：`scripts/export_openapi.py` + `frontend/openapi.json` 已存在。
- **持久化**：`runs/` 下落 `traces.db / kb_cache.db / run_journal.db / graph_checkpoints.db`（SQLite WAL），符合方案 A §10b 的"演示重跑省时间"。

### 1.3 不足与改进建议（优先级从高到低）

#### Gap-1 ⚠️ Planner competitor 验证薄、homepage_hints 是占位 URL（D1 短板）
- **现象**：`_real_planner_step` 仅靠 LLM 自行说"X 是竞品"，未加 domain probe / 反证搜索；`homepage_hints` 直接合成成 `google.com/search?q=<name>`。
- **影响**：评分项"DAG 任务流转可视化、可追溯"在 planner 阶段失分；竞品名错会带病往下游传，浪费 collector token。
- **改进**：
  1. 给 planner 加 `verify_homepage(name) → {url, status_code, title_match}` 工具；明确 fail 则把 candidate 标 `selected=False`。
  2. 加 `cross_check_search(name)` —— 用 2 条不同 query 互相印证，全没 hit 视为 LLM 编造。
  3. 把 `CompetitorCandidate.confidence` 与 verify 结果挂钩，低于阈值（默认 0.6）的 candidate 自动剔除。

#### Gap-2 ⚠️ Sub-agent context.messages 实际未填充
- **现象**：`SubagentContext.messages` 字段定义存在，但 ReAct loop 里没有任何 `add_message` 调用；上下文隔离仅靠 `_trace_llm_json` 每次自己组 prompt。
- **影响**：方案 A §3 强调"子 agent 内部 messages history 完全独立、可单测"，目前是结构形式而非内容形式的隔离；如果哪天 ReAct 退化为多次调用复用同一 list，就会跨 branch 串扰。
- **改进**：在 `runner` 里把每轮 system / user / tool / assistant message append 到 `context.messages`，并以此做 prompt 拼装，单测用 `context.messages` 当输入快照。

#### Gap-3 ⚠️ 集成/replay 测试覆盖薄
- **现象**：`tests/integration/test_redo_routing_contract.py` 仅 22 行单 path；`tests/replay/test_trace_replay_contract.py` 仅 29 行单 assert；`tests/contract/test_skill_tool_modules.py` 21 行。
- **影响**：方案 A §11 风险表里 "ReAct 不收敛 / 工具死循环 / Skill yaml 写错" 没有自动化兜底，全靠人肉 review。
- **改进**：
  1. integration 至少补齐 `writer_only / comparator / analyst / collector / full` 五条 redo 路径各一个端到端测试，断言 "重做后 issue 数下降"。
  2. replay：从 `traces.db` 反向重建 timeline，断言节点顺序、span 数量、token 总量。
  3. contract：每个 skill yaml 都要有一个 round-trip 测试（yaml → SkillSpec → tools_allowlist 导出 → 重建 → equality）。

#### Gap-4 ⚠️ 3 个 seed case 没真正展示 5 种 redo_scope
- **现象**：`scripts/seed_cases.py` 里的 3 个 topic 在 `demo_mode=True` 下跑，且没断言 `RedoScope.kind` 类别覆盖。
- **影响**：方案 A §7 明确要求"3/3 种子 case 成功触发对应 scope"——这是评分项 35% 里"反馈闭环真实可触发"的硬证据。
- **改进**：把 seed case 重新设计成 5 个，分别针对 `writer_only`（伪造 phantom citation）/ `comparator`（matrix 单元格不一致）/ `analyst`（slice 空 KB）/ `collector`（fetch 失败）/ `full`（schema 验证失败），每个 case 落 `expected.json` 快照供 CI 校验。

#### Gap-5 ⚠️ `schema_pass_rate` 没作为 metric 暴露
- **现象**：方案 A §9 的 7 个评测指标里"Schema 通过率 100% Pydantic 验证"在 `RunMetrics` 里缺位（其余 6 个都有对应字段）。
- **改进**：在 `_refresh_quality_metrics` 里聚合所有节点出口的 `model_validate` 成功 / 失败次数，加 `schema_pass_rate: float`；前端 CostPanel 顺便展示。

#### Gap-6 ⚠️ 三个 graph 实现重复
- **现象**：`build_real_analysis_graph` / `build_scoped_redo_graph` / `build_demo_analysis_graph` 三套基本相同的边声明并存。
- **改进**：抽出 `_install_main_pipeline(graph, service)` 公共函数，三种入口只差头部节点（START → planner / redo_router / planner-demo）。否则一旦改图拓扑要同步三处。

#### Gap-7 ⚠️ Final-QA HITL 无独立轮次上限
- **现象**：phase QA 有 `attempts >= max_iterations` 兜底，但最终 QA 走 `qa_hitl → writer_only → writer → qa → qa_hitl` 这种链路时缺独立计数器。
- **改进**：在 `GraphState` 加 `final_qa_attempts: int`，超过 `MAX_ITERATIONS` 强制 `END` 并标记 `audit_stalled=True`。

#### Gap-8 ℹ️ Langfuse adapter 静默吞错
- **现象**：`langfuse_adapter.py:60-61` 整体 `try/except` 不打印不上报。
- **改进**：fall back 到 logger.warning + 一个 `langfuse_publish_failed` Prometheus counter。

---

## 第 2 章 CIMatrix 对课题要求的符合度

### 2.1 课题 9 项核心要求逐条核对

| # | 要求 | 评级 | 关键证据 |
|---|---|---|---|
| 1 | 多 Agent 角色划分（采集/分析/撰写/质检） | ✅ Y | 12 个 Agent，QC 独立（`agents/orchestrator.py:80-93`） |
| 2 | Pydantic 知识 Schema（功能树/定价/画像） | ✅ Y | `schemas/competitor.py`：core_features + pricing_model + target_users；`scenario.py` ProductBrief |
| 3 | DAG + 反馈闭环（QC 打回触发上游重做） | ⚠️ Partial | QC↔Analyst 重试存在（`runtime/local.py:49-73`），但规则可指 Discovery/Collector，运行时只回灌 Analyst —— **不能真重启上游** |
| 4 | 信息溯源 | ✅ Y | `Claim.evidence_ids` 强约束 + `EvidenceAuditAgent` + `R-EVIDENCE-001` 规则强制 |
| 5 | 可观测（prompt/IO/decision/token cost） | ⚠️ Partial | 全 agent + 规则事件 + 审计日志齐全；**但 token cost 完全未采集**（`llm/__init__.py:50-63` 丢弃 `response.usage`），原始 prompt 也未持久化 |
| 6 | LangGraph / CrewAI 编排 | ❌ N | `requirements.txt` 仅 openai/chromadb/sqlalchemy；自研 `AnalysisOrchestrator` —— 课题"考察要点"明确点名两框架 |
| 7 | 抗幻觉/上下文/错误恢复/超时降级 | ⚠️ Partial | 抗幻觉：`RedTeamAgent` + 7 条规则；旁路 agent try/except 优雅降级；**但 httpx timeout 写死、无指数退避、call_llm 失败一次 fallback 完事** |
| 8 | E2E 链路：采集→编排→KB→后端→前端 | ✅ Y | WebScraper + ChromaDB + FastAPI + SSE + 单页 HTML 2069 行 + docker-compose |
| 9 | robots.txt 等合规 | ❌ N | 全仓库无 `urllib.robotparser` / `robots.txt` 解析；`web_scraper.py:35-71` 直接 GET |

**总评**：5 条全过 / 3 条部分 / 2 条不达标（含一条课题点名的"LangGraph/CrewAI"）。

### 2.2 CIMatrix 的亮点（值得 plan_a 借鉴）

1. **三层竞品建模 L1/L2/L3** —— 直接产品 / 平台方案 / 模型供应商分层，每层独立 schema。L3 离线兜底 16 家厂商详情（pricing / rate_limits / coding_plan / user_feedback）。
2. **真实证据 jsonl 流水线** —— `data/real_evidence/evidence.jsonl` 143 条带 `source_url / confidence / collected_at`，配 `validate_real_evidence.py` 做关系校验、`seed_real_evidence.py` 同步到 ChromaDB。
3. **规则引擎驱动 QC** —— 7 条规则可热注册（`rules/definitions.py:230-285`），`action ∈ {reject, warn, block}` 分级 + `target_agent` 指向；比 prompt 让 LLM 自评确定性高。
4. **双库持久化** —— Postgres（结构化）+ ChromaDB（向量）。`AuditLog / ReportHistory / FeedbackStore` 都有 in-memory + Postgres 双实现，本地无 DB 不退化。
5. **MemoryAgent 偏好学习闭环** —— 从用户 feedback 提取 priority/constraint/dimension 偏好 → `memory_candidates` 表 → 用户确认后生效（rule `memory_requires_confirmation`）→ 下次同场景自动加载。
6. **动态场景生成** —— `scenario_id="custom"` 时 LLM 现场合成 ScenarioPack 落盘 (`scenario_packs/dynamic_*.json`)，绕开"必须预定义场景"。
7. **旁路增强非阻塞** —— EvidenceGap / RedTeam / Benchmark 三个 agent try/except 包裹，主链不被增强能力拖垮。

### 2.3 CIMatrix 的硬伤

- **未用 LangGraph/CrewAI**（课题点名失分）。
- **token cost 完全未追踪**（课题硬要求）。
- **robots.txt 合规缺失**（课题硬要求）。
- **DAG 反馈环退化** —— 规则虽指明 target_agent，运行时只重跑 Analyst。
- **prompt 文本未持久化** —— `agent.started/completed` 事件只带摘要 payload。
- **Evidence ↔ Competitor 关联用文本子串匹配** —— `comp.name in ev.snippet` 粗匹配，长名/英文名 collision 风险。
- **AnalystAgent 故意注入 bad claim** 演示 QC 打回（`analyst_agent.py:200-208`），更像 demo 装置而非真实业务逻辑。
- **L1.target_users 仅 List[str]**，缺人口学 / 痛点结构化字段。

---

## 第 3 章 plan_a vs CIMatrix —— 维度对照

### 3.1 直观打分（按课题评分维度）

| 评分维度 | 权重 | plan_a | CIMatrix | 优胜方 |
|---|---|---|---|---|
| 多 Agent 协作与输出可信度 | 35% | **A−**（schema-first + scoped redo + structured msg） | B+（多 agent + 规则引擎 + EvidenceAudit，但反馈环退化） | plan_a |
| 技术深度与工程完整度 | 25% | **A−**（LangGraph + 双层 trace + KB cache + HITL + checkpointer） | B（自研 orchestrator + Postgres+Chroma 双库；但无 LangGraph、token cost 缺失） | plan_a |
| 业务价值与产品体验 | 20% | B（前端 10 视图工程量大，但场景库浅） | **A−**（L1/L2/L3 三层建模 + 动态场景 + MemoryAgent 偏好闭环 + 真实证据治理） | CIMatrix |
| 代码质量与文档 | 10% | **A−**（Pydantic 全 forbid + ruff + 多层 tests + docs/ 齐备） | B（README 详尽但 tests 较少） | plan_a |
| 合规、材料与答辩 | 10% | B+（robots tool 已挂在 yaml allowlist 但实现未审，待确认） | C+（robots 完全缺失） | plan_a |

**主观折算**：plan_a 综合 88 / CIMatrix 综合 78。

### 3.2 维度细分对照

| 维度 | plan_a | CIMatrix |
|---|---|---|
| 编排框架 | **LangGraph + Send fan-out + checkpointer**（课题点名） | 自研 `AnalysisOrchestrator` + 遗留 `SequentialLangGraphWorkflow`（命名借用）|
| Agent 数量 | 7（planner/collector/analyst/comparator/reflector/writer/qa） | 12（含 Discovery / Structuring / EvidenceGap / RedTeam / Benchmark / Memory / Requirement） |
| Schema 严格度 | Pydantic `extra="forbid"` 全节点 | Pydantic v2 + 三层竞品独立 schema |
| 反馈闭环 | 5 级 RedoScope（writer_only/comparator/analyst/collector/full）真触发 | QC 重试 ≤ 2 次，**只回灌 Analyst** |
| 自评估 | reflector 节点 + ReflectionRecord + cross_competitor_gaps | RedTeamAgent + 7 条规则触发 warn/reject |
| 溯源粒度 | 每 claim → source_ids → RawSource(content_hash + url + confidence) | 每 claim → evidence_ids → Evidence(source_url + confidence + audit verdict) |
| 可观测 | trace_spans / agent_messages / tool_call_messages 三表 + token + 美元成本 + Langfuse 可选 | InMemoryEventBus + 30+ 事件类型 + audit_logs，**无 token cost** |
| 持久化 | SQLite × 4（traces/kb_cache/run_journal/graph_checkpoints） | Postgres + ChromaDB + in-memory 双轨 |
| 前端 | React + Vite + TS，10 个 feature 视图 | 单页 HTML 2069 行 + SSE 渐进渲染（无构建链）|
| 测试 | 10 unit + 2 contract + 1 integration + 1 replay | 较薄（README 未列具体覆盖率） |
| HITL | 双 interrupt（planner / qa）+ resume 协议 + 超时回退 | 仅"反馈表单"，无运行时 interrupt |
| 演示部署 | docker-compose + nginx 反代 + Makefile | docker-compose（含 postgres + chromadb） |
| 业务深度 | 6 个维度 yaml（pricing/feature/persona/review/integrations/security） | L1/L2/L3 三层竞品 + 动态场景 + 16 家 LLM 供应商离线库 |
| 合规 | robots.py 工具存在 | **完全缺失** |

### 3.3 plan_a 应该向 CIMatrix 学什么（改进建议）

| # | 借鉴点 | 落地方式 | 收益 |
|---|---|---|---|
| **B-1** | 三层竞品建模（L1/L2/L3） | 在 `AnalysisPlan` 加 `competitor_layer: Literal["product","platform","model"]`；不同 layer 走不同 skill 子集（model 层加 rate_limit / context_window 维度） | 业务价值 +5 分（可同时分析 SaaS 产品和 LLM 供应商） |
| **B-2** | 真实证据 jsonl 流水线 | 在 `runs/` 下加 `evidence_seed.jsonl`，由 `seed_cases.py` 写入 KB cache + RawSource 表；启动时校验 schema 一致性 | 演示稳定性 +（不依赖实时爬取） |
| **B-3** | 规则引擎驱动 QC | 把 `qa/logic.py` 的 hard-coded 检查抽成 `qa/rules/*.yaml`（severity / target_agent / target_subagent / rationale_template），动态加载 | 可观测性 +（评委能直接看到"是哪条规则触发的 redo"） |
| **B-4** | MemoryAgent 偏好学习 | 加 `packages/memory/preference_store.py`：把 HITL 时人工拒绝的 plan / 通过的 issue 抽成 `Preference`，下次 planner / qa 系统 prompt 注入 | 业务闭环 +（"用得越久越懂你"） |
| **B-5** | 动态场景生成 | 现在 plan_a 是 topic+competitor 输入；可加 `scenario_template` 字段，让 planner 根据 topic 自动选 dimensions（而非用户硬指定） | 易用性 + |
| **B-6** | 旁路增强 agent | 把 reflector 改造成 try/except 包裹的可选节点；新增可选 `BenchmarkAgent`（对比标杆产品）/ `RedTeamAgent`（红队挑刺） | 技术前瞻性 + |

### 3.4 CIMatrix 应该向 plan_a 学什么（如果 plan_a 团队要给队友建议）

| # | 借鉴点 | 落地方式 |
|---|---|---|
| **A-1** | 迁移到 LangGraph | `AnalysisOrchestrator` 重构为 `StateGraph`，复用现有 12 个 Agent.handle 方法作为节点函数；DAG 显式声明，反馈环用条件边 |
| **A-2** | RedoScope 5 级路由 | 把规则引擎的 `target_agent` 升级为 `RedoScope`，让 LangGraph 按 scope 真窄化重跑，而不是固定回灌 Analyst |
| **A-3** | 补 token cost | `llm/__init__.py:50-63` 加 `usage = response.usage`；事件 payload 加 `prompt_tokens / completion_tokens / cost_usd`；前端展示成本饼图 |
| **A-4** | 补 robots.txt 合规 | 给 `WebScraper.fetch` 加 `RobotFileParser` 前置检查，违反时抛 `RobotsDisallowed` + 写 audit log |
| **A-5** | 持久化 prompt | `agent.started/completed` 事件加 `prompt: str / response: str`；audit_logs 表新增列 |
| **A-6** | HITL 真 interrupt | LangGraph `interrupt()` + REST resume，替代单向反馈表单 |
| **A-7** | KB cache | 把 ChromaDB 之外加一张 `kb_cache(competitor, dim, content_hash)` 走 PG，演示重跑命中即返回 |

---

## 第 4 章 后续可扩展方向（plan_a + CIMatrix 共同视角）

按"实施成本 / 评分加成"二维排序：

### 4.1 短期（1 周内可落）

1. **schema_pass_rate 指标补齐**（plan_a：Gap-5）
2. **3+2 个 seed case 严格覆盖 5 种 RedoScope**（plan_a：Gap-4）
3. **Planner verify_homepage 工具 + cross_check_search**（plan_a：Gap-1）
4. **集成测试补齐 5 条 redo 路径 E2E**（plan_a：Gap-3）
5. **plan_a 引入 robots 合规测试**（确认 `tools/robots.py` 在 collector ReAct 真被调用）

### 4.2 中期（2–3 周）

6. **三层竞品建模 L1/L2/L3**（借鉴 CIMatrix）—— planner 选 layer，dim 池按 layer 过滤
7. **规则引擎驱动 QC**（yaml 化规则）—— QA 检查抽成 yaml
8. **真实证据 jsonl 流水线** —— 离线 seed + 在线增量
9. **MemoryAgent 偏好学习闭环** —— HITL 人工干预 → preference store
10. **Run 复盘 / Diff 视图增强** —— 现在 RevisionDiff 是单 issue 维度，可加"两次 run 整体 KB diff"

### 4.3 长期（>1 月，研究/前瞻向，对应 25% "技术前瞻"加分）

11. **自适应任务拆分** —— Planner 根据 `complexity` 估算和初步 search 结果，动态决定 collector ReAct 的 `max_turns` 和 dimensions 数量；甚至自动新增 yaml dim（"AI 生成 SkillSpec"）
12. **多 Agent 互评矩阵** —— reflector 拆成 `peer_review_collector / peer_review_analyst / peer_review_writer`，每个 agent 都有 1 个 peer 对它的 self-found
13. **动态 Schema 演化** —— 当一类 dim（如 "compliance"）反复在 reflector 里被发现是 cross_competitor_gap，自动生成 `compliance.yaml` 草稿放到 `skills/_pending/` 等用户审批
14. **多模态证据** —— pricing 页面截图 + OCR；用户访谈视频转写自动化（需补 ASR 工具）；前端 ReportView 加图片 / 视频内联
15. **Embedding 去重** —— `content_hash` 之上叠 `embedding similarity > 0.95 → 视为重复`，避免同 pricing 页面不同 URL（带 utm 参数）重复入 KB
16. **联邦 / 团队协作** —— 多人同 run、批注、版本控制（Git-style branch / diff / merge），适合企业落地
17. **跨 run 知识库累积** —— 把每次 run 的 `CompetitorKB` 落到全局 KB，下次同名 competitor 自动 prefill；和 KB cache 不同的是这是跨 run 而非单 run 内
18. **答辩可视化升级** —— 把 swimlane 升级为 Sankey 流量图（fan-out / fan-in 用宽度表示）；trace playback 加"按节点回放" + "按 token 消耗回放"双轴
19. **A/B run 对比** —— 同一 topic 跑两遍（不同 LLM / 不同 skill 组合），前端 A/B Diff 视图，量化模型选择对结果的影响 —— 直接对应"业务闭环 / 关键指标"评分项
20. **跨竞品价格归一化** —— pricing slice 出口加 `normalized_monthly_usd`（处理 annual 折扣 / 不同币种 / per-seat vs flat），让 ComparisonMatrix 真能横向对比

---

## 第 5 章 结论与行动清单

### 5.1 结论

- **plan_a 整体落地度对方案 A 约 88–90 / 100**：D2–D9 全到，D1 是唯一明显短板；Schema 严格度、scoped redo、HITL、双层 trace 都达成。
- **CIMatrix 对课题约 75 / 100**：业务建模深、数据治理强，但**关键工程项缺失**（LangGraph、token cost、robots 合规），DAG 反馈环退化。
- **plan_a 综合质量 > CIMatrix**，主要赢在工程纪律和评分项命中度；**CIMatrix 业务理解 > plan_a**，赢在三层竞品建模、动态场景、MemoryAgent。

### 5.2 plan_a 优先行动清单（按答辩前剩余时间）

**P0（必做，影响评分硬指标）**
- [ ] Gap-1: Planner 加 verify_homepage / cross_check_search 工具
- [ ] Gap-4: 5 个 seed case × 5 种 RedoScope，每个有 expected.json 快照
- [ ] Gap-5: `RunMetrics.schema_pass_rate` 暴露 + 前端展示
- [ ] B-1（借鉴 CIMatrix）: AnalysisPlan 加 `competitor_layer`，至少演示 L1+L2 两层

**P1（强烈建议，提升前瞻性 25% 那 3 分）**
- [ ] Gap-3: integration / replay 测试覆盖 5 条 redo 路径
- [ ] B-3: QA 规则 yaml 化（先抽 3 条 hard-coded 检查作为示例）
- [ ] B-2: 离线 evidence seed 流水线（演示稳定性）

**P2（锦上添花）**
- [ ] Gap-2: SubagentContext.messages 真填充
- [ ] Gap-6: 三个 graph 抽公共 install 函数
- [ ] Gap-7: final_qa_attempts 计数器
- [ ] Gap-8: Langfuse 错误可见化

### 5.3 CIMatrix 优先行动清单（如果两项目可合并交付）

**P0（直接对标课题硬要求）**
- [ ] A-1: 迁移到 LangGraph
- [ ] A-3: token cost 采集
- [ ] A-4: robots.txt 合规
- [ ] A-2: RedoScope 5 级路由（修反馈环退化）

**P1**
- [ ] A-5: 持久化 prompt 文本
- [ ] A-6: HITL 真 interrupt
- [ ] A-7: KB cache

---

> 报告生成于 2026-05-27 ｜ plan_a 与 CIMatrix 对照评审
