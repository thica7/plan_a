# 双路检索与有界证据上下文补全实施计划

> 执行方式：使用 subagent-driven-development；实现、规格审查、质量审查依次进行。用户已明确批准本方向与离线执行，沿用现有工作区和未提交改动。

**Goal:** 保留原问句的信息，同时给取回的证据补足同一 canonical 文档内的前提上下文，并量化检索和 Agent 消费的变化。

**Architecture:** 原句与结构化子查询各自召回，结构化一路先内部 RRF，再与原句一路等权 RRF；最终精排使用完整原句。先固定排名锚块，再补同文档当前版本的短父级章节/全文或相邻块；锚块及其向量引用不改变，补全文本和原文坐标单独记录。后续 Collector 仍经过提取、准入及快照。

**Tech Stack:** Python、SQLite FTS5、Qdrant 本机模式、已下载 E5/BGE、本机 pytest。

## 范围与约束

- 离线：不采集新网页、不调用外部模型、不下载权重、不增加额度、不启动付费四产品流程。
- 保留上一轮未提交成果；基线为当前 intent-v7/lexical-v4，源码树 SHA256 `2b2c6e702906f153c6ebbe5499f02558664781f702f0f6dcbebd4244eb2b9ca8`。副本 `/tmp/plan_a_dual_context_baseline` 不参与修改。
- 原 8 题已人审但已曝光；新 16 题仍 candidate 且已曝光，不改金标，不称盲测或整体质量已合格。
- 现有工作区/项目、产品、维度、市场、来源角色、时间、版本、哈希和索引验证两路一致。
- `parent_document_id` 是版本链，绝不能作为父级上下文来源。父级仅来自当前文档内已验证的章节范围或短正文。
- 补全只增加可核对原文，不自动把邻近条件绑定为某项能力的前提。坐标不唯一/不匹配、旧版本、不合范围、超预算时明确跳过。
- 不改公开请求 schema。`RetrievalService` 构造参数 `enable_query_fusion=True`、`expand_context=True` 用于生产默认与离线消融；服务/策略版本进入缓存和诊断。

## Task 1：复现与实现双路融合

**Files:** `backend/packages/knowledge/retrieval.py`；新测试 `backend/tests/unit/test_dual_query_fusion.py`。

- [x] 写失败测试：原句独有来源仍进入候选；最多 5 条结构化子查询不会得到相对原句 5 倍票权；相同查询去重；raw 路径不额外规划；精排收到原句；各路 filters 相同。
- [x] 执行 RED：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_dual_query_fusion.py -q`。
- [x] 最小实现：先 `structured = _rrf_fuse_ranked_lists(fact_lists)`，再 `fused = _rrf_fuse_ranked_lists([original_hits, structured])`；仅有一条相同原句时只查一次；保留旧 `fact_query_results` 并记录两路与缓存版本。
- [x] `enable_query_fusion=False` 保留旧路径；不得在融合时改变过滤、扩大服务 top_k 或绕过 canonical 校验。
- [x] 回归现有 query intent、scope、cache、dense validation、Collector 单测，全部通过后交规格审查。

## Task 2：相邻与父级上下文

**Files:** 新建 `backend/packages/knowledge/evidence_context.py`；必要时修改 `ingestion.py` 与 `retrieval.py`；单测同上或新建 `test_knowledge_evidence_context.py`。

- [x] 先 RED：只有后半锚块命中时，前面的角色/工作区前提进入补全文本；原 `hit.text`、chunk ID 和排名不变。
- [x] 输出 `metadata.evidence_context`：当前文档 ID/version/hash、锚块 ID、原文 start/end、原文文本与 hash、覆盖块 ID、方法/省略原因。保留精确连续原文，重叠区间去重。
- [x] 短父章节或短当前全文优先；大范围退相邻块。每条补全文本最多 3000 字符，每次最多增加 6000 字符；不能为省预算截断原始锚块或表格。统计补全字符与跳过原因。
- [x] 老数据没有偏移时只在当前正文中唯一精确匹配；本轮未改 ingestion，兼容已有 source_start/source_end；从当前正文及章节恢复范围，无数据库迁移。
- [x] 缓存保存锚块结果，补全在返回前从当前 canonical 正文重建；不得信任文档元数据自带的同名补全字段。
- [x] 反例测试：同 URL 的旧版本、错工作区/项目/产品、历史报告、过期来源、重复文本导致歧义、伪造坐标、超预算、缓存后来源更正、父版本链、章节边界和不完整表格。

## Task 3：实际 Collector 与 Agent 消费

**Files:** `backend/packages/agents/collectors/kb_bridge.py`；新 integration `backend/tests/integration/test_dual_context_agent_alignment.py`。

- [x] Collector 使用可验证的补全文本组织证据，保留上下文溯源，不让维度摘要重新切掉必要前提；命中仍不是已准入事实。
- [x] 真实 RAG 工具、提取准入、canonical 入库、快照、Analyst/Comparator/Reflector/Writer/QA 逐项执行；网页字节与 LLM 回复固定重放且禁网，保留真实报告门禁。
- [x] 验证前提进入 Analyst 与 Writer，错产品/引用绑定仍被拒绝；来源更正后旧上下文与相关产物不得复用。Planner/Survey 保持既有范围和跳过约束。
- [x] 与既有 `test_agent_evidence_alignment.py`、`test_evidence_snapshot_repair.py`、`test_offline_agent_retrieval_alignment.py` 一起回归。

## Task 4：离线消融与效果记录

**Files:** `backend/packages/knowledge/product_benchmark.py`；`backend/scripts/eval_independent_retrieval.py`；对应 runner/benchmark 单测。

- [x] 先 RED：评测参数传递、锚块完整性校验保留、扩展片段必须是相同快照的精确区间，坏补全不能提高分数。
- [x] 可选消融：原句、仅结构化、双路（不补全）、双路（补全），每组比较 sparse/hybrid/hybrid+BGE，共 12 臂。旧默认六臂接口可继续执行，输出明确标记开关与版本。
- [x] 各臂共享 top-3、每路 top-20、精排上限 20 与相同数据；分开记录来源召回、锚块引文完整率、补全后引文完整率、额外字符量和候选池。
- [x] 固定数据、实际导入代码哈希前后验证；模型严格加载、本机权重、socket 禁网，外部模型调用 0。所有业务/规格修复完成再锁版跑模型，避免中途改码造成无效结果。
- [x] 原 8 题 formal 与 16 题 candidate-diagnostic 分别运行；候选的全库与指定产品范围分开呈现。不运行生成式回答评分或冒称独立验收。

## Task 5：最终验证与交付

- [x] SPEC → QUALITY 独立审查先完成行为验证，集中修复可复现 P1/P2，停止无关扩展。
- [x] 锁定源码哈希后跑完整后端测试；正常进程可见权限用于 `test_dev_runtime` 的 ps 归属检查。前端未变则核对哈希，不重复无关构建。
- [x] 中文 README、Agent 执行说明及 `2026-10-16-dual-query-context` 交付/结构化结果，写清收益、回归、预算代价、仍缺前提和未验收项；不把扩大量文本带来的引文覆盖称为排序提升。
- [x] 比对旧评测输入哈希、密钥模式/实际凭据字面扫描、`git diff --check`，确认最终源码与验证锁一致。

## 实施中发现并修复

- QA 贯通测试原本未断言审核结果；补断言后复现阻断，修正“此前已验证网页”的回放来源类型并检查真实 QA 零 findings，未放松生产 QA。
- 缓存诊断原本沿用冷请求调用数；本次执行零调用与冷排名来源已分开。
- 重复事实查询原本只去重搜索、未去重内部 RRF 投票；生产融合现已按规范化查询去重投票，关闭融合的旧对照维持既有行为。
- 评测首条重复锚块缺唯一坐标时可能触发空值比较；增加守卫，不能用后续片段的证据给 top-1 虚报命中。
- 当前源码锁：`29254d486597f2887bab8cb4074eed6afd643ab17fa3b30c338e5883b9e595a3`，898 个代码/配置/评测文件；本轮前端与评测资料未变。

## 验证完成记录

- 三份实际 E5/BGE 十二臂报告、480 条查询记录，旧对照逐题复现 v7，补全前后排名锚块不变，输入与实际导入代码哈希均匹配。
- 最终全量后端 4226 passed / 1 skipped / 202 existing warnings；跳过真实 Postgres RLS 连接项。首次全量旧测试夹具失败及修复后的完整重跑分别保留。
- 当前字节 SPEC 47 passed；QUALITY 代码行为 356+3 passed，夹具跟进 50 passed，范围重叠不相加。
- README、Agent 执行文档与本轮中文交付已更新；数据不改，稀疏旧5/6、新2/12未改善；不宣称真实生成准确率或整体RAG合格。
- 最终数值及校验见 [交付说明](2026-10-16-dual-query-context.md) 与 [结果](2026-10-16-dual-query-context-results.json)。
