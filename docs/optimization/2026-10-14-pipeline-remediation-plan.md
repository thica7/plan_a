# 主流水线修复实施计划

> 使用 subagent-driven-development 按用户要求顺序实施；每阶段先复现/红测试，最小修改，规格审查，再质量审查。用户已批准五项修复，不在阶段之间请求继续确认。

**Goal:** 修复事实污染、Agent 阶段饥饿与产物消费，接通语义检索并补齐人工修订/下载/作用域授权和正式验收。

**Architecture:** 复用 LangGraph、RunService、snapshot/view、原子主张审核及 KnowledgeRepository；修改产生错误的接点，保留总预算、版本/租户边界和原文准入。五项按顺序完成，不并行修改互相依赖的生产模块。

**Tech Stack:** Python/FastAPI/LangGraph/Pydantic/pytest、SQLite/Qdrant local、本机 E5/BGE 与可选 cross encoder、React/TypeScript/Vitest。

## 基线

现有隔离工作树、HEAD `40e0f52`，上一轮后端3623通过/1跳过，前端258通过。完整流水线最新v7为completed_with_blockers；Analyst实际请求0；来源18/24、审核格14/24。开始时保存相关文件SHA，避免把既有未提交工作计为本轮改动。Python前缀：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python`。

## 1. 事实污染

文件：`backend/packages/agents/collectors/kb_bridge.py`、`backend/packages/research/evidence/snapshot.py`、`backend/packages/orchestrator/evidence_context.py`、`backend/tests/unit/test_structured_pricing_pipeline.py`、`backend/tests/unit/test_evidence_snapshot_scope.py`；必要时新增 `test_fact_market_provenance.py`。

- [x] 将隔离复现写成永久红测试，原文删除market、任务US、完整采集/准入/入库/封存/回答守卫；未知报价仍拒当前价。
- [x] 增加原文CN/请求US、旧canonicalUS/原文未知、明确原文US与合法上下文分类反例，并覆盖feature/persona事实。
- [x] 报价入库按来源证据市场保存，任务市场仅单独context metadata；其他目录可保留查询分类，但所有snapshot fact只使用normalized行真实市场，不由canonical分类覆盖。
- [x] 恢复入口校验旧封存快照：新执行不得复用污染事实；保留旧版本供审计，在合法接受边界生成新版本并失效受影响产物，不自动接受待审核来源。
- [x] 跑报价链/快照/知识作用域相关回归，按规格→质量审查修复具体反例。

目标断言：
```python
assert before.raw_market is None and after.fact_market is None
assert after.boundary_status == 'insufficient'
assert 'market' in after.missing_fields
```

验收记录：567 项相关回归通过；第五轮规格审查 SPEC_PASS，最终质量审查 QUALITY_PASS（另跑107项及4个独立恢复边界探针）。历史快照字节保持；结论限定来源隔离与接受边界，不代表报告语义质量已合格。

## 2. 阶段预算与可见状态

文件：`backend/packages/llm/execution_budget.py`、`backend/packages/orchestrator/llm_execution.py`、`backend/packages/agents/analysts/logic.py`、`backend/packages/orchestrator/search_execution.py`、trace/schema/frontend现有显示接点；测试 `test_delivery_budget.py`、`test_execution_limits.py`、`test_prompt_trace_metadata.py`。

- [x] 重放v7阶段准入并写预算红测试：有证据的四家Analyst不能全部被delivery reserve挡住，后续写作/审核仍能准入，总量不超限。
- [x] 将现有reserve泛化为所有必要阶段，绑定阶段身份与完成释放；依据原预算按任务规模分配，缩短重复输入而非调大总上限。
- [x] 本地准入失败不盲重试；trace明确transported/succeeded/fallback/skipped及原因，现有前端显示回退原因。
- [x] 验证重启恢复、未知usage、并发在途额度、cost/call保护、预算真不足的失败状态；完成两级审查。

目标断言：
```python
assert analyst_transport_requests > 0
assert total_charged_tokens <= 200000 and total_calls <= 60
assert writer_can_reserve and qa_can_reserve
```

验收记录：固定200000 token/60调用，482项受影响后端回归、8项前端trace测试与构建通过；默认深度None的采集侵占反例已修。最终规格SPEC_PASS、质量QUALITY_PASS。mock transport验证阶段准入，真实付费完整流程仍待统一验收。

## 3. 产物消费与绑定投影

文件：`backend/packages/agents/writer/dimension_writer.py`、`writer/logic.py`、`research/evidence/report_claims.py`、现有comparator/reflector上下文与prompt合同；测试 `test_dimension_writer.py`、`test_report_claim_audit.py`、`test_operation_projection.py`、`test_agent_evidence_alignment.py`。

- [x] 红测试验证analysis/matrix/reflection的合法产物确实传入维度写作；旧snapshot/hash和预算遗漏显式处理。
- [x] 写作生成明确操作绑定，审核按原文观察逐项验证角色/对象/effect/条件，矩阵不再靠中文动作词作为唯一归属。
- [x] 以Confluence阅读/分享、Nuclino评论/创建的已有来源遗漏作固定回归，保留Coda缺源状态。
- [x] 本轮路径支持产品×维度/操作范围的审核后局部重做，未影响段保留；清理无关账单话术，结论按比较判定生成。
- [x] 验证已审核全文合成、跨对象/否定/来源篡改/未审核修订反例，两级审查。

目标断言：
```python
assert prompt['upstream_analysis'] and prompt['comparison_assessment']
assert prompt['reflection_constraints']
assert reviewed_claim.operation == bound_observation.operation
```

验收记录：受影响17模块673项回归通过；泛主题操作候选与混合事实局部重做的两处审查P2修复后，254/116项必要回归分别通过。最终规格SPEC_PASS、质量QUALITY_PASS；根代理另跑47项价格/市场/预算跨阶段回归通过。操作ID由服务端绑定完整原文观察；普通非操作事实仍支持；显式地区要求保持严格。真实报告质量留统一验收。

## 4. 生产语义 RAG

文件：`backend/packages/knowledge/embeddings.py`、`local_models.py`、`ingestion.py`、`reranker.py`、`backend/packages/tools/rag_retrieve.py`、`agents/collectors/kb_bridge.py`、现有配置/启动接点；测试 `test_knowledge_embeddings.py`、知识检索/入库/作用域及Agent bridge现有测试，补新接线测试。

- [x] 核查本机现有权重/环境，以冻结模型 manifest加载，禁隐式下载与静默hash冒充。
- [x] 红测试检验实际Provider工厂、全文向量入库、Collector配置hybrid、tool可选精排和模型/租户版本隔离。
- [x] 复用本地E5/BGE适配器接生产配置；仅明确启用语义模式时建索引；摘要保持摘要身份，模型缺失降级诊断。
- [x] 用临时Qdrant local及生产Collector入口验证中文查询，比较sparse/hybrid/精排；新模式不得复用hash向量，禁网本机模型推理。
- [x] 与前三阶段snapshot/更正依赖回归并完成两级审查；不宣称小样本生产准确率。

目标断言：
```python
assert indexed_model_version == query_model_version
assert collector_hit.metadata['effective_provider'] != 'hash'
assert captured_source_scope == retrieval_scope
```

验收记录：664项相关回归通过；修复非strict dense缺模型降级及摘要索引回执两处审查P2，最终规格SPEC_PASS、质量QUALITY_PASS（独立98项及线程探针），根代理45项跨阶段回归通过。真实断网生产Collector/tool在持久Qdrant local上测试12候选、9组中英文检索，E5推理19次、精排6次，网络尝试0；旧hash命名空间重建不改原文/版本/抓取时间。纯空白清理后diff检查通过。生产配置须显式启用，HTTP Qdrant及完整报告留后续验收。

## 5. 正式验收与用户闭环

按5a→5b→5c顺序落地，每个子任务有独立红绿与两级审查。

### 5a. 运行授权和下载

文件：`backend/app/routers/runs.py`、`stream.py`、`trace.py`、`kb.py`、`revisions.py`、现有 `app/deps.py`、`packages/auth/rbac.py`、`enterprise.py`artifact接点。

- [x] 红测试用两个workspace隔离应用：列表过滤、详情/stream/trace/KB/revision/资料导入拒跨域；实际服务存储路径也不能绕过身份。
- [x] 使用现有服务端身份与workspace授权，不信任前端workspace或审批操作者字符串；保持无鉴权本地开发合同。
- [x] 本地报告artifact增加授权下载响应及Content-Disposition，路径穿越/外部URI/错误格式保守拒绝；保存版本关联与hash。
- [x] 人工新稿生成新claims/QA，新增或省略范围条件不可由词重合自动放行；未知标题/表头断言保守待复核，明确中性章节名可保留。
- [x] 复用RunJournal原子保存并恢复Memory模式报告父子版本/来源/主张与新QA，现有store投影不被旧journal覆盖；重启后可再改稿和重新导出。

验收记录：20模块361项相关回归；聚合作用域新增反例单独通过，最后7模块185项通过。最终规格SPEC_PASS、质量QUALITY_PASS，均另跑62项，独立真实API复现标题/表头八组合的新QA阻断与普通结构控制。无新增Ruff问题，diff检查通过。Memory恢复限本机报告版本投影；旧artifact登记不恢复，可重新导出；无可靠语义核验的新措辞仍保守待复核，连续人工排版修订可能需再审。最终同代码全量与真实模型仍待5c。

### 5b. 前端改稿、下载与项目检索

文件：`frontend/src/features/run-detail/RunReportReviewStudio.tsx`、`features/workbench`报告接点、`api/client.ts/http.ts`、`pages/SearchPage.tsx`、`pages/CrawlPage.tsx`、`stores/i18n.ts`及对应测试。

- [x] 红测试确认改稿提交真实API、重验后刷新新版本和质量；下载获取Blob并触发浏览器文件保存，携带认证；错误可见。
- [x] Search/Crawl通过项目入口选择/保留project_id和include_workspace_library，作用域切换不混用缓存。
- [x] 沿用明亮像素视觉及中文文案，通过相关前端测试和TypeScript/build；全量与真实浏览器留5c最终统一验收。

验收记录：首版14文件70项相关前端测试通过，实际RunDetail切换未缓存run导致编辑器卸载丢未保存稿的P2修复后，31项必要回归与构建通过。最终规格SPEC_PASS（另跑15项及3独立探针）、质量QUALITY_PASS（另跑28项），24文件SHA匹配、diff检查通过。未保存稿按服务端workspace/project/run/version保留于页面会话，保存成功仅清同正文草稿。当前后端旧服务尚未重启，真实浏览器留5c。已如实禁用无后端接口的单采集任务retry/delete，保留按范围的来源重采集。

### 5c. 正式数据与完整复验

文件：`eval/`版本化独立候选集、审核清单、现有 `backend/packages/knowledge/product_benchmark.py`、`backend/scripts/eval_live_products.py`与交付文档。

- [x] 纳入新8题及官方证据：用户已明确“1–8均认可，按这些边界审核”，固定审核记录和数据SHA；新6源加旧人审16源组成22源。评测仍待执行，不把已曝光小样本当盲测或泛化证明。
- [x] 隔离全量后端测试、前端测试/build、独立审查、作用域/真实性反例；source SHA、实际凭据扫描、diff check。最终后端4019通过1跳过；前端相同源码279通过及构建；详见正式验收记录。
- [ ] 使用最终同一代码SHA执行四家完整真实流程，另验一个非相同SaaS产品/多维任务；记录模型执行与回退、语义投影、覆盖、主张审核、成本和未解决项。
- [x] 输出逐项交付状态与待人审的具体清单。Temporal/HTTP Qdrant/实机Postgres RLS仅在服务可用时验收，否则保留明确边界，不把本地模式当生产集群验收。正式报告仍不通过完整交付；当前12/24格、条件归属及硬件缺证冗长问题已列明。

### 5c 第二轮真实验收修补（继续第 2、3 项已批准目标）

源码 `59a9e51f…` 后端 3967 项通过（1 跳过）、前端 279 项与构建通过，但两组真实报告仍未通过交付验收。保留 `/tmp/plan_a_acceptance_v2` 原始结果后继续：

1. **补证作为待验证更新**：collector redo 准备阶段保留有效来源与分析。新抓取通过准入及 canonical 身份、版本校验后再替换；修复同 URL/hash 来源换 ID 时，去重保留旧 retired 对象的问题。明确人工撤回或真正无效的来源仍不可复用。
2. **无新证据停止重做**：比较正式来源、事实、条件、作用域和 canonical 版本；完全无新证据且原 producer 凭据仍有效时，保留原 snapshot、分析和已审核正文，记录 `no_new_evidence`，保留原 QA 阻断，交由 QA 收尾。真变化仍严格失效并按范围执行。用保存案例的 204→159 facts（新增 0、丢 45）补红测试，不能按 raw source 数判断进展。
3. **机会假设段结构回退**：标准深度写作在 `product_opportunities` 结构重试失败时，提前调用已有确定性 backfill，再执行原段落、引用和文本质量检查。用硬件原 span157/159 的输出回归。
4. 两级审查与同源码全量验证后，再分别运行真实任务；应用任务保留在工作台并核对本机 RAG 入库和查询。前两轮失败产物保持原样，每任务预算保持 200000 token / 60 calls。

## 执行约束

### 第三轮实读补修（原第 3 项）

`3557c1e2…` 已完成同源码全量和两组真实任务，但 Coda 的原文 `not manage access` 被解析成 `allowed`，主张却正确写成禁止，模型审核仍放行。继续最小修复：

1. 在现有操作分句中识别明确的 `not + access-control action`，保留 `not only` 等非否定对照，不推断缺失角色、套餐或范围。
2. 审核只对已绑定的具体操作检查正文与 `effect` 的明确极性矛盾；混合动作、另一主体、角色标签和前提条件不能误归属。原 Coda 事实和主张作为永久反例，模型 `supported` 不能覆盖确定性矛盾。
3. 仅修改 `operations.py`、`report_claims.py` 及必要测试，红绿后进行增量规格与质量审查，最后统一验证。上一版真实结果保持原样；硬件正文冗长和缺证段的泛化叙述单列质量缺口，不借此扩大改造。

当前已有大量历史改动，不reset/stash/clean；本轮不为技能默认提交而把旧改动混入commit。完成后形成可审阅交付，不自动推送/发布。一次只派一个实现者，审查者只读；阶段按顺序推进，真实模型完整流程在最终代码固定后运行，避免每个小补丁重跑昂贵流程。
