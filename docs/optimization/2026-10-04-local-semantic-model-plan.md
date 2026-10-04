# 本机真实多语检索实施计划

> 使用 subagent-driven-development，产品任务每项RED/GREEN→SPEC→QUALITY；父负责官方证据、数据版本、依赖下载、真实回放和Git。用户已确认执行范围。

**Goal:** 以真实本机权重比较召回、融合和精排，落实已审核事实及边界。

**Architecture:** 只加载本地权重的适配器，扩展现有benchmark显式dense/hybrid，临时SQLite与Qdrant；独立新资料版本保持旧基线。

**Tech Stack:** Python、Sentence Transformers、PyTorch、现有Qdrant/Pydantic/pytest；权重和运行缓存在/private/tmp。

设计：[本机模型设计](2026-10-04-local-semantic-model-design.md)。使用现有隔离工作树codex/pastoral-desktop，基线06d785a。

## Task 1：本地模型适配器

**Files:** 新backend/packages/knowledge/local_models.py、backend/tests/unit/test_local_retrieval_models.py。

- [x] 写失败测试：本地路径必需、加载只允许local文件/禁远程代码、E5前缀/BGE无前缀、规范化、维度/NaN/Inf校验、sigmoid分数及数量校验、错误不fallback、调用计数与状态。

```python
provider = LocalEmbeddingProvider(path, model_id='intfloat/multilingual-e5-small',
                                 revision='fixed-commit', device='cpu')
provider.embed_documents(['billing'])
provider.embed_query('计费周期')
assert provider.status()['inference_calls'] == 2
```

- [x] 最小实现：SentenceTransformer与CrossEncoder懒导入；明确路径/版本、CPUfloat32、batch4/max_length512；加载耗时和calls，模型失败抛出异常。
- [x] 隔离测试、owned Ruff、SPEC和QUALITY通过后提交准备完成；父独验21项，E5真实离线加载通过，另两模型前置检查进行中。

```bash
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py -q backend/tests/unit/test_local_retrieval_models.py --tb=short
```

## Task 2：真实向量评测与CLI

**Files:** 修改backend/packages/knowledge/product_benchmark.py、backend/tests/unit/test_product_research_benchmark.py；新backend/scripts/compare_local_retrieval_models.py及对应unit测试。

- [ ] RED：sparse默认无模型，dense/hybrid实际索引和搜索；hash/uninitialized/degraded拒绝；rerank显式启用；as_of/scope/role/canonical和proof指标保持；模型调用数和模式状态准确。

```python
report = await run_product_benchmark(*paths, retrieval_mode='hybrid',
    embedding_provider=real_provider, reranker_provider=real_reranker,
    candidate_top_k=20, enable_rerank=True)
assert report['modes']['rrf_rerank']['status'] == 'completed'
assert report['external_model_calls'] == 0
assert report['model_calls'] > 0
assert not report['semantic_quality_verified']
```

- [ ] 实现显式参数retrieval_mode/candidate_top_k/enable_rerank，临时Qdrant本地client、生产索引与检索服务；状态运行后读取、实际模型计数；旧默认和未执行模式保留。
- [ ] CLI以本地模型manifest/run参数执行一模型一进程的固定对照；清API凭据/禁.env、下载离线分开；保存输入/代码/模型hash、逐query及warm/cold资源口径，不让标签构造查询。
- [ ] 合成数据回归、SPEC后QUALITY冻结，不根据旧候选调词。

## Task 3：下载与审核资料

**Files:** 新eval/product-research-reviewed-v2-{corpus,queries,labels}.jsonl、facts.json及manifest；docs/optimization官方核查续记、下载manifest、依赖版本锁和交付文档。

- [ ] 创建/private/tmp独立venv，官方PyPI依赖安装并记录freeze；官方HF固定revision选择safetensors下载到/private/tmp/plan-a-rag-models，核对model_id/revision/文件hash；记录实际大小和设备。不发送用户资料到模型API。
- [ ] 重新核验Figma周期开关和各官方来源；新资料记录短引用/摘要和未知时间，人审project_user、本轮时间、限制范围，保留旧hash；结构化Pixel期限、Notion缺价、Figma六项金额/双条件、Slack两属性。
- [ ] load_dataset(require_reviewed=True)验5条审核及proof坐标/hash，不修改旧label或自动审核新造题；合成资料与正式新版本分开。

## Task 4：冻结比较与交付

- [ ] 运行两embedding的raw/structured × sparse/dense/hybrid/hybrid+rerank，旧候选诊断和新审核范围均保存；top5/pool20固定，不按结果调参。模型串行，截断512、CPUfloat32、独立进程RSS记录。
- [ ] 统计召回/覆盖/排序与误召回，明确资料补证影响不能归因模型；先比较同一corpus同一问题，再区分新旧版本。
- [ ] 完整隔离后端与06d785a增量Ruff，最终fresh审查、密钥扫描和diff检查；提交推送并核对远端HEAD；不以5题或本机模型调用替代全RAG验收。

```bash
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py -q backend/tests --tb=short
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_lint_delta.py 06d785a
../plan_a/.venv/bin/python backend/scripts/scan_secrets.py
git diff --check
```
