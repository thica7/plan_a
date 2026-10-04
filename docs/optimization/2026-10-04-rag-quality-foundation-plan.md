# RAG 质量基础实施计划

> **For agentic workers:** 确认后使用 `executing-plans` 或 `subagent-driven-development` 逐项执行；每项先失败回放、最小实现、独立审查，再继续。

**Goal:** 先修复确定缺陷并建立真实检索验收所需的数据、结构分块和对照基线。

**Architecture:** 复用现有知识库的正文抽取、入库、FTS、Qdrant 与混合检索。正式样本使用共享资料集合和独立审核标签；模型比较使用隔离索引，降级结果与真实语义质量分开记录。

**Tech Stack:** Python、现有 SQLite / Qdrant 本地模式、pytest；模型依赖与服务方式单独确定。

设计：[质量基础设计](2026-10-04-rag-quality-foundation-design.md)。状态：任务 1 已完成；任务 2–4 为下一批多文件实施方案，按用户 AGENTS.md 先确认。这里没有将方案标为已实现。

## 任务 1：确定缺陷与准备资料（已完成）

**Files:** `backend/packages/knowledge/ingestion.py`、`backend/tests/unit/test_knowledge_token_estimates.py`、`eval/product-research-queries-draft.jsonl`、`docs/optimization/2026-10-04-rag-offline-baseline.json`。

- [x] 先补连续中文、中英混合与真实临时 SQLite 入库计数回放；观察 3 failed / 3 passed。
- [x] 仅将估算改为 `max(1, math.ceil(len(text.encode("utf-8")) / 4))`，明确离线估算，不修改真实账单或已有 chunk。
- [x] 相关回归 119 passed，Ruff / 差异检查通过，快速代码审查通过。
- [x] 编制 50 条待审核调研题，保存原 14 条合成检索基线；两者用途明确分开。

定向命令（使用本机已存在的隔离 runner）：

```bash
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py -q \
  backend/tests/unit/test_knowledge_token_estimates.py \
  backend/tests/unit/test_rag_index_recovery.py \
  backend/tests/unit/test_rag_retrieval_eval_runner.py \
  backend/tests/unit/test_batch_ingest.py \
  backend/tests/unit/test_knowledge_scope_storage.py \
  backend/tests/unit/test_knowledge_scope_retrieval.py \
  backend/tests/unit/test_repository_migrations.py \
  backend/tests/unit/test_document_versioning.py --tb=short
```

## 任务 2：固定资料与审核标签

**Files:** 新建 `eval/product-research-corpus.jsonl`、`eval/product-research-labels.jsonl`、`backend/tests/unit/test_product_research_eval_data.py`；问题草案仍保留原路径与状态。

- [ ] 为首批题采集官方资料，记录完整型号、市场、真实原文、日期、URL 与内容 hash；没有支持材料时明确保持未完成标签。
- [ ] 编制候选标签并核对原文位置；正式评测集合只接受明确审核的标签。参数调优与验收样本分开保存，不能先看验收结果再修改其答案。
- [ ] 写数据失败回放：ID 重复、引用不存在、quote 不属于原文、市场或型号不符、来源日期缺失、无答案和未标注混淆时拒绝正式评测。
- [ ] 核对全部 source 引用、原文位置与审核记录，报告审核完成数量和排除原因；不以“50 个问题”替代“50 个已审核样本”。

数据测试使用真实文件，下面是不可省略的原文合同：

```python
assert len(query_ids) == len(set(query_ids))
assert all(label["query_id"] in query_ids for label in labels)
for label in labels:
    assert label["review_status"] == "reviewed"
    assert label["reviewed_by"] and label["reviewed_at"]
    for proof in label["proofs"]:
        source = corpus_by_id[proof["source_id"]]
        assert source["text"][proof["start"]:proof["end"]] == proof["quote"]
```

正式结构在该任务首个测试中锁定；字段严格沿用设计的数据合同，不将用户输入或网页 metadata 当作授权信息。

## 任务 3：结构清洗与分块回放

**Files:** 必要修改 `backend/packages/crawler/parser.py`、`backend/packages/knowledge/ingestion.py`；新建 `backend/tests/unit/test_knowledge_structured_chunks.py`，沿用现有正文抓取 / 版本回归。

- [ ] 先补中文连续句子与英文小数边界失败测试，要求原文可核对，不插入改变引用含义的正文。
- [ ] 补标题、表头、价格与限制条件、脚注、重复导航回放；缺结构的输入保持显式缺口，不能虚构表头。
- [ ] 根据失败原因分别最小修正分句或解析输出；每次只改一个边界，保留原文与来源元数据。
- [ ] 用已固定资料重切新临时库，与原分块方式比较命中与引用。已有真实文档与快照不自动重切或升级。

中文与小数回放的固定输入：

```python
pipeline = IngestionPipeline(repo, object(), chunk_size=14, chunk_overlap=0)
sentences = ["基础套餐每月29.9元。", "包含权限管理与审计日志。", "仅限中国大陆市场。"]
chunks = pipeline._chunk_text("".join(sentences), "document-test", "body-hash", "")
assert [chunk.text for chunk in chunks] == sentences
assert "29.9" in chunks[0].text
```

该断言用于保证中文无空格时能保持完整句子，并不要求所有生产文档只有一种固定块长。

## 任务 4：检索对照与真实模型验收

**Files:** 复用 `backend/packages/knowledge/retrieval.py`、`embeddings.py`、`reranker.py`、`eval.py`；新建 `backend/packages/knowledge/product_benchmark.py` 和 `backend/tests/unit/test_product_research_benchmark.py`。原合成 benchmark 保持其契约用途。

- [ ] 先补原始查询不被 gold 修改、共享资料池与干扰样本、未审核标签拒绝、provider 降级不能登记语义通过的失败测试。
- [ ] 在临时库执行关键词基线；权限过滤和原引用合同必须保持，逐题记录命中与失败原因。
- [ ] 模型方式确定后，使用已有 BGE / HTTP 接口建立独立索引，记录实际 provider、模型、维度、索引版本；没有真实 provider 时返回不可验收，不能以 hash 替代。
- [ ] 比较关键词、dense、RRF、RRF + 精排四组；报告 Recall@k、MRR、nDCG、澄清 / 无答案行为和分组指标。记录索引耗时、p50 / p95 延迟与资源，不使用 mock token 数声明费用节省。
- [ ] 真正用于报告的引用和事实另做离线回放；Ragas 依赖和裁判配置到位后，再增加独立抽样评估，不将其加入每次生成的同步门禁。

provider 降级合同：

```python
status = provider.status()
semantic_provider_ready = (
    status["effective_provider"] not in {"hash", "uninitialized"}
    and not status["degraded"]
)
if status["degraded"]:
    assert not semantic_provider_ready
```

这个布尔值只表达模型是否真实就绪；质量是否达标还必须由正式评测决定。

## 交付条件与边界

- [ ] 必要定向与完整后端回归在临时 cwd / DB 执行，禁用环境文件与宿主付费凭据；有实际供应商调用时另记录明确额度和用途。
- [ ] 每个实现任务经过规格与质量审查；不放宽第二阶段快照、版本、授权和失效规则。
- [ ] 数据未审核、模型未就绪、HTTP Qdrant 或 Ragas 未执行时逐项记录，不生成伪通过结果。
- [ ] 保存实际对照结果、交付文档和提交，再按授权推送现有分支。

当前无需用户执行命令。接入真实模型前需要选择本地模型或已有服务；样本审核时需要确认研究范围及关键事实口径。模型方式可稍后决定，离线资料与分块工作不依赖该选择。
