# 项目验收审计记录：RAG KB / Collector / QA / Frontend Contract

日期：2026-06-20
分支：`rag-kb-optimize`

## 验收目标

本次按项目验收口径检查：

1. 是否存在隐藏的质量、契约或运行环境问题。
2. 哪些代码块过重，后续如何减轻。
3. RAG KB、collector、writer、quality gate、前端之间是否存在功能冲突。
4. 对低风险、高收益问题做直接修复，并留下可验证结果。

## 已修复问题

### 1. 后端 lint 隐患

执行：

```powershell
.venv\Scripts\python.exe -m ruff check backend --ignore E501 --fix
```

修复内容：

1. `typing.Sequence/Mapping` 迁移到 `collections.abc`。
2. writer section writer 中无意义的 `getattr(contract, "section_id")` 改为直接属性访问。
3. 多个 import 排序问题。

说明：未整体修复 E501，因为 `writer/logic.py` 存在大量历史长行；全量格式化会制造无关 diff，建议后续单独做 writer 拆分时一起处理。

### 2. 前端手写 API 类型漂移

发现：`frontend/src/api/types.ts` 的 `RawSource` 落后于后端 `packages.schema.models.RawSource`，缺少：

- `candidate_origin`
- `candidate_rank`
- `candidate_confidence`
- `fetch_method`
- `quality_score`
- `failure_reason`
- `metadata`

同时 `QCIssue.detected_by` 缺少后端已有的 `text_quality`。

修复：

1. 补齐 `RawSource` 手写类型。
2. 补齐 `QCIssue.detected_by` union。
3. `sourceBundle.ts` 从 Enterprise EvidenceRecord 构造 RawSource 时补默认 `candidate_origin/fetch_method/metadata`。
4. 更新 `ReportView.test.ts` 测试样例。

收益：后续前端可以直接标注 `candidate_origin="rag_kb"` 的 KB 复用证据，不会被 TS 类型挡住，也减少“后端变了、前端没变”的隐藏问题。

## 验收发现

### A. 代码块过重

按文件行数扫描，最大文件如下：

| 文件 | 行数 | 风险 |
| --- | ---: | --- |
| `backend/packages/orchestrator/service.py` | 4675 | 编排、trace、redo、projection 混在一起，修改容易互相影响 |
| `backend/packages/agents/writer/logic.py` | 4199 | writer 生成、修复、prompt、segment 逻辑过重，E501 集中 |
| `backend/app/routers/enterprise.py` | 3100 | API 聚合过重，路由/服务边界不清 |
| `backend/packages/agents/analysts/logic.py` | 3006 | analyst ReAct、结构化抽取、fallback 混合 |
| `backend/packages/agents/collectors/logic.py` | 2853 | collector 现在还承载 KB warm-start、web search、community、join 回写 |
| `backend/packages/agents/qa/logic.py` | 2199 | QA 规则增长快，适合拆 rule modules |

建议拆分方向：

1. `RunService`：拆 `trace_service`、`redo_service`、`projection_service`、`run_lifecycle_service`。
2. `writer/logic.py`：继续把 segment writer、assembler、repair、grounding prompt 移出 mixin。
3. `collector/logic.py`：把 KB warm-start、KB ingest、community source、official source discovery 拆成独立策略模块。
4. `qa/logic.py`：把 freshness、contradiction、citation、coverage 拆成 rule provider，统一输出 `QCIssue`。
5. `enterprise.py`：按 project/evidence/report/memory/runtime 分 router。

### B. 功能冲突检查

当前 RAG KB 分工基本成立：

| 模块 | 当前边界 | 验收结论 |
| --- | --- | --- |
| KB crawler | 采集、入库、search、kb-sync | 可用，但仍缺版本化/过期字段 |
| collector | KB warm-start、live 验证、RawSource 形成、KB 回写 | 边界正确，KB 只作为 candidate |
| writer | 只消费 RawSource/source token | 已避免裸 RAG 文本绕过证据链 |
| QA gate | freshness/contradiction/citation/coverage | 已能拦截过期和 KB/live 冲突 |
| frontend | 展示 report/source/search | 已同步核心 RawSource/QCIssue 类型 |

仍需注意：

1. Enterprise `kb-sync` 和 collect_join KB 回写是两条链路，职责不同：前者投影项目证据，后者沉淀 collector 采集结果。后续要在文档/trace 里持续区分。
2. QA contradiction 当前是启发式，不是完整 claim graph。它适合先挡住明显互斥，但不能替代结构化 claim validator。
3. 前端已有 generated OpenAPI 和手写 `types.ts` 两套类型，长期会继续漂移。建议逐步改成从 `components["schemas"]` 派生核心 DTO。

### C. 测试与验收环境问题

1. `npm run build` 在普通 sandbox 中会因 esbuild 子进程 `spawn EPERM` 失败；提权后通过。
2. Vitest 在普通 sandbox 中同样因 esbuild 子进程 `spawn EPERM` 失败；提权后目标测试通过。
3. 后端部分 `tmp_path` 测试在普通 sandbox 中会因 Windows Temp 权限失败；提权后 `test_advanced_fetch.py` 和 `test_batch_ingest.py` 通过。
4. 全量 `backend/tests/unit` smoke 在当前环境下被杀掉，退出码 137。建议 CI 分片，避免一次性跑完整巨型测试集。

## 本次验证结果

通过：

```powershell
.venv\Scripts\python.exe -m ruff check backend --ignore E501
.venv\Scripts\python.exe -m py_compile backend\packages\agents\writer\assembler.py backend\packages\agents\writer\prompt_builder.py backend\packages\agents\writer\section_writer.py backend\packages\agents\writer\segment_contract.py backend\packages\business_intel\release_gate.py backend\packages\enterprise\report_scope.py backend\packages\memory\run_journal.py backend\tests\unit\test_run_service.py
.venv\Scripts\python.exe -m pytest backend\tests\unit\test_run_service.py::test_collect_qa_flags_stale_kb_reused_source_for_refresh backend\tests\unit\test_run_service.py::test_collect_qa_flags_kb_live_source_contradiction backend\tests\unit\test_run_service.py::test_collector_warm_starts_from_rag_kb backend\tests\unit\test_run_service.py::test_collect_join_ingests_verified_raw_sources_into_kb backend\tests\unit\test_retrieval_params.py::test_sparse_mode_uses_sqlite_without_dense_vector_search backend\tests\unit\test_report_quality.py::test_writer_grounding_prompt_reuses_kb_only_via_source_tokens -q
.venv\Scripts\python.exe -m pytest backend\tests\unit\test_advanced_fetch.py backend\tests\unit\test_batch_ingest.py -q
npm run build
npm test -- src\features\report\ReportView.test.ts src\features\report\sourceBundle.test.ts
```

未作为通过项：

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\unit -q --maxfail=5
```

原因：当前环境下进程退出码 137，属于验收执行方式过重/环境资源问题。建议改为 CI shard，而不是继续扩大单次命令。

## 下一步减重建议

优先级 P0：

1. 把 full backend unit 改成分片任务：agent、business_intel、enterprise、knowledge、router、frontend 各自独立 job。
2. 为 RAG KB 建固定 eval set，覆盖 pricing 变更、功能下线、KB 旧资料 vs 新网页、竞品名称歧义。
3. 把前端手写核心 DTO 改为从 OpenAPI schema 派生，消除双类型源。

优先级 P1：

1. 把 collector KB warm-start / KB ingest 提取到 `packages/rag/collector_bridge.py` 或 `packages/agents/collectors/kb_bridge.py`。
2. 把 QA freshness / contradiction 拆出为 `packages/agents/qa/source_freshness.py` 与 `source_contradiction.py`。
3. 为 writer grounding prompt 建独立 contract 测试，防止裸 RAG 文本重新混入。

优先级 P2：

1. 清理 `writer/logic.py` 的历史 E501 长行。
2. 把 `enterprise.py` 路由按领域拆分。
3. 将 broad exception 分级：可降级路径保留，关键持久化/状态修改路径必须 trace + event + surfaced status。