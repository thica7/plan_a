# 检索意图与真实证据核查实施计划

> **For agentic workers:** 使用 subagent-driven-development，每项先失败测试、实现、SPEC再QUALITY；不重复请求已授权方向的执行许可。

**Goal:** 分离事实查询和输出指令，提供有界多事实检索，保留可复现评测与人审边界。

**Architecture:** 纯函数计划，复用 RetrievalService、SQL过滤、RRF及canonical回查；benchmark显式选择新计划，默认保留raw。

**Tech Stack:** 现有Python、Pydantic、SQLite FTS及pytest，无新增离线依赖。

设计：[检索意图设计](2026-10-04-retrieval-intent-design.md)。使用现有隔离工作树 codex/pastoral-desktop，基线 b1cb4d2。下载范围另行询问，等待期间推进离线部分。

## 任务1：意图合同与生产入口

**Files:** 新建 backend/packages/knowledge/query_intent.py、backend/tests/unit/test_retrieval_intent.py；修改 models.py、retrieval.py、backend/packages/tools/rag_retrieve.py；工具测试在 test_collector_knowledge_scope.py 增加。

- [x] RED：格式后缀不参与匹配、原问题不变；事实中的中文支持/消息保留/引用功能不删，未知格式保留；raw不拆分；空值、上限与额外授权字段拒绝。

```python
request = RetrievalRequest(query='AuroraCam X warranty；输出中文并保留出处',
                           mode='sparse', enable_query_rewrite=False)
plan = resolve_retrieval_plan(request)
assert plan.original_query == request.query
assert plan.queries == ('AuroraCam X warranty',)
assert plan.output_language == '中文'
assert plan.require_citations
```

- [x] 实现RetrievalIntent和请求字段、纯函数计划。required_terms与非产品名数字保留；诊断记录origin/version；不从答案或来源构造查询。
- [x] 真SQLite验证两事实、数字限制、错误scope/market/role、缓存隔离。changed plan绕过LLM rewrite，每条搜索沿用过滤，RRF去重，精排使用事实查询，返回原query，分组只记录最终保留chunk。

```python
request = RetrievalRequest(query='NimbusNote export and refund；answer in Chinese',
    retrieval_intent=RetrievalIntent(fact_queries=['export', 'refund']),
    workspace_id='ws', competitors=['NimbusNote'], mode='sparse')
response = await service.retrieve(request)
assert response.query == request.query
assert response.diagnostics['query_plan']['queries'] == ('export', 'refund')
```

- [x] RAG tool传入intent和policy；不改变服务注入scope。GREEN、Ruff、SPEC、QUALITY后提交。

```bash
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py -q backend/tests/unit/test_retrieval_intent.py backend/tests/unit/test_query_rewriting.py backend/tests/unit/test_retrieval_cache.py backend/tests/unit/test_knowledge_scope_retrieval.py backend/tests/unit/test_collector_knowledge_scope.py --tb=short
```

## 任务2：意图对照

**Files:** 修改backend/packages/knowledge/product_benchmark.py和backend/tests/unit/test_product_research_benchmark.py；新增独立tuning意图JSONL和对照结果，不改原evaluation三文件。

- [x] RED：默认raw使用原问题；structured去完整格式后缀，intent可做两事实；原问题/标签不变；重复ID、未知ID、答案字段及raw+intent拒绝。
- [x] API增加intent_policy='raw'、可空intent_plan_path；CLI增加--intent-policy raw|structured、--intent-plan。文件格式为每行query_id及intent对象，只按RetrievalIntent校验；记录真实query_plan和每条实际FTS表达式，保留现有指标及未执行模型状态。

```python
raw = await run_product_benchmark(*paths, mode='tuning-diagnostic', intent_policy='raw')
structured = await run_product_benchmark(*paths, mode='tuning-diagnostic',
    intent_policy='structured', intent_plan_path=intent_path)
assert raw['model_calls'] == structured['model_calls'] == 0
assert raw['queries'][0]['original_query'] == structured['queries'][0]['original_query']
assert not structured['semantic_quality_verified']
```

- [x] 独立虚构问题GREEN，SPEC、QUALITY后冻结；原候选仅跑一次raw/structured对照，保留输入hash，不迎合gold。旧词典不改。

## 任务3：官方核查与交付

**Files:** 新建docs/optimization/2026-10-04-product-source-audit.md、意图对照JSON及意图交付文档，更新本计划。

- [x] 整理5条重新访问的官方证据，区分AI核查与人审；每页只保存短引用，日期未知明确记录；Pixel截止月份为推算，动态价格不冒充开关已核实。
- [x] 依赖和缓存已检查；根据用户范围执行真实模型比较或记录未运行，不用hash代替。下载范围问题未回复，本轮记录未运行，不下载。
- [ ] 隔离完整回归、b1cb4d2增量Ruff、最终审查、提交文件扫描和diff check后提交，按已有授权推送分支并核对远端HEAD。

```bash
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py -q backend/tests --tb=short
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_lint_delta.py b1cb4d2
../plan_a/.venv/bin/python backend/scripts/scan_secrets.py
git diff --check
```

本轮可在人工审核未完成时改入口，但不能宣称正式RAG验收通过。
