# Product Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从目标产品出发发现各品类可解释的竞品。

**Architecture:** 在现有 RunCreateRequest 与 AnalysisPlan 中增加可选产品画像，保持旧请求兼容。Planner 用多种查询提出候选，并用匹配来源验证候选关系；通用品类抽取使用原文支持的能力字段。

**Tech Stack:** FastAPI、Pydantic、LangGraph、Temporal、React、TypeScript、Vitest、pytest。

---

### Task 1: 产品画像贯通 API、运行和 Temporal

**Files:** `backend/packages/schema/models.py`、`backend/packages/schema/api_dto.py`、`backend/packages/orchestrator/service.py`、`backend/packages/workflows/models.py`、`backend/packages/workflows/service.py`、`backend/packages/workflows/activities.py`、`backend/tests/unit/test_product_research_contract.py`。

- [ ] 先写失败测试：`RunCreateRequest(topic="清洁产品研究", target_product={"name":"示例吸尘器","category":"家电"}, dimensions=["feature"])` 能验证；`service.create_run()` 的 `plan.target_product.name` 保持一致；Temporal DataConverter 往返和 activity 入参保留画像。
- [ ] 执行 `.venv/bin/python -m pytest backend/tests/unit/test_product_research_contract.py -q`，确认字段缺失导致失败。
- [ ] 增加 `TargetProduct` 结构，包含 `name`、`official_url`、`category`、`audience`、`use_cases`、`market`；在 create_run 和 Temporal 传递；产品身份加入活跃运行指纹。其余调用使用默认 `None`。
- [ ] 重跑目标测试及 `test_temporal_workflows.py`、`test_run_service.py`，确认通过。

### Task 2: 通用品类发现和候选证据归属

**Files:** `backend/packages/agents/planner/logic.py`、`backend/packages/business_intel/homepage.py`、`backend/packages/research/discovery/planner.py`、`backend/tests/unit/test_product_discovery.py`。

- [ ] 先写失败测试：名单外 `Notion` 保留；无候选匹配的搜索结果返回空列表；画像生成产品名/品类/场景三种查询；有匹配来源的候选记录 `direct/adjacent/substitute` 关系与证据 URL。
- [ ] 执行 `.venv/bin/python -m pytest backend/tests/unit/test_product_discovery.py -q`，确认名单筛选和错误归属造成预期失败。
- [ ] 用目标产品信息构造去重发现查询；候选仅使用自身匹配来源；官网名单不负责剔除；关系字段使用兼容默认值，未匹配候选标记待核验。
- [ ] 重跑目标测试、`test_run_service.py` 中 planner/发现相关用例和 `test_identity_contract.py`。

### Task 3: 通用品类的能力抽取

**Files:** `backend/packages/research/models.py`、`backend/packages/research/extraction/feature.py`、`backend/packages/research/extraction/common.py`、`backend/tests/unit/test_generic_product_extraction.py`。

- [ ] 先写失败测试：品类为家电的资料“可更换电池、吸拖一体”产出带原文的通用能力条目，而无 `context_window`/`agentic_workflow`；没有画像的旧运行保持旧字段。
- [ ] 运行目标测试确认非 AI 产品仍被归入 AI 字段。
- [ ] 在 ResearchBrief 传递产品品类和场景；增加通用能力提取路径，保留精确引文；不为未提及能力作否定判断。
- [ ] 重跑提取、研究流水线、报告引用相关测试。

### Task 4: 前端产品入口与 API 类型

**Files:** `frontend/src/features/new-run/ScopeSection.tsx`、`frontend/src/features/new-run/useNewRunBuilder.ts`、`frontend/src/features/new-run/dimensions.ts`、`frontend/src/api/types.ts`、`frontend/openapi.json`、`frontend/src/api/openapi.ts`、`frontend/src/features/new-run/useNewRunBuilder.test.tsx`。

- [ ] 先写失败测试：新建运行必须有目标产品名称；可选官网、品类、用户、场景、市场进入请求；用户保留自定义研究重点；默认页面不再预填 AI 产品主题。
- [ ] 运行 `pnpm test -- src/features/new-run/useNewRunBuilder.test.tsx`，确认请求缺画像。
- [ ] 修改表单、构建器和通用入门预设；刷新 OpenAPI 类型，旧 API 调用字段保持兼容。
- [ ] 运行 `pnpm test`、`pnpm build`、OpenAPI 对照与交互真实性审计。

### Task 5: 分品类发现评测

**Files:** `eval/product-discovery-eval.jsonl`、`backend/tests/unit/test_product_discovery_eval.py`。

- [ ] 加四类固定离线样本，分别检查真实同类、相邻替代、歧义品牌和无证据候选。
- [ ] 测试候选召回、错误归属和名单外留存；基线先失败，修复后通过。
- [ ] 执行全后端 `pytest backend/tests -q`、全前端 `pnpm test` 与 `pnpm build`。
