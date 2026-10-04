# 离线关键词召回实施计划

> **For agentic workers:** 使用 `subagent-driven-development`，逐项先失败测试、实现、SPEC、QUALITY；不在任务间重复请求已授权的确认。

**Goal:** 改善自然问句与常用中英文概念召回，同时记录噪声、引用覆盖及未验收状态。

**Architecture:** 复用 SQLite FTS；保留严格查询，增加有边界的术语查询。沿用原资料合同与检索服务，用独立合成调参资料验证，不修改原 evaluation 问题或标签。

**Tech Stack:** 现有 Python、SQLite FTS5、pytest；不增加依赖或模型调用。

设计：[召回设计](2026-10-04-lexical-recall-design.md)。用户已允许执行下一步，方案依照上一阶段确定的离线范围具体化；当前工作树 `codex/pastoral-desktop`，基线 `7527bd2`，定向初始验证 67 passed。

## 任务 1：有边界的双语关键词补召回

**Files:** 新建 `backend/packages/knowledge/lexical.py`、`backend/tests/unit/test_knowledge_lexical_recall.py`；修改 `repository.py` 的构造与两项关键词搜索、`retrieval.py` 的 canonical 元数据处理。不迁移索引或存储资料。

- [x] 先写真实临时 SQLite 失败用例：中文自然问句找到中文保修段，中文保修查英文 Warranty，英文 warranty 查中文段；未知词及 36 months 限制不匹配 24 months；不同型号 / 市场 / role / workspace 的强匹配在 top1 前排除。
- [x] 运行新测试观察 RED；基础资料只使用虚构产品，不能从当前 evaluation gold 提取词典。
- [x] 实现纯函数 `build_lexical_plan(query, competitors=None)`；返回严格表达式、补召回表达式、概念、literal、版本、禁用原因。使用设计中的 23 个通用概念，别名从 query 提取，保留原 query。

表达式合同：

```python
# 多个概念必须同时匹配，而同概念允许中英别名。
fallback = ' AND '.join([*concept_or_groups, *quoted_unknown_literals])
# 不用来源正文、source ID、quote 或 expected_facts。
assert plan.original_query == original_query
assert plan.fallback_query is None if plan.disabled_reason else bool(plan.fallback_query)
```

- [x] 仓库构造增加 `lexical_fallback=True`；严格基线保留 `_to_fts_query` 原行为与首个块命中保留的旧排序。两项搜索共用原过滤，不在 Python 后过滤替代 SQL；文档搜索只合并原文档，不将标题命中标成正文命中。
- [x] 正文严格匹配分数使用 `(0.75 + 0.25 / rank) * document_weight`，补召回正文 `(0.5 + 0.25 / rank) * document_weight`，严格标题 `0.1 / rank * document_weight`；同块去重，保留最佳路径。补召回只执行正文，严格正文不足 limit 才执行；标题不挤掉正文。
- [x] hit metadata 增加 `lexical_retrieval`（version/path/concepts），覆盖同名来源字段；服务 canonical 回查仍生效，先移除来源自带同名字段，仅 sparse 保留仓库生成的诊断，不把它作为可信事实或授权。仓库正文 / 来源 metadata 不写回。
- [x] 补英文完整词边界、数字位置、纯问法、不支持的主题、8/12 上限关闭补召回、标题弱命中和 stale 折权测试；定向 GREEN、Ruff、SPEC、QUALITY 后提交。

验证：

```bash
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py -q \
  backend/tests/unit/test_knowledge_lexical_recall.py \
  backend/tests/unit/test_knowledge_scope_retrieval.py \
  backend/tests/unit/test_retrieval_cache.py \
  backend/tests/unit/test_product_research_benchmark.py --tb=short
```

## 任务 2：独立调参模式及对照记录

**Files:** 修改 `backend/packages/knowledge/product_benchmark.py` 与其测试；新建三个 `eval/product-research-tuning-{corpus,queries,labels}.jsonl`，均虚构、候选、tuning。不改原三份 evaluation 文件。

- [x] 锁定共同合成资料与问题：保修中英双向、导出、退款、访客、月付 / 年付计费、同产品不同主题，另有未知主题与不满足数字限制题；加入错误型号、市场、历史角色、未来资料干扰。文本和来源 ID 唯一，避免入库去重 / 归档冲突。
- [x] RED：当前模式不能纳入 tuning；验证新模式不会跑 evaluation，原 formal 不能纳入 tuning 或 candidate。使用真实 SQLite，禁止修改原问题。
- [x] 添加 `mode=tuning-diagnostic` 与 `lexical_policy=strict|bounded` 参数、CLI 两项 choices；前者只选择 tuning，后者传到 `_BenchmarkRepository(..., lexical_fallback=...)`。记录 purpose_selected / purpose_excluded、词典版本 / hash、每题原 query 和实际 hit 路径。

关键调用：

```python
baseline = await run_product_benchmark(*tuning_paths, mode='tuning-diagnostic', lexical_policy='strict')
bounded = await run_product_benchmark(*tuning_paths, mode='tuning-diagnostic', lexical_policy='bounded')
assert baseline['model_calls'] == bounded['model_calls'] == 0
assert not bounded['semantic_quality_verified']
```

- [x] 答案题增记支持原文片段覆盖率与按来源去重的非 gold 来源数，仍不与 doc 主指标混算；澄清 / 数据不足的候选命中数不是模型行为或真实误报率。
- [x] GREEN + SPEC + QUALITY 后提交。保存相同 corpus / query / labels 的两政策结果与逐题来源序列；合成资料报告明确不能当语义验收。
- [x] 词典冻结后对原 13 条 evaluation 候选运行两政策一次，不依据其结果改词典或 gold，指标不要求达到预设数。

## 任务 3：人工审核准备、验收与交付

**Files:** 新建 `docs/optimization/2026-10-04-product-research-review-sheet.md`、召回对照 JSON 与召回交付 Markdown；更新本计划实际状态。

- [x] 生成 008 / 023 / 026 / 028 / 030 审核单，列原问题、候选事实、proof 原文、官方地址、市场 / 日期和完整性待确认项；不填人审身份或把执行许可当审核。
- [x] 冻结实现后在禁环境文件、清宿主付费凭据、临时 cwd / DB 下执行完整后端回归；进程管理测试需要的 ps 权限仅用于测试自身临时进程。
- [ ] 对比基线 `7527bd2` 的增量 Ruff，完整提交文件密钥扫描和 diff check；最终集成审查通过后提交交付文档与结果。
- [ ] 按已有授权推送现有分支并核对远端 HEAD；报告实际改进、失败及下一步，不宣称正式语义 / 事实质量通过。

完整回归：

```bash
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py -q backend/tests --tb=short
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_lint_delta.py 7527bd2
../plan_a/.venv/bin/python backend/scripts/scan_secrets.py
git diff --check
```

本轮无需配置模型服务、下载权重或改真实运行库。人工审核未完成时明确保留状态，真实模型比较留到后续。
