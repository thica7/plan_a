# 方案 A · 图驱动优化版 —— "结构化骨架 + 智能节点"

> 立场：**LangGraph DAG 是骨架，每个节点内部允许是 ReAct 子循环，但产出必须是 Pydantic。**
> 参考：DeerFlow v1 的"Plan-Execute + research_team 路由"思想 +Anthropic Claude Research 的"sub-agent context 隔离"思想 +Competiscope 已验证的 schema-first 工程纪律。
> 目标分：≥ 88 分（35 + 25 + 18 + 9 + 9）。

---

## 0. 一句话定位

把 Competiscope 现有的 *固定 5 类节点 + Send fan-out* 升级为 *Plan-Execute 元循环 + 维度 plug-in + 子 agent 内部 ReAct + QA 分级路由*，让"加一个新分析维度"和"窄化重跑某个 sub-agent"都不需要改 graph 拓扑代码。

---

## 1. 关键设计决策（每条都对应一个具体痛点）

| # | 决策 | 解决的痛点 |
|---|---|---|
| D1 | Planner 升 LLM + 工具调用，输出 `AnalysisPlan` 时已经做过 web_search 验证 | v1 / Competiscope 的 planner 都是规则型，竞品名错也不会被发现 |
| D2 | 把 Collector / Analyst 的 4 个子节点改成 *子 agent + 内部 ReAct loop*，但出口仍写 `RawSource[]` / partial KB | 当前是硬编码 search→fetch→extract，遇到反爬或 SPA 没法自适应 |
| D3 | 维度（dim）从 4 个硬编码升级为 *yaml 驱动的 skill registry* | 加 "integrations" / "security_compliance" / "funding" 要改 graph |
| D4 | QA 输出 `QCIssue` 时携带 `redo_scope: enum`，路由按 scope 决定窄化粒度 | 当前任何 block 都跑全图重跑 |
| D5 | 新增 `comparator` 节点产出 `ComparisonMatrix`（schema 已定义但 graph 没节点） | Pydantic 模型定了却没人用，浪费 |
| D6 | 新增 `reflector` 节点 —— 在 QA 之前让一个 LLM 先看 `competitor_kbs` 的覆盖度对照 plan，主动生成 *self-found gaps*（不仅靠 QA 找问题） | 自我评估是评分项前瞻性加分 |
| D7 | 持久化 KB cache —— `(competitor, dim, content_hash) → CompetitorKB slice` 落 SQLite | 演示重跑省时间，体现工程深度 |
| D8 | HITL：planner 后 + QA 后 各一个 `interrupt()`，前端给"修改 plan / 覆盖 finding / 强制通过"按钮 | 答辩时演示"人机协同"加分 |
| D9 | Trace 双层：节点级落本地 SQLite +可选 Langfuse；前端 SSE 实时看 swimlane | 评分项明确要求 Token / Prompt / 决策可查 |

---

## 2. 节点级架构

```
                                ┌────────────────────────────────────┐
                                │ planner (LLM + web_search)         │
                                │ ↳ 验证竞品名、抽 homepage_hint     │
                                │ ↳ 选 dimensions、估 complexity     │
                                │ ↳ 输出 AnalysisPlan                │
                                └─────────────┬──────────────────────┘
                                              │
                                       interrupt #1（HITL）
                                              │
                       ┌──────────────────────┼──────────────────────┐
                       │  collector_dispatch  │  按 plan.competitors │
                       │   Send/(竞品×dim)   │  × dim_skills 注册    │
                       └──────────────────────┴──────────────────────┘
                                              │ fan-out
       ┌────────────────────────┬─────────────┴──────────────┬────────────────────────┐
       ▼                        ▼                            ▼                        ▼
┌──────────────┐         ┌──────────────┐             ┌──────────────┐         ┌──────────────┐
│ collector    │         │ collector    │             │ collector    │         │ collector    │
│ (skill=      │         │ (skill=      │             │ (skill=      │         │ (skill=      │
│ pricing)     │         │ feature)     │             │ review)      │         │ persona)     │
│              │         │              │             │              │         │              │
│ 内部 ReAct: │        │ 内部 ReAct: │            │ 内部 ReAct: │        │ 内部 ReAct: │
│  search →    │         │  search →    │             │  review_site │         │  survey_sim  │
│  robots →    │         │  fetch_doc → │             │  → fetch →   │         │  + interview │
│  fetch →     │         │  fetch_page  │             │  extract     │         │  synthesizer │
│  extract     │         │  → extract   │             │              │         │              │
│              │         │              │             │              │         │              │
│ 出口 schema: │         │ 出口 schema: │             │ 出口 schema: │         │ 出口 schema: │
│ RawSource[]  │         │ RawSource[]  │             │ RawSource[]  │         │ RawSource[]  │
└──────┬───────┘         └──────┬───────┘             └──────┬───────┘         └──────┬───────┘
       └────────────────────────┴────────────┬────────────────┴────────────────────────┘
                                              ▼ reducer: raw_sources += list
                                       ┌──────────────┐
                                       │ collect_join │
                                       └──────┬───────┘
                                              │ analyst_dispatch (Send/(竞品×slice))
       ┌────────────────────────┬─────────────┴──────────────┬────────────────────────┐
       ▼                        ▼                            ▼                        ▼
┌──────────────┐         ┌──────────────┐             ┌──────────────┐         ┌──────────────┐
│ analyst      │         │ analyst      │             │ analyst      │         │ analyst      │
│ (slice=      │         │ (slice=      │             │ (slice=      │         │ (slice=      │
│ feature)     │         │ pricing)     │             │ persona)     │         │ swot)        │
│ 内部 ReAct  │         │ 内部 ReAct  │             │ 内部 ReAct  │         │ 内部 ReAct  │
│ + 引用强校验 │         │ + 单位归一  │             │ + 情感聚合  │         │ + 跨竞品对照│
│              │         │              │             │              │         │              │
│ 出口: partial CompetitorKB（仅自己 slice）                                              │
└──────┬───────┘         └──────┬───────┘             └──────┬───────┘         └──────┬───────┘
       └────────────────────────┴────────────┬────────────────┴────────────────────────┘
                                              ▼ reducer: merge_kbs
                                       ┌──────────────┐
                                       │ analyst_join │
                                       └──────┬───────┘
                                              ▼
                                       ┌──────────────┐    新增节点
                                       │ comparator   │ ◀──产出 ComparisonMatrix
                                       └──────┬───────┘
                                              ▼
                                       ┌──────────────┐    新增节点
                                       │ reflector    │ ◀──主动找覆盖空缺、置信度异常
                                       └──────┬───────┘
                                              ▼
                                       ┌──────────────┐
                                       │ writer       │
                                       │ (确定性渲染 + LLM takeaway + phantom 剥离)
                                       └──────┬───────┘
                                              ▼
                                       ┌──────────────┐
                                       │ qa (4 lane) │
                                       │ + redo_scope │
                                       └──────┬───────┘
                                              │ interrupt #2（HITL）
                       ┌──────────────────────┴────────────────────┐
                       ▼                                            ▼
       ┌─────────────────────────┐                         qc_passed → END
       │ bump_iteration_routed   │
       │ scope ∈ {writer_only,   │
       │  comparator,            │
       │  analyst::<slice>,      │
       │  collector::<dim>,      │
       │  full}                  │
       └────────────┬────────────┘
                    │ 按 scope 路由回最早可重入点
                    ▼
              （回到 collector_dispatch / analyst_dispatch / writer 等）
```

---

## 3. 关于 "agent 的 context 是否要独立"

**结论：分层独立，shared state 共享。**

| 层 | context 处理 | 理由 |
|---|---|---|
| 子 collector / 子 analyst 的*内部 ReAct loop* | **完全独立** —— 每个子 agent 有自己的 `messages` history、tool call 轨迹、token bucket。Send payload 只塞它需要的东西，不传整个 state | (a) ReAct 推理需要工具调用 history 才不会绕圈，但其他 agent 的 history 是噪声；(b) token 直接降；(c) 子 agent 单测可独立打分 |
| 子 agent 之间 | **完全隔离** —— 互相看不到 messages。要交换信息只能落到 shared state | 满足"agent 间结构化消息传递"评分项 |
| Shared state（raw_sources / competitor_kbs / qa_findings / report_md） | **共享 + reducer 强制结构化合并** | 这是 LangGraph 的精髓，丢了就退化成 v2 |
| QA findings 注入到子 agent | 通过 `format_issues_for_prompt()` 渲染成 system prompt 段落，**不直接共享 messages** | 只让 redo 看到对它本子 agent 的 finding，反馈聚焦 |

**对照 DeerFlow v1**：v1 的子 agent（researcher/coder/analyst）每次被 research_team_node 调用时其实是把 `state["messages"]` 整段塞回去的 —— 这是**共享 messages 史**。我们这里**不**这么做。原因是竞品分析的"采集 → 分析 → 报告"链路太长，messages 累计会爆炸，且不同子 agent 关心的内容差异大。

**对照 DeerFlow v2**：v2 的 subagent context 完全独立但**产出也是非结构化 messages**。我们这里**保留 context 独立但出口必须落 Pydantic** —— 这是"结合二者"。

---

## 4. 目录结构（双仓 frontend / backend）

顶层物理拆分：`backend/`是Python项目，`frontend/` 是 React + Vite + TypeScript 项目，两边各自独立 lint / test / build。`docs/` 和 `docker/` 在仓根共享。

```
competiscope-v2/
├─ README.md
├─ Makefile                       # 一键 dev / test / build / docker
├─ docker-compose.yml             # backend + frontend + nginx 反代
├─ .env.example
│
├─ docs/
│   ├─ architecture.md            # 节点级 + swimlane
│   ├─ schema.md                  # Pydantic 模型字段说明
│   ├─ api_contract.md            # ★ HTTP/SSE 接口契约（前后端共识）
│   ├─ skill_authoring.md         # 怎么加新 dim
│   └─ graph.png                  # 自动导出
│
├─ backend/                       # =================== 后端 ===================
│   ├─ pyproject.toml
│   ├─ .python-version
│   ├─ ruff.toml
│   │
│   ├─ packages/
│   │   ├─ schema/                # 沿用 Competiscope，新增 RedoScope/QCIssue
│   │   │   ├─ models.py
│   │   │   ├─ messages.py
│   │   │   ├─ comparator.py
│   │   │   └─ api_dto.py         # ★ 给前端用的对外 DTO（与内部 model 解耦）
│   │   │
│   │   ├─ llm/
│   │   │   ├─ doubao_client.py
│   │   │   └─ json_extract.py
│   │   │
│   │   ├─ tools/
│   │   │   ├─ web_search.py
│   │   │   ├─ fetch_page.py
│   │   │   ├─ robots.py
│   │   │   ├─ search_review_site.py
│   │   │   ├─ find_official_docs.py
│   │   │   └─ survey_simulator.py
│   │   │
│   │   ├─ skills/                # 维度 plug-in（yaml 驱动）
│   │   │   ├─ registry.py
│   │   │   ├─ base.py
│   │   │   ├─ pricing.yaml
│   │   │   ├─ feature.yaml
│   │   │   ├─ review.yaml
│   │   │   ├─ persona.yaml
│   │   │   ├─ integrations.yaml
│   │   │   └─ security.yaml
│   │   │
│   │   ├─ agents/
│   │   │   ├─ planner/
│   │   │   ├─ collectors/        # 通用 ReAct runner + skill 实例化
│   │   │   ├─ analysts/
│   │   │   ├─ comparator/
│   │   │   ├─ reflector/
│   │   │   ├─ writer/
│   │   │   └─ qa/
│   │   │
│   │   ├─ orchestrator/
│   │   │   ├─ state.py
│   │   │   ├─ graph.py
│   │   │   ├─ scoping.py         # redo_scope → 路由
│   │   │   ├─ audit.py
│   │   │   └─ checkpointer.py
│   │   │
│   │   ├─ memory/
│   │   │   ├─ kb_cache.py
│   │   │   └─ run_journal.py
│   │   │
│   │   └─ observability/
│   │       ├─ trace_store.py
│   │       └─ langfuse_adapter.py
│   │
│   ├─ app/                       # FastAPI 应用入口
│   │   ├─ main.py                # uvicorn 入口、CORS、生命周期
│   │   ├─ deps.py                # 依赖注入
│   │   ├─ routers/
│   │   │   ├─ runs.py            # POST /runs, GET /runs/{id}
│   │   │   ├─ stream.py          # GET /runs/{id}/stream  (SSE)
│   │   │   ├─ hitl.py            # POST /runs/{id}/resume （interrupt 应答）
│   │   │   ├─ trace.py           # GET /runs/{id}/trace
│   │   │   ├─ kb.py              # GET /runs/{id}/kb       （快照查询）
│   │   │   ├─ revisions.py       # GET /runs/{id}/revisions
│   │   │   └─ skills.py          # GET /skills (列出可用维度)
│   │   ├─ events.py              # SSE 事件类型 + 序列化（与前端 types 同源）
│   │   └─ openapi_export.py      # ★ 启动时导出 openapi.json 给前端用
│   │
│   ├─ scripts/
│   │   ├─ export_openapi.py      # CI 调，输出到 frontend/openapi.json
│   │   └─ seed_demo_run.py       # 准备演示种子 case
│   │
│   ├─ tests/
│   │   ├─ unit/
│   │   ├─ integration/
│   │   ├─ contract/              # 含 API schema 快照测试
│   │   └─ replay/
│   │
│   └─ Dockerfile
│
├─ frontend/                      # ================== 前端 ===================
│   ├─ package.json
│   ├─ pnpm-lock.yaml
│   ├─ tsconfig.json
│   ├─ vite.config.ts             # dev proxy → /api → backend:8000
│   ├─ tailwind.config.ts
│   ├─ index.html
│   │
│   ├─ openapi.json               # ★ 由 backend export 生成（CI 强制同步）
│   │
│   ├─ src/
│   │   ├─ main.tsx
│   │   ├─ App.tsx
│   │   ├─ routes.tsx             # react-router
│   │   │
│   │   ├─ api/
│   │   │   ├─ client.ts          # fetch / SSE 客户端
│   │   │   ├─ types.ts           # ★ 由 openapi-typescript 自动生成
│   │   │   └─ hooks.ts           # tanstack-query hooks
│   │   │
│   │   ├─ stores/                # zustand
│   │   │   ├─ run.ts             # 当前 run 状态
│   │   │   └─ ui.ts              # 选中 swimlane / 选中 trace 等
│   │   │
│   │   ├─ pages/
│   │   │   ├─ NewRun.tsx         # 输入 topic / competitors / dimensions
│   │   │   ├─ RunDetail.tsx      # 主视图（多面板布局）
│   │   │   └─ History.tsx        # 历史 run 列表
│   │   │
│   │   ├─ features/
│   │   │   ├─ swimlane/
│   │   │   │   ├─ SwimlaneView.tsx     # 实时 (agent×swimlane) 气泡图
│   │   │   │   └─ useSseStream.ts
│   │   │   ├─ graph/
│   │   │   │   └─ StaticGraphView.tsx  # LangGraph 自动导出图（mermaid 渲染）
│   │   │   ├─ trace/
│   │   │   │   ├─ TracePlayback.tsx    # 决策回放（时间轴+prompt/output）
│   │   │   │   └─ TraceList.tsx
│   │   │   ├─ revision/
│   │   │   │   └─ RevisionDiff.tsx     # before/after markdown diff
│   │   │   ├─ kb/
│   │   │   │   └─ KbExplorer.tsx       # 浏览 competitor_kbs（结构化）
│   │   │   ├─ report/
│   │   │   │   └─ ReportView.tsx       # markdown 报告 + 引用悬浮卡
│   │   │   ├─ hitl/
│   │   │   │   ├─ PlanReviewModal.tsx  # planner 后的 interrupt
│   │   │   │   └─ QaReviewModal.tsx    # qa 后的 interrupt
│   │   │   └─ cost/
│   │   │       └─ CostPanel.tsx        # token / 美元估算
│   │   │
│   │   ├─ components/            # 通用 UI（按钮、卡片、tab、tooltip）
│   │   ├─ lib/                   # 工具函数（mermaid 渲染、diff 渲染）
│   │   └─ styles/
│   │
│   ├─ tests/                     # vitest
│   ├─ e2e/                       # playwright（演示前的冒烟）
│   └─ Dockerfile                 # multi-stage: build → nginx 静态托管
│
└─ docker/
    └─ nginx.conf                 # / → frontend, /api → backend, /api/stream → SSE
```

### 4.1 前后端契约同步（重要）

防止"前端写一份字段、后端改了字段没同步"的经典坑：

1. backend 启动 / CI 时跑 `scripts/export_openapi.py`，把 FastAPI 的 OpenAPI schema 写到 `frontend/openapi.json`
2. frontend 用 `openapi-typescript` 把 `openapi.json` 编译成 `src/api/types.ts`
3. CI 加一步 `git diff --exit-code frontend/openapi.json frontend/src/api/types.ts`，**schema 不同步直接 fail**
4. SSE 事件类型走 `backend/app/events.py` + `frontend/src/api/sse_types.ts` 双向手工对齐，加 contract test 校验

### 4.2 dev / prod 拓扑

**dev**：前端 `pnpm dev` 起 Vite (5173)，vite.config.ts 配 proxy 把 `/api/*` 转发到后端 `localhost:8000`，SSE 也走这个proxy；后端 `uvicorn --reload`。两个进程各自热更新。

**prod**（演示也用这个）：

```
        ┌─ docker-compose ─────────────────────┐
        │                                       │
client ─┼─▶ nginx:80                            │
        │     ├─ /          → frontend (静态)  │
        │     └─ /api/*     → backend:8000     │
        │                                       │
        └───────────────────────────────────────┘
```

一条 `make demo` 起完整环境，答辩前彩排不会出"前后端跑错端口"的事故。

---

## 5. 关键 Schema 增量

```python
# packages/schema/models.py 增量
class RedoScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "writer_only",        # 仅 phantom citation 等渲染层问题
        "comparator",         # 仅 ComparisonMatrix 不一致
        "analyst",            # 单 slice 重跑
        "collector",          # 单 dim 重跑
        "full",               # 必须从 collector 起
    ]
    target_subagent: str | None = None
    target_competitor: str | None = None  # 进一步窄化到单竞品
    rationale: str

class QCIssue(BaseModel):
    # ... 原字段
    redo_scope: RedoScope     # 新增
    self_found: bool = False  # 新增：是 QA 发现还是 reflector 自找

class ReflectionRecord(BaseModel):
    iteration: int
    coverage_gaps: list[str]              # "竞品 X 缺 pricing 的 source"
    confidence_outliers: list[str]        # 异常低 / 高
    cross_competitor_gaps: list[str]      # "只有 A 有 SWOT, B 没有"
    suggested_redos: list[RedoScope]
```

---

## 6. 关键节点伪代码

### 6.1 子 agent 通用 ReAct runner（核心新增）

```python
# packages/agents/collectors/runner.py
async def run_collector_subagent(
    skill: SkillSpec,                 # 来自 yaml
    competitor: str,
    qa_feedback: str,
    base_ctx: CallContext,
    client: DoubaoClient,
) -> list[RawSource]:
    """子 agent 内部 ReAct loop：自己决定调多少次工具，但出口是结构化的。"""
    tools = skill.bind_tools()        # web_search, fetch_page, robots
    msgs: list[dict] = [
        {"role": "system", "content": skill.render_system_prompt(qa_feedback)},
        {"role": "user", "content": f"Competitor: {competitor}\nDimension: {skill.name}"},
    ]
    facts: list[ExtractedFact] = []
    for turn in range(skill.max_turns):  # 默认 6
        out = await client.chat(msgs, tools=tools.descriptors, ctx=base_ctx)
        if not out.tool_calls:
            break
        for call in out.tool_calls:
            result = await tools.invoke(call.name, call.args)
            msgs.append({"role": "tool", "tool_call_id": call.id, "content": result})
            if call.name == "extract_facts":
                facts.extend(result["facts"])
    # 出口 schema 强约束
    return skill.facts_to_raw_sources(facts, competitor)
```

要点：

- 工具中包含一个特殊的 `extract_facts(url, body) → list[ExtractedFact]`，让子 agent 自己决定何时收口
- 出口走 skill 的 `facts_to_raw_sources()` 做 Pydantic 验证 + content_hash + confidence
- 失败/超 turn → 返回空 list，由 QA / reflector 兜底

### 6.2 Skill yaml 示例

```yaml
# packages/skills/pricing.yaml
name: pricing
subagent_class: PricingCollector
description: "Extract concrete pricing tiers (tier name, price, billing cycle)"
tools_allowlist:
  - web_search
  - robots_check
  - fetch_page
  - extract_facts
query_templates:
  - "{competitor} pricing plans cost"
  - "{competitor} site:*/pricing"
  - "{competitor} enterprise quote"
max_turns: 6
source_type: webpage
output:
  prefix: web
  confidence_default: 0.9
  confidence_no_url: 0.5
  required_dimension: pricing
```

加新维度（e.g. `integrations.yaml`）→ 写一个 yaml + 一个 prompt 文件。**不动 graph 拓扑**。

### 6.3 QA 计算 redo_scope

```python
# packages/agents/qa/scope.py
def assign_redo_scope(issue: QCIssue) -> RedoScope:
    if issue.detected_by == "citation":
        return RedoScope(kind="writer_only", rationale="phantom citation only")
    if issue.detected_by == "consistency" and "matrix" in issue.field_path:
        return RedoScope(kind="comparator", rationale="cell mismatch")
    if issue.target_agent == "analyst":
        return RedoScope(kind="analyst",
                         target_subagent=issue.target_subagent,
                         target_competitor=_extract_comp(issue),
                         rationale=issue.problem)
    if issue.target_agent == "collector":
        return RedoScope(kind="collector",
                         target_subagent=issue.target_subagent,
                         target_competitor=_extract_comp(issue),
                         rationale=issue.problem)
    return RedoScope(kind="full", rationale="unscoped block")
```

### 6.4 路由

```python
# packages/orchestrator/scoping.py
def route_after_qa(state) -> Command:
    if state.qc_passed: return Command(goto=END)
    scope = pick_priority_scope(state.qa_findings)  # 取最严重 scope
    if scope.kind == "writer_only":
        return Command(goto="writer", update={"redo_scope": scope})
    if scope.kind == "comparator":
        return Command(goto="comparator", update={"redo_scope": scope})
    if scope.kind == "analyst":
        return Command(goto="analyst_dispatch",
                       update={"target_agents_to_redo": ["analyst"],
                               "target_subagents": [scope.target_subagent]})
    if scope.kind == "collector":
        return Command(goto="collector_dispatch",
                       update={"target_agents_to_redo": ["collector"],
                               "target_subagents": [scope.target_subagent]})
    return Command(goto="collector_dispatch")  # full
```

---

## 7. 反馈闭环可信度（评分 35% 的核心）

要让评委相信"重做后输出有改善"，证据链必须完整：

1. **Revision before/after 必须落盘**（你 audit.py 已经做了）—— 前端 `RevisionDiff.tsx` 渲两栏 markdown diff
2. **convergence_ratio 量化**：每轮 issue 数 / 上轮 issue 数，期望 < 0.7；否则触发 audit_stalled
3. **窄化重跑可视化**：swimlane 上用红色高亮被 redo 的子 agent
4. **种子 case**：准备 3 个"已知会触发不同 redo_scope"的 case 作为答辩演示
   - case 1: 故意构造 phantom citation → writer_only
   - case 2: 故意让 pricing 子 agent 抓不到数据 → collector 窄化
   - case 3: 故意让 analyst 输出空 KB → analyst 窄化
5. **Reflector 主动 self-found** —— 让评委看到不仅是被动 QA 报错，系统自己也会找问题

---

## 8. 可观测性

### 8.1 双层 Trace

- **本地 SQLite**（`traces.db`）：每次 LLM call → 一行 `(trace_id, run_id, agent, subagent, swimlane, step, model, prompt, response, token_in, token_out, latency_ms, cost)`
- **Langfuse 可选**：`LANGFUSE_*` 环境变量在则镜像一份

### 8.2 前端（React + Vite + TS）

页面骨架是一个 RunDetail 主视图，多面板 tab 切换；运行中所有更新通过单条 SSE 流推送，前端按事件类型分发到对应 store/feature。

| 视图 | 路径 | 关键交互 |
|---|---|---|
| **Static Graph** | `features/graph/StaticGraphView.tsx` | mermaid 渲染 `docs/graph.mmd`，节点点击高亮当前 swimlane |
| **Swimlane 实时图** | `features/swimlane/SwimlaneView.tsx` | (agent × swimlane) 坐标，每个 LLM call 一个气泡；hover 看 prompt/output；当前活跃节点闪烁 |
| **Trace Playback** | `features/trace/TracePlayback.tsx` | 时间轴 scrubber，拖动看任意时刻的 prompt/output/tool call；支持按 agent 过滤 |
| **KB Explorer** | `features/kb/KbExplorer.tsx` | 树状浏览 `competitor_kbs[name]`，每个 fact 点击跳转到对应 RawSource 卡片 |
| **Revision Diff** | `features/revision/RevisionDiff.tsx` | before/after markdown 双栏 diff，红绿高亮 |
| **Report View** | `features/report/ReportView.tsx` | 渲染 markdown 报告；`[^src_id]` 鼠标悬停显示来源卡片 |
| **Cost Panel** | `features/cost/CostPanel.tsx` | 按 agent / 按轮次的 token + 估算费用饼图/柱图 |

**技术栈选型**：

- 路由：react-router
- 状态：zustand（run 状态）+ tanstack-query（API 数据）
- UI：tailwindcss + headlessui（轻量、无设计系统包袱）
- 图：reactflow 画 swimlane / 静态 graph；mermaid 渲染备用
- diff：react-diff-viewer-continued
- markdown：react-markdown + remark-gfm + rehype-raw（处理 `[^id]` 脚注）

### 8.3 HITL（前后端协议）

- 后端 `interrupt()` 触发后，SSE 推送 `event: interrupt`，payload 含 plan / findings + 推荐 redo_scope
- 前端弹出 `PlanReviewModal` / `QaReviewModal`，用户提交后 `POST /runs/{id}/resume`
- 超时（默认 60s）后端按"接受默认值"自动续跑，避免演示卡死

---

## 9. 评测指标（写进答辩）

| 指标 | 目标 | 测法 |
|---|---|---|
| 引用合规率 | 100% phantom = 0 | report 正则 vs raw_sources |
| Schema 通过率 | 100% Pydantic 验证 | 每节点出口 model_validate |
| 反馈闭环触发率 | 准备 3/3 种子 case 成功触发对应 scope | 自动化测试 |
| 收敛率 | 平均 ≤ 2 轮 QA 通过 | iteration_count 直方图 |
| 端到端时延 | 3 竞品 × 2 dim ≤ 90s | 计时器 |
| Token 成本 | ≤ ¥0.5/run | trace 聚合 |
| 覆盖度 | 平均 extraction_completeness ≥ 0.6 | 跑 5 个真实竞品 |

---

## 10. 3 周排期（按角色分轨）

> 假设 2 人协作：一个偏后端、一个偏前端，前端那位 W1 也帮后端写 schema / API。
> 单人也能跑，把"前端轨"压到 W2-W3 即可。

| 周 | Day | 后端轨 | 前端轨 |
|---|---|---|---|
| W1 | D1-2 | Skill registry + 4 个 yaml 改造 | 仓初始化（Vite+TS+tailwind+react-router）；接 `openapi-typescript` 自动生成 types；写 `api/client.ts` |
| W1 | D3-4 | 子 agent ReAct runner + 接现有工具池 | NewRun 表单 + RunDetail 骨架 + SSE 接入 + StaticGraphView |
| W1 | D5-7 | comparator / reflector + RedoScope 路由 | SwimlaneView（reactflow）+ ReportView + KB Explorer 雏形 |
| W2 | D8-9 | KB cache + checkpointer 断点续跑 | TracePlayback + Revision Diff |
| W2 | D10-11 | HITL interrupt 后端协议 + SSE 事件类型固化 | PlanReviewModal + QaReviewModal + 超时回退 |
| W2 | D12-14 | 3 个种子 case 联调 + 评测脚本 | CostPanel + 整体样式打磨 + e2e（playwright）冒烟 |
| W3 | D15-17 | 真实竞品压测 + 边界 case 修复 | 联动调优 + 错误态/loading 态/空态 |
| W3 | D18-19 | 文档 / 架构图 / 演示视频 / Dockerfile + nginx 反代 | 静态构建 + Dockerfile multi-stage |
| W3 | D20-21 | 答辩排练 | 答辩排练 |

### 单人 fallback

如果只有一个人，**前端用 Streamlit 起步、第 2 周末再迁 React 演示视图**——前面 8.2 列的视图按"答辩刚需"砍到 4 个：StaticGraph + Swimlane + Report + RevisionDiff，砍掉 KB Explorer / Cost Panel / TracePlayback（这些用 Streamlit 留着自己看）。

---

## 10b. 开发 / 交付指南（conda + docker 双路径）

**核心原则**：conda 管开发循环，docker 管交付演示。两条路径并行存在，**不互相替代**。

### 10b.1 路径分工

| 场景 | 路径 | 启动方式 |
|---|---|---|
| 日常改后端代码 | conda + uvicorn --reload | `make dev-backend` |
| 日常改前端代码 | pnpm + Vite | `make dev-frontend` |
| 后端单测 / lint / 类型检查 | conda | `make test-backend` |
| 前端单测 / e2e | pnpm | `make test-frontend` |
| 评测脚本 / 真实 LLM 联调 | conda | `make eval` |
| **演示给评委 / 录视频 / 交付** | **docker-compose** | `make demo` |
| 别人拿到代码自己跑 | docker-compose | `docker compose up` |

为什么不全用 docker：W1-W2 后端代码每天改几十次，每次重建镜像浪费 10 分钟。
为什么不全用 conda：交付时评委大概率没装 conda；nginx 反代、网络拓扑也只能 docker 表达。

### 10b.2 文件清单

```
项目根/
├─ Makefile                      # 双路径都封装好
├─ docker-compose.yml            # 演示一键起（backend + frontend + nginx）
├─ docker/
│   └─ nginx.conf
├─ backend/
│   ├─ environment.yml           # conda 环境（开发用）
│   ├─ pyproject.toml            # pip 依赖（被 environment.yml 引用）
│   ├─ .python-version           # 3.11
│   └─ Dockerfile                # 演示镜像
├─ frontend/
│   ├─ package.json              # pnpm 直跑
│   └─ Dockerfile                # multi-stage: build → nginx 静态托管
└─ .env.example                  # 仅 ARK_API_KEY 等敏感项
```

### 10b.3 environment.yml（conda 开发环境）

```yaml
# backend/environment.yml
name: bd-competiscope-v2
channels:
  - conda-forge
dependencies:
  - python=3.11
  - pip
  - pip:
      - -e ".[dev,trace]"        # 走 pyproject.toml
```

开发命令固定：

```bash
conda env create -f backend/environment.yml      # 第一次
conda activate bd-competiscope-v2
cd backend && pip install -e ".[dev,trace]"      # 同步依赖
make dev-backend                                  # uvicorn --reload
```

### 10b.4 Makefile（关键命令固化）

```makefile
.DEFAULT_GOAL := help
SHELL := bash

# ---- 开发路径 (conda + pnpm) ----
.PHONY: dev-backend dev-frontend
dev-backend:
	conda run -n bd-competiscope-v2 uvicorn app.main:app --reload --port 8000 --app-dir backend
dev-frontend:
	cd frontend && pnpm dev

# ---- 测试 / 评测 ----
.PHONY: test-backend test-frontend eval
test-backend:
	conda run -n bd-competiscope-v2 pytest backend/tests -q
test-frontend:
	cd frontend && pnpm test
eval:
	conda run -n bd-competiscope-v2 python backend/scripts/eval_seed_cases.py

# ---- 契约同步 ----
.PHONY: sync-openapi
sync-openapi:
	conda run -n bd-competiscope-v2 python backend/scripts/export_openapi.py \
	    > frontend/openapi.json
	cd frontend && pnpm openapi-typescript openapi.json -o src/api/types.ts

# ---- 演示路径 (docker-compose) ----
.PHONY: demo demo-build demo-down demo-logs
demo-build:
	docker compose build
demo:
	docker compose up -d
	@echo "→ http://localhost:8080"
demo-down:
	docker compose down -v
demo-logs:
	docker compose logs -f --tail=100

# ---- 帮助 ----
help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "%-20s %s\n", $$1, $$2}'
```

### 10b.5 backend/Dockerfile（最小可用）

```dockerfile
FROM python:3.11-slim AS base
WORKDIR /app
COPY backend/pyproject.toml backend/README.md ./
RUN pip install --no-cache-dir -e .
COPY backend/packages ./packages
COPY backend/app ./app
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 10b.6 frontend/Dockerfile（multi-stage）

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### 10b.7 docker-compose.yml

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    env_file: .env
    volumes:
      - ./runs:/app/runs           # trace.db / kb.json 落盘
    expose: ["8000"]

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    expose: ["80"]
    depends_on: [backend]

  nginx:
    image: nginx:1.27-alpine
    volumes:
      - ./docker/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    ports:
      - "8080:80"
    depends_on: [backend, frontend]
```

`docker/nginx.conf` 把 `/api/*` 反代到 backend:8000、其余到 frontend:80。SSE 路径要加 `proxy_buffering off`。

### 10b.8 引入节奏（贴在 3 周排期上）

| 阶段 | conda 用法 | docker 状态 |
|---|---|---|
| W1 全程 | 主力开发 | **不写**（先专注后端逻辑） |
| W2 D8-9 | 主力开发 | 在背景跑 `make sync-openapi` 即可 |
| W2 D12-14 | 主力开发 | **写 backend/Dockerfile + frontend/Dockerfile**（不一定要 compose 跑通，但镜像能 build） |
| W3 D17-19 | 减少使用 | **docker-compose 联调通**。本周后所有"演示式"运行都走 docker |
| W3 D20-21 答辩前 | 关掉 conda | **只用 docker-compose 排练**，避免依赖意外 |

**关键纪律**：W3 D19 起，禁止用 conda 演示。conda 跑得通而 docker 跑不通的代码，等于交付不了。

---

## 11. 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| ReAct 子 agent 不收敛 / 工具死循环 | `max_turns` 硬上限 + LLM 输出 `done` 信号 + audit_stalled 兜底 |
| Doubao 工具调用稳定性不如 OpenAI | 加 JSON-mode 回退路径（已在 `extract_json` 里做） |
| Skill yaml 写错没人发现 | 启动时跑 `SkillSpec.model_validate` + CI 校验 |
| HITL 把演示打断，时间不够 | interrupt 默认 timeout = 自动通过；演示模式可关 |
| 真实竞品反爬严重 | 准备 2 套 evidence fixture（真实抓取 + LLM recall fallback）作 demo 双轨 |

---

## 12. 何时选这个方案而非方案 B

- 你的领域（竞品分析）输出 schema **明确且稳定**（功能树 / 定价 / 画像 / SWOT）
- 评分项强调"结构化消息 + DAG 可追溯 + 反馈闭环可触发"
- 3 周时间盒，需要确定性高的工程
- 工程团队 ≤ 2 人

满足以上任一条 → 选 A。
