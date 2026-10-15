# 真实产品采集、报告验收与上下文压缩计划

> **For agentic workers:** 使用 executing-plans 顺序执行；修复使用 test-driven-development，完成前运行 verification-before-completion 与 requesting-code-review。

**Goal:** 用公开产品任务验证当前流水线，修复已复现的价格正文丢失，并减少 Comparator 重复输入，交付真实结果与未通过项。

**Architecture:** 复用 RunService 的内存存储、真实搜索及模型调用和已有 HTTP→webfetch_v2 路径。价格任务携带明确采集需求；基础正文缺金额且预算允许时尝试临时浏览器，仍缺价就记录事实缺口。压缩只删除与已传 Evidence View 完全相同的分析值，保留解释、引用、条件与缺口。

**Tech Stack:** Python、pytest、httpx、现有 webfetch_v2、现有 DeepSeek 配置。

## 范围与决策

- 用户已批准上一轮建议的下一步，按本计划直接实施，沿用已有隔离工作区。
- 初始优先静态高级提取；实际复核发现静态文本虽有金额，却丢掉套餐/席位标签或只保留附加项。执行中调整为：基础正文缺金额且预算允许才尝试浏览器，其余高级提取保持原路径；不使用模型补造价格。
- 已复现：Notion / Figma 返回 200，基础正文 149 / 169 字符且无金额；高级静态正文 8451 / 4428 字符，包含金额。长度达标导致高级路径未触发。
- 公开任务：Notion 文档知识协作、Figma 设计交付、iPhone duo 名称歧义；Pixel 官方支持页作为实物产品采集样本。
- 使用新建内存存储，不读取现有业务数据库。临时捕获和完整诊断保存在 `/tmp/plan_a_live_acceptance`；交付文档仅保存必要指标和短节选。
- 完整报告每个任务使用项目现有极简预算：最多 60 次原生 LLM 调用，外部搜索另计并单独记录；超时或质量阻塞不算通过。先跑一个实际任务，根据失败证据修复后再扩大。

## Task 1：固定公开任务的可复现验收

**Files:** 创建 `backend/scripts/eval_live_products.py`、`eval/live-product-acceptance-v1.jsonl`、`backend/tests/unit/test_live_product_acceptance.py`。

- [x] 测试不把失败/未结束/带阻塞报告判为通过；无效引用及缺产品分析单独记录。
- [x] 运行测试观察 RED，再实现纯摘要函数，明确机械指标不等同于事实正确性。
- [x] 复用 `RunService`、`RunJournal.in_memory()`、`KBCache.in_memory()`、`TraceStore.in_memory()`、`GraphCheckpointer.in_memory()` 和 `EnterpriseMemoryStore()`，显式 `execution_mode=real`。命令默认只列出任务；`--live` 才调用提供商。

```python
completed = await asyncio.wait_for(service.run_pipeline(detail.id), timeout=600)
summary = summarize_acceptance(completed)
assert summary['pipeline_terminal'] is (completed.status in {'completed', 'completed_with_blockers'})
```

- [x] 输出原生/搜索 span、成功搜索 span、最后尝试的提供商 Token、保守预算收费、总耗时与 span 耗时、来源质量、比较状态和报告。补充脱敏失败事件，并保持 JSON 可解析；取消时停止子任务。
- [x] 运行真实 Notion 基线与最终代码复跑，保留失败和预算数据。三组任务均无报告正文，记录完整报告未通过；公开价格证据单独核对。

## Task 2：价格内容缺失触发高级提取

**Files:** 修改 `backend/packages/tools/evidence_fetch.py`、`backend/packages/orchestrator/service.py`；测试 `backend/tests/unit/test_evidence_fetch_quality.py`、`backend/tests/unit/test_product_price_fetch.py`。

- [x] 使用基础正文 149/169 字符、价格缺失的固定样本，验证价格需求会尝试高级提取；非价格任务仍用快速路径；预算关闭、登录页、验证码仍停止。
- [x] 观察 RED，再增加仅用于价格任务的显式 `require_price_content` 参数。

```python
result = await fetch_evidence_page(url, require_price_content=True)
assert result.advanced_fetch_attempted
```

- [x] `_trace_fetch` 按当前分支维度传入参数，继续执行 robots、抓取次数和高级次数预算。高级结果仍缺金额时返回可解释失败，不将它标为价格采集完成。
- [x] 复核实际价格页并修正卡片提取、完整页准入重解析、币种冲突和 unknown 比较门禁。Figma 9 行 / Notion 3 行通过价格覆盖；不等同于完整报告通过。
- [x] 使用项目已有可选 Playwright 依赖，记录浏览器运行时及网络不稳定情况；不使用持久登录资料。

## Task 3：删除 Comparator 的精确重复输入

**Files:** 创建 `backend/packages/agents/comparator/context.py`，修改 `comparator/logic.py`；测试 `backend/tests/unit/test_comparator_context.py`。

- [x] 输入两个完全相同证据值、不同解释与条件，验证仅重复值被替换为事实 ID 引用，不同值、引用、缺口、价格限定不丢失。
- [x] 观察 RED，递归匹配 canonical JSON 的精确值；仅替换长度大于引用表示的内容。引用必须指向当前 Evidence View，不能引用缓存中的旧事实。

```python
compressed = compact_analysis_context(payload, view.facts)
assert compressed['different_condition'] == payload['different_condition']
assert len(canonical_json(compressed)) < len(canonical_json(payload))
```

- [x] 接入 Comparator 的现有有界上下文；保护嵌套条件与来源，提示词版本为 v3；不修改 Evidence View、快照。
- [ ] 对相同真实任务捕获的实际输入比较字节与估算 Token；模型对照记录实际提供商 Token，仍检查暂停比较、引用和条件保真。不能将字节缩减当作真实费用缩减。

未完成原因：真实任务均在 `collect_qa` 停止，尚无实际 Comparator 输入；不得以人工构造重复上下文代替完整流水线收益验收。

## Task 4：最终回归与交付

- [x] 定向回归与独立复审通过；最终后端 3183 passed、1 skipped，vendored 安全回归 7 passed。
- [x] 跨日交付保存到 `docs/optimization/2026-10-08-live-product-acceptance-results.md` 和同名 JSON：记录真实验收失败、采集成功范围、Token 代价与下一步。
- [x] 不将价格覆盖或机械评分当成全业务质量认证；完整报告及实际压缩收益仍未通过。
