# 10 · 高分导向融合 Backlog · 课题适配增强

> 来源：`review/plan_a_high_score_comprehensive_review_20260601.md`。  
> 定位：本文件不替代 `dev_plan_final v2.0` 的主路线，而是把高分审查报告中适合吸收的内容转成可执行 backlog。  
> 原则：保留 `LangGraph + Schema + Trace + RedoScope + Temporal 外层 + Enterprise Store` 主干，只补课题硬要求、报告质量、证据可信度和业务体验。

---

## 10.1 纳入结论

这份高分导向审查可以纳入计划，但要分层吸收：

| 类别 | 是否纳入 | 处理方式 |
|---|---|---|
| 课题硬要求补强 | 纳入 | Survey/Interview Agent、source 可追溯、闭环改善证据 |
| 产品质量增强 | 纳入 | L1/L2/L3 产品化、报告模板、Evidence Center 跳转 |
| 智能能力增强 | 纳入 | 真 RAG、Online Gap Fill、MemoryAgent、Self-consistency |
| 企业架构增强 | 选择性纳入 | SourceSnapshot、ToolRegistry、ModelRouter、KG read model 延后 |
| 答辩材料 | 暂缓 | 当前先不做 PPT/录屏/演示脚本，等产品能力收口后再补 |
| 过度研究项 | 不作为近期目标 | 因果 do-calculus、TLA+、联邦学习、Neo4j/RDF 不进近期路线 |

---

## 10.2 当前路线修正

原 `dev_plan_final` 的主线仍然成立：

```text
Phase 1: 企业数据骨架
Phase 2: 业务情报能力
Phase 3: Agent 增强 + 工作台
Phase 4: Temporal 外壳 + 审批原型
Phase 5: 企业治理与规模化
```

本补充文档新增一条 **Phase 5 产品质量分支**：

```text
Phase 5A: 企业治理
  RBAC / RLS / Audit / Temporal / Source Registry / pgvector / compliance

Phase 5B: 高分质量增强
  L1L2L3 产品化 / Survey-Interview / RAG / Memory / Self-consistency / EvalOps
```

两条分支可以并行，但当前优先顺序是：

1. 先补产品质量和报告质量；
2. 再补生产级企业治理；
3. 最后补答辩材料。

---

## 10.3 P0：立即纳入的开发项

### H0 · 提交安全与敏感信息边界

目标：避免真实密钥、课题凭据、临时文件进入提交包、截图、报告或演示。

当前状态：已有 `.env.example`、PII redaction、model policy，但工作区仍有 review/backups 等临时文件。

开发项：

- 建立 `docs/submission_checklist.md`。
- 明确排除 `.env`、`runs/`、`backups/`、`.claude/`、临时 review 输出。
- 对本地课题资料只保留脱敏引用，不复述密钥。
- 扩展 provider key redaction pattern。

说明：这不是答辩材料，而是项目安全底线。

### H1 · L1/L2/L3 产品化增强

目标：把已经存在的 L1/L2/L3 后端能力变成用户入口、报告主线和质量规则。

当前状态：后端已有 layer 判断、ScenarioPack、QA rules；前端工作台可展示，但 New Run 和 writer 模板还不够显性。

开发项：

- New Run 增加 Layer 选择：`auto / L1 / L2 / L3`。
- New Run 增加 ScenarioPack 选择器。
- 选择 scenario 后自动填充推荐 competitors/dimensions。
- Run Detail 顶部展示 layer、scenario、QA rules、recommended dimensions。
- Writer 增加 layer-specific report template：
  - L1：battlecard、pricing、features、objection handling；
  - L2：workflow overlap、ecosystem、switching cost、enterprise risk；
  - L3：market landscape、benchmark、trend、category segmentation。

验收：

- L1/L2/L3 三个 preset 都能跑通。
- 报告标题、章节和 QA rules 会随 layer 改变。

### H2 · Source token 一键跳转

目标：报告正文中的 `[source:...]` 不只是文本，而是可跳转到 Evidence Center/Source detail。

当前状态：EvidenceRecord、SourceRegistry、ReportVersion 已有；前端有 Evidence Table，但报告正文 token 未产品化。

开发项：

- 增加 report source token parser。
- ReportView 将 source token 渲染为链接/按钮。
- 点击后定位到 evidence detail 或打开 source URL。
- 对失效 source 显示 broken/missing 状态。

验收：

- 报告正文任一 source token 可定位到对应 EvidenceRecord。
- 不存在的 source token 被 QA 或 UI 标记。

### H3 · SurveyAgent / InterviewAgent

目标：补齐课题中“问卷调研、用户访谈”相关采集 Agent 要求。

当前状态：已有 survey_simulator 工具桩，但不是独立 Agent 链路。

开发项：

```text
backend/packages/agents/survey/
backend/packages/agents/interview/
backend/packages/schema/survey.py
backend/packages/schema/interview.py
frontend/src/features/survey/
frontend/src/features/interview/
```

能力：

- SurveyDesignAgent：根据 EvidenceGap 生成问卷问题。
- SurveyAdminAgent：demo/fixture 模式读取或合成问卷应答。
- SurveyAnalystAgent：将问卷结果转为 KnowledgeClaim。
- InterviewAgent：将访谈纪要或模拟 transcript 转为 persona pain points、quotes、claims。
- 所有问卷/访谈数据显式标注 `survey_simulated`、`interview_record` 或 `manual_transcript`，并经过脱敏。

接入：

- 在 persona / user review / buying criteria 维度触发。
- 结果进入 EvidenceRecord、ClaimRecord、ReportVersion。

验收：

- 至少一个 run 能产出 survey/interview evidence。
- 相关 claim 有 source_ids。
- compliance report 不出现未脱敏敏感信息。

---

## 10.4 P1：显著提升真实报告质量

### H4 · 真 RAG + Online Evidence Gap Fill

目标：在当前 pgvector/embedding index 基础上补完整 RAG 链路。

当前状态：已有 deterministic embedding index、search_evidence、pgvector schema，但不是完整 retrieval pipeline。

开发项：

```text
backend/packages/rag/chunker.py
backend/packages/rag/embedder.py
backend/packages/rag/vector_store.py
backend/packages/rag/bm25.py
backend/packages/rag/reranker.py
backend/packages/rag/retriever.py
backend/packages/rag/grounded_prompt.py
```

检索流程：

```text
query rewrite
  -> vector search
  -> BM25 rerank
  -> optional cross-encoder / LLM rerank
  -> RetrievalRecord
  -> grounded analyst/writer prompt
```

Online Gap Fill：

- EvidenceGapAgent 识别缺失 `competitor x dimension`。
- 只对缺口触发 web search/fetch/chunk/upsert。
- 补采结果进入 Evidence Center，并更新 gap 状态。

验收：

- Trace 中能看到 retrieval query、chunk ids、rerank score。
- analyst claim 能引用 RetrievalRecord。
- gap fill 后缺口数量下降。

### H5 · MemoryAgent

目标：让系统能从历史 run、HITL、用户反馈和质量标注中学习偏好。

Memory 类型：

- `user_preference`
- `domain_fact`
- `source_preference`
- `failure_pattern`
- `qa_policy`

接入：

- planner 前 recall；
- collector 选择 source 时参考 source_preference；
- writer 参考 user_preference；
- qa 参考 failure_pattern；
- run 结束后 observe。

验收：

- 同 workspace 第二次 run 能召回上一轮用户反馈。
- report 或 plan 中能解释使用了哪些 memory。
- repeated feedback 数量下降。

### H6 · Self-consistency + ClaimValidator

目标：进一步抑制幻觉和不稳定结论。

开发项：

- planner discovery 多采样；
- analyst claim extraction 多采样；
- comparator matrix cell majority vote；
- high-risk claim 用 critic model 或 deterministic validator 检查；
- 统一输出 `ClaimValidationResult`。

验收：

- high-risk claim 必须有 validation status。
- minority samples 被记录到 trace。
- final QA 能基于 validation 触发 scoped redo。

### H7 · Quality Agent Matrix

目标：把 QA 从单一终检升级为多角色质量矩阵。

矩阵：

- EvidenceGapAgent：字段级缺口；
- RedTeamAgent：反命题、绝对化表述、偏见检查；
- BenchmarkAgent：报告质量评分；
- ClaimValidator：证据是否支持 claim；
- ReleaseGateAgent：是否可发布。

验收：

- 每类 finding 进入统一 issue/finding schema。
- finding 可触发 RedoScope。
- 工作台显示质量矩阵状态。

---

## 10.5 P2：体验、评测与长期产品化

### H8 · EventBus / Decision Replay 升级

目标：把现有 SSE 从节点完成流升级为决策事件流。

新增事件类型：

```text
agent.started
agent.finished
tool.called
rag.retrieved
self_consistency.sampled
memory.recalled
claim.validated
qa.blocked
redo.routed
benchmark.scored
report.ready
```

验收：

- 前端 Decision Replay 时间轴能展示 RAG、memory、claim validation、redo。
- 每个关键决策都能回放到输入、输出、证据和原因。

### H9 · Baseline / EvalOps 看板

目标：把业务价值量化展示出来，而不是只靠报告看起来不错。

指标：

- golden_set_pass_rate
- coverage_lift_rate
- citation_validity_rate
- manual_time_saved_hours
- human_correction_rate
- redo_convergence_ratio
- llm_judge_avg_score

验收：

- Enterprise Workbench 或独立 Eval 页面展示 baseline vs system。
- `eval_enterprise.py` 输出可被前端读取。
- regression gate 可阻止明显退化。

### H10 · SourceSnapshot / ArtifactStore / ToolRegistry / ModelRouter

目标：吸收企业架构方案中有长期价值但不宜过早做重的能力。

优先级：

1. SourceSnapshot：网页快照、PDF、截图、访谈 transcript 统一资产化；
2. ArtifactStore：从 local/external pointer 升级到 S3/OSS；
3. ToolRegistry：工具 schema、成本、side effect、policy；
4. ModelRouter：按质量、成本、合规、租户策略路由；
5. KG read model：只做 read model，不引入 Neo4j/RDF。

---

## 10.6 暂缓项

以下内容来自高分报告，但当前暂缓：

- PPT、演示视频、答辩脚本；
- TRAE/AI 协作材料包；
- 大规模 200 条 golden set；
- Causal Reasoner / do-calculus；
- TLA+；
- 联邦协作、差分隐私、同态加密；
- Neo4j + RDF/OWL；
- Kafka Event Sourcing。

原因：这些对当前“真实业务产品”不是最短路径，且容易分散 Phase 5 生产化和报告质量改进。

---

## 10.7 推荐执行顺序

当前项目已经完成 Phase 4，并进入 Phase 5。后续建议顺序：

```text
1. H1 L1/L2/L3 产品化
2. H2 Source token 一键跳转
3. H3 Survey/Interview Agent
4. H4 真 RAG + Online Gap Fill
5. H6 ClaimValidator + Self-consistency
6. H5 MemoryAgent
7. H8 Decision Replay
8. H9 EvalOps 看板
9. H10 SourceSnapshot / ToolRegistry / ModelRouter / KG read model
```

如果要先提升真实 run 报告质量，优先做：

```text
H1 + H2 + H4 + H6
```

如果要先补课题评分硬项，优先做：

```text
H0 + H1 + H2 + H3 + H9
```

如果要先靠近企业产品，优先做：

```text
H4 + H5 + H8 + H10
```

---

## 10.8 一句话

高分审查报告可以纳入计划，但应作为 **高分质量增强 backlog**，不是推翻现有企业架构。当前最值得先做的是：**L1/L2/L3 产品化、source 一键跳转、Survey/Interview Agent、真 RAG + Online Gap Fill、ClaimValidator/Self-consistency、MemoryAgent、Decision Replay、EvalOps 看板**。
