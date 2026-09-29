# 产品经理分析模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留 L1/L2/L3 研究视角，新增可验证的深度预算、全 AI/半人工流程与产品经理决策输出。

**Architecture:** 在运行契约中独立记录研究深度、协作方式与决策简报；纯预算策略为 Planner、Collector、LLM 和 Writer 提供同一组上限。LangGraph 在采集 QA 后新增受 assisted 控制的证据审核节点；前端显示三轴及审核载荷。省略新字段的旧请求继续走原路径。

**Tech Stack:** Pydantic、LangGraph、Temporal、FastAPI、React、TypeScript、pytest、Vitest。

---

### Task 1: 三轴契约及 Temporal 传播

**Files:** `backend/packages/schema/models.py`、`backend/packages/schema/api_dto.py`、`backend/packages/workflows/models.py`、`backend/packages/workflows/service.py`、`backend/packages/workflows/activities.py`、`backend/packages/orchestrator/service.py`、`backend/tests/unit/test_research_modes.py`。

- [ ] 写失败测试：`RunCreateRequest` 能接受 `research_depth="quick"`、`collaboration_mode="assisted"`、`decision_brief={...}`；服务计划保留它们；旧请求不改变行为；`collaboration_mode="ai"` 与 `hitl_enabled=True` 冲突时验证失败。

```python
request = RunCreateRequest(topic="产品选择", dimensions=["feature"],
    target_product={"name": "洁净家"}, research_depth="quick",
    collaboration_mode="assisted",
    decision_brief={"decision_question": "优先改进哪一段体验？",
                    "primary_job": "快速清理宠物毛发", "success_metric": "任务完成率"})
assert request.research_depth == "quick"
```

- [ ] 运行 `.venv/bin/python -m pytest backend/tests/unit/test_research_modes.py -q`，确认因字段不存在而失败。
- [ ] 增加 `DecisionBrief` 与可选枚举字段，计划和活跃运行指纹保留三轴；Temporal 输入及 activity 入参原样传递。`_resolve_hitl_enabled` 对显式 collaboration mode 优先，旧分支不变。
- [ ] 运行目标测试、`test_product_research_contract.py`、`test_temporal_workflows.py`。

### Task 2: 深度预算策略及执行接线

**Files:** 新建 `backend/packages/research/budget.py`，修改 `backend/packages/orchestrator/service.py`、`backend/packages/agents/planner/logic.py`、`backend/packages/agents/collectors/logic.py`、`backend/packages/orchestrator/llm_execution.py`、`backend/packages/agents/writer/prompt_builder.py`、`backend/packages/agents/writer/logic.py`、`backend/tests/unit/test_research_modes.py`。

- [ ] 写失败测试：相同输入下 quick/standard/deep 的候选、来源、抓取和 LLM 上限单调增加；旧请求仍使用 Settings；超出显式竞品上限报错；Writer 的目标长度随深度变化。

```python
assert depth_budget("quick").target_sources < depth_budget("standard").target_sources
assert depth_budget("standard").target_sources < depth_budget("deep").target_sources
assert "4,000-6,000" in first_draft_prompt(quick_detail).user
```

- [ ] 运行目标测试确认缺预算函数或上限相同导致失败。
- [ ] 实现 `depth_budget()` 的固定三档和部署设置上限；在自动发现、ResearchBrief、Collector 目标来源、LLM RunLLMBudget、Writer 提示中应用。`None` 继续旧值，所有深度共用证据准入和事实时效规则。
- [ ] 跑目标测试、`test_research_pipeline.py`、`test_advanced_fetch.py`、`test_writer_structured_report.py`。

### Task 3: 采集后的证据审核关口

**Files:** `backend/packages/orchestrator/graph.py`、`backend/packages/orchestrator/service.py`、`backend/packages/agents/qa/logic.py`、`backend/packages/schema/api_dto.py`、`backend/tests/unit/test_evidence_hitl.py`、`backend/tests/unit/test_run_service.py`。

- [ ] 写失败测试：assisted demo 在 `planner_hitl → evidence_hitl → qa_hitl` 依次暂停；AI 模式无暂停；旧 `hitl_enabled=true` 仍只有两处；证据关口载荷列出来源与当前问题；`redo` 最多一次受深度与现有重试预算约束。

```python
assert detail.current_node == "evidence_hitl"
assert service.has_pending_interrupt(detail.id)
await service.resume(detail.id, HitlResumeRequest(decision="accept"))
```

- [ ] 运行定向测试观察 `evidence_hitl` 节点缺失。
- [ ] 在 real/demo/scoped-redo 图的 collect QA 后增加节点；复用 `_maybe_interrupt` 并扩展 current node、恢复路由和生命周期审计。证据页列原文来源、维度、日期、来源质量和 QA 问题；`redo` 在剩余轮次内回 collector，耗尽后保留问题并继续审核，不无限循环。
- [ ] 修改最终 QA `force_pass`：保留问题和审查理由，最终 release gate 仍独立判断；验证现有审核测试。
- [ ] 跑 `test_evidence_hitl.py`、`test_hitl_runtime_commands.py` 和相关 `test_run_service.py`。

### Task 4: 决策简报与产品机会输出

**Files:** `backend/packages/agents/planner/logic.py`、`backend/packages/agents/writer/prompt_builder.py`、`backend/packages/agents/writer/logic.py`、`backend/packages/agents/writer/structured_report.py`、`backend/packages/agents/writer/structured_renderer.py`、`backend/tests/unit/test_pm_decision_brief.py`。

- [ ] 写失败测试：用户的决策问题、任务与成功信号在 Planner/Writer 上下文中可见；demo 和真实报告契约含“产品机会与验证”；无引文的竞品事实只能标为待验证假设。

```python
assert "优先改进哪一段体验" in prompt.user
assert "产品机会与验证" in report
assert "待验证" in unsupported_opportunity
```

- [ ] 跑目标测试确认决策上下文和章节缺失。
- [ ] 在报告决策区明确引用 `decision_brief`；使用现有 claim/source tokens 构建机会与验证建议，缺事实依据时写待验证，保持旧报告章节兼容。
- [ ] 跑目标测试及 writer/report quality 测试。

### Task 5: 前端三轴与证据审核

**Files:** `frontend/src/features/new-run/DepthSection.tsx`、`frontend/src/features/new-run/ExecutionModePanel.tsx`、`frontend/src/features/new-run/RunReadinessRail.tsx`、`frontend/src/features/new-run/useNewRunBuilder.ts`、`frontend/src/features/new-run/types.ts`、`frontend/src/features/run-detail/planReview.ts`、`frontend/src/pages/RunDetail.tsx`、新建 `frontend/src/features/hitl/EvidenceReviewModal.tsx`、`frontend/src/api/types.ts`、`frontend/src/stores/i18n.ts`、对应 Vitest。

- [ ] 写失败前端测试：L1/L2/L3 标签为研究视角；选 quick/standard/deep 和 AI/assisted 会发送独立字段；决策简报与预算摘要可见；`evidence_hitl` 渲染来源审核且接受/补采能调用现有恢复接口。

```ts
expect(request.research_depth).toBe("quick");
expect(request.collaboration_mode).toBe("assisted");
expect(screen.getByText(/证据审核/)).toBeInTheDocument();
```

- [ ] 运行相关 `pnpm vitest run ...` 确认控件/请求缺失。
- [ ] 实现新控件和文案；`execution_mode` 继续表示真实/演示；半人工的三次暂停及全 AI 无等待说明清楚，成本栏只展示可保证的上限。
- [ ] 跑前端相关测试、`pnpm test`、`pnpm build`、交互审计。

### Task 6: 组合验收、文档和提交

**Files:** `frontend/openapi.json`、`frontend/src/api/openapi.ts`、`README.md`、`docs/optimization/2026-09-29-pm-modes-results.md`、后端与前端组合测试。

- [ ] 从后端导出 OpenAPI 并生成 TS；断言 API 文档和运行响应三轴一致。
- [ ] 用固定 demo 输入执行 3 深度 × 2 协作模式；验证预算单调、人工暂停/恢复、报告章节、旧请求兼容和无凭据 real 明确失败。
- [ ] 完整执行 `.venv/bin/python -m pytest backend/tests -q`、`pnpm test`、`pnpm build`、WebFetch 测试、最小运行及 Temporal 薄壳烟测、密钥扫描、Ruff 和 `git diff --check`。
- [ ] 记录真实模型/搜索不可测范围、测试计数和模式预算，代码审查后提交分支。
