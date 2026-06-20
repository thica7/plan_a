# RAG KB 与 Collector 衔接优化记录

## 本次背景

主线多 agent 编排和整体修改由同事继续推进。本次目标是检查 `collector` 与 RAG KB crawler 是否真正衔接，避免 KB crawler 独立运行但没有进入分析证据链，同时处理质量门禁中出现的信息不准确、过期和失真问题。

讨论中形成的原则：

1. KB 不能直接等于事实，只能作为 evidence candidate。
2. collector 负责验证、补新、过滤并形成 `RawSource`。
3. analyst/writer 只能消费 `RawSource` 和 `[source:...]` token，不能直接消费裸 RAG 文本。
4. quality gate 负责 freshness、冲突、引用、覆盖度等检查。
5. 高变化信息，尤其 pricing、feature、security，需要过期策略和冲突检测。

## 现状判断

RAG KB crawler 原本已经在项目里起作用，但更偏独立链路：

1. `backend/app/routes/knowledge.py` 提供 crawl、batch ingest、knowledge search 等接口，把网页写入 KB SQLite 和 chunk 表。
2. `backend/packages/rag/knowledge_bridge.py` 与 enterprise `kb-sync` 接口可以把 KB 文档投影为项目级 `EvidenceRecord`。
3. writer 原来会在 grounding 阶段直接调用 `rag_retrieve_tool`，把裸 RAG 命中拼进 prompt。
4. collector 的 `collect_join` 原来尝试把采集结果写回 KB，但代码访问了不存在的 `source.text/source.ok` 字段，并且异常被吞掉，所以回写不可靠。
5. collector 原来没有把 KB 作为 warm-start 输入，导致 crawler/KB 与 collector 主证据链仍然偏独立。

## 本次改动

### Collector 与 KB 衔接

1. collector 在真实采集前先做 KB warm-start：
   - 调用 `rag_retrieve_tool`。
   - 使用 `mode="sparse"`，避免没有向量库或 embedding 时阻塞采集。
   - 将 KB hit 转为 `RawSource(candidate_origin="rag_kb")`。
   - 继续走 `source_quality_problem`，KB 命中只作为候选证据。

2. collect_join 修复并收敛 KB 回写：
   - 新增 `_sync_collected_sources_to_kb`。
   - 只回写验证过、有 URL、高置信、质量通过的 source。
   - 回写 metadata 包含 `run_id/raw_source_id/crawl_run_id/collector_confidence/candidate_origin/fetch_method`，便于追责。
   - 回写时 `index_vectors=False`，先保证 SQLite 稀疏检索可用，避免 collect_join 被向量索引依赖拖住。

3. KB 污染防护：
   - 已跳过 `rag_kb` 自身复用来源，避免循环污染。
   - 已跳过低置信、失败、无 URL、文本太短、质量不通过来源。
   - 新增 source_type 白名单，只允许 official、verified webpage、review_site、trust_center、manual 等可信来源入库。

### RAG 检索能力

1. `RetrievalRequest.mode` 新增 `sparse`。
2. `RetrievalService` 支持 sparse-only 检索。
3. `rag_retrieve_tool` 支持 `mode/preset`，sparse 模式不加载 Qdrant/vector store。
4. `RetrievalHit` 增加 `fetched_at/last_seen_at/status`，让 collector 和前端能看到 KB 新鲜度线索。

### Writer 边界收紧

1. 移除 writer grounding 阶段直接注入裸 RAG dict 的逻辑。
2. writer 只提示可复用的 KB source token，例如 `[source:xxx]`。
3. 这样 writer 不会绕过 collector/QA 的证据链。

### Quality Gate

新增 collector 侧质量门禁：

1. Freshness gate：
   - pricing 默认 45 天。
   - security/compliance/privacy/procurement 默认 90 天。
   - feature/api/docs/model/integration 默认 120 天。
   - persona/user/customer/review/community 默认 180 天。
   - KB 复用证据缺少原始观察日期时给 warning。
   - real run 中过期来源会生成 collector blocker redo。

2. Contradiction gate：
   - 同一 competitor/dimension 下检测 KB reused source 与 live source 的互斥声明。
   - 覆盖 SSO/SAML/SCIM/SOC 2/API/free plan/enterprise plan/self-hosted 等高风险事实项。
   - pricing 下检测同 plan/cadence 的不同价格。
   - 发现冲突时不让报告直接选边站，而是生成 consistency blocker，交给 collector 重新验证。

### 前端同步

1. 重新导出 `frontend/openapi.json`。
2. 重新生成 `frontend/src/api/openapi.ts`。
3. 检索页支持 dense=0 时发送 `mode="sparse"`。
4. 检索页接住 `fetched_at/last_seen_at/status`，并把 KB 时间显示到现有 SourceCard。
5. 检索参数抽屉的 dense/sparse 权重范围从 `0..2` 修正为后端契约的 `0..1`，避免 422。

## Agent 协调方案

本次改动尽量不侵入主线 multi-agent 编排：

1. KB warm-start 是 collector 内部增强，不新增 orchestrator 节点。
2. collect_join 的 KB 回写是 non-blocking，失败只进入 trace/message，不阻塞主流程。
3. writer 不再主动拉 RAG，减少与 collector 的职责冲突。
4. QA gate 只生成标准 `QCIssue` 和 collector redo scope，沿用现有 redo 路由。
5. enterprise evidence bridge 继续存在，不被替换；它仍负责项目级 EvidenceRecord 投影。

最终分工：

| 模块 | 职责 |
| --- | --- |
| KB / crawler | 历史证据召回、减少重复抓取、提示可能来源 |
| collector | 验证、补新、过滤，形成 RawSource |
| analyst / writer | 只消费 RawSource 与 source token |
| quality gate | 检查引用、冲突、新鲜度、覆盖度 |

## 验证记录

已覆盖的重点测试与检查：

```powershell
.venv\Scripts\python.exe -m py_compile backend/packages/agents/qa/logic.py backend/packages/knowledge/retrieval.py backend/packages/knowledge/models.py backend/packages/agents/collectors/logic.py backend/tests/unit/test_run_service.py backend/tests/unit/test_retrieval_params.py
.venv\Scripts\python.exe -m ruff check backend/packages/agents/qa/logic.py backend/packages/knowledge/models.py backend/packages/knowledge/retrieval.py backend/packages/agents/collectors/logic.py backend/packages/tools/rag_retrieve.py backend/packages/tools/ingest_document.py
.venv\Scripts\python.exe -m pytest backend/tests/unit/test_run_service.py::test_collect_qa_flags_stale_kb_reused_source_for_refresh backend/tests/unit/test_run_service.py::test_collect_qa_flags_kb_live_source_contradiction backend/tests/unit/test_run_service.py::test_collector_warm_starts_from_rag_kb backend/tests/unit/test_run_service.py::test_collect_join_ingests_verified_raw_sources_into_kb backend/tests/unit/test_retrieval_params.py::test_sparse_mode_uses_sqlite_without_dense_vector_search backend/tests/unit/test_report_quality.py::test_writer_grounding_prompt_reuses_kb_only_via_source_tokens -q
.venv\Scripts\python.exe -m pytest backend/tests/unit/test_business_intel.py -k "stale or conflict" -q
.venv\Scripts\python.exe -m pytest backend/tests/unit/test_run_service.py -k "collect_qa_flags or warm_starts_from_rag_kb or collect_join_ingests_verified" -q
.venv\Scripts\python.exe -m ruff check backend/packages/agents/qa/logic.py backend/packages/knowledge/models.py backend/packages/knowledge/retrieval.py backend/packages/agents/collectors/logic.py backend/packages/agents/writer/logic.py backend/packages/tools/rag_retrieve.py backend/packages/tools/ingest_document.py --ignore E501
npm run build
git diff --check
```

结果：

1. 后端目标测试通过：`6 passed`。
2. business_intel stale/conflict 周边测试通过：`2 passed, 49 deselected`。
3. 前端 `npm run build` 通过。
4. `git diff --check` 通过，仅有 Windows autocrlf 换行提示。
5. ruff 在 `--ignore E501` 下通过；不忽略 E501 时，`writer/logic.py` 存在大量既有长行，本次没有做无关格式化。

## 后续建议

优先级最高：

1. 增加面向 RAG KB 的 eval set：
   - 已知 pricing 变更。
   - 功能下线。
   - 官网与第三方冲突。
   - KB 旧资料 vs 新网页资料。
   - 竞品名称歧义。

2. KB 文档版本化：
   - 同 URL 多次采集不要简单覆盖。
   - 保留 document version、raw_source_id、run_id、crawl_run_id。
   - 支持污染回滚。

3. 更细的 freshness schema：
   - `observed_at`、`last_verified_at`、`expires_at`。
   - 按 dimension/source_type 计算 freshness score。
   - 过期时强制 collector live verification。

4. 前端可解释性面板：
   - 展示 KB warm-start query。
   - 展示 accepted/rejected hit。
   - 展示 rejected reason、source_id、doc/chunk id。
   - 让质量门禁发现失真时可以直接倒查。

5. contradiction pass 升级：
   - 当前是启发式检测，适合先兜底。
   - 后续可以接结构化抽取或 claim validator，把冲突落成 `conflict_evidence`。

## 注意事项

本次曾尝试使用 `fast_context` 做代码语义检索，但本机缺少 Windsurf API Key，因此改用 `rg` 和源码核查完成。
