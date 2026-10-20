# Agent 实际执行与证据约束

本文描述真实执行入口，供开发、测试与排查使用。总图以 [`graph.py`](../backend/packages/orchestrator/graph.py) 为准；demo 图生成合成数据，不能作为 real 图事实准确率的验收依据。

当前验证见[完整引用支持与回答投影](optimization/2026-10-20-bound-answer-projection.md)：最终6452通过／1跳过；四组各首次38调用／129433 token。正文及保存均5正确／0错误／3遗漏，全部发表主张5/7完整绑定。BW上限否定和固定离职澄清已正常生成；BW额外共享动作越过窄引用、1Password“可以”到“必须”的模态强化、CF范围题漏答与Dropbox正文仍待修。内容合格2/4，内容与绑定同时0/4，系统0/4、6阻断。三家Analyst／Comparator／Reflector／Writer真实调用且核心模块无回退；Dropbox无接受来源未调用核心阶段。Writer实际输入已核实派送，但两套遥测状态仍不一致，BW真实核心资料仍有遗漏；不能仅据unverified遥测断言未发送。730冻结文件、5 helper及1332旧文件保持；不是Planner／全Graph／生产稠密RAG验收，未训练。

上一轮验证见[逐题证据包与原子回答](optimization/2026-10-20-agent-question-packets.md)：后端6308通过／1跳过，四组各首次30调用／123676token。正文及保存记录均3正确／5遗漏；发表观察5/6完整绑定，内容与绑定同时0/4、系统0/4交付。三组核心Agent真实调用，Dropbox采集阻断。各入口已统一选择身份；真实Writer两套派送遥测状态仍不一致，实际输入可独立核实。BW澄清、1Password复合句及CF范围误判仍待修，非feature逐题、Planner／全Graph／生产稠密RAG未验收，未训练。

上一轮真实验证见[逐题证据交付修复](optimization/2026-10-20-question-delivery-repair.md)：后端6151通过／1跳过，四组各首次30调用／116410token。正文5正确／3遗漏，记录4正确／1错误／3遗漏；Cloudflare两题及全部发表绑定合格，系统仍0/4交付。三组核心阶段真实调用，Dropbox无正文未调用生成模型。实际Reflector视图与Writer仍未逐题对齐；两条额外主张只有半句绑定。不是Planner/全Graph/生产稠密RAG验收，未训练。

上一轮真实验证见[Search／Fetch与证据消费](optimization/2026-10-19-deepseek-web-delivery.md)：后端5982通过／1跳过，四组各一次22调用／75844token。正文2正确／1错误／5遗漏，记录2正确／6遗漏；Cloudflare限定两题内容合格，系统仍0/4交付。Bitwarden、Cloudflare各核心下游实际执行且三模块状态为llm，1Password／Dropbox在采集处阻断。9份捕获完整可核验。默认关闭的新路线只在隔离CLI启用，Planner发现、全Graph及生产稠密RAG未在本轮验收；未训练。

上一轮真实验证见[Collector逐题交付](optimization/2026-10-19-collector-question-delivery.md)：后端5811通过/1跳过；四组30次真实调用，正文3正确/5遗漏、记录2正确/6遗漏，0/4完整报告可交付。三组核心下游Agent实际执行，Dropbox采集阻断未调用下游。合同已接线不代表全召回或语义合格；抓取、选窗、Writer原始选证及最终回答状态仍有明确缺口。

此前真实验证见[完整证据与答案发表恢复](optimization/2026-10-18-evidence-recovery-delivery.md)：5664项后端通过，四组40次真实调用；正文3正确／1错误／4遗漏，记录2正确／6遗漏，仍0/4报告达标。下面是有限规则及实际入口；中文数量结论误拒、下载规则投影遗漏、计费行／FAQ漏提取和错误缺证陈述仍未解决。实现检查通过不等于语义验收。

## 1. 执行顺序

```text
planner → planner_hitl
→ collector_dispatch → collector（产品 × 维度并行）→ collect_join
→ survey_interview → collect_qa → evidence_hitl
→ analyst_dispatch → analyst（产品 × 维度并行）→ analyst_join → analyst_qa
→ comparator → reflector → writer → qa → qa_hitl
→ 完成、人工决策或定向重做
```

采集 QA、分析 QA 可在预算与次数限制内重试；不满足继续条件时结束。`evidence_hitl` 接受后才创建分析所需的已准入快照。人工模式在计划、证据及最终 QA 节点等待决策，全 AI 模式仍执行对应流程检查。

## 2. 各 Agent 执行功能

### Planner：明确问题与计划

- **入口**：[`planner/logic.py`](../backend/packages/agents/planner/logic.py) 的 `_real_planner_step`。
- **输入**：目标产品、官网、研究主题、竞品、维度、市场、研究深度与决策简报。
- **执行**：研究目标产品；未指定竞品时通过搜索发现直接竞品和替代方案；验证官网线索，限制研究范围，分解后续任务。
- **输出**：`AnalysisPlan`、竞品发现记录、目标产品资料与 `analysis_plan_ready` 消息。
- **边界**：用户指定的人数、套餐或访问方式是研究条件；不能作为来源已经证实的属性。没有可用搜索且未指定竞品时可能无法继续。

### Collector：检索、采集与补证

- **入口**：[`collectors/logic.py`](../backend/packages/agents/collectors/logic.py)；知识库取证见 [`kb_bridge.py`](../backend/packages/agents/collectors/kb_bridge.py) 的 `_collect_competitor_from_kb`。
- **输入**：当前产品、维度、目标操作、研究条件、已采资料与真实缺口。
- **执行**：先通过 `rag_retrieve_tool` 检索可复用来源，再按预算进行搜索和网页抓取；清洗正文，做确定性与有界模型语义提取，按产品、维度、操作和条件组织事实；缺口驱动定向补证。
- **输出**：`RawSource`、原文和元数据、分块索引状态、结构化事实、覆盖与缺口、采集跟踪记录。规则提取使用 `source_operation_rules`，模型语义提取使用 `bounded_semantic_capabilities`，同页两路结果分别准入，避免 ID 去重吞掉补充事实。两路均重放原文、位置和值的绑定。
- **边界**：命中不代表准入。资料须通过来源角色、工作区/项目、版本/哈希、时效与正文校验；搜索摘要、旧报告和失败页面不能冒充当前一手证据。不同产品、型号、席位和计费周期不能拼成一个事实。

新准入的功能观察通过 [`source_conditions.py`](../backend/packages/research/evidence/source_conditions.py) 保留同一产品、页面、抓取及原始条件分支中的显式套餐依赖。完整条件原文、条目身份与公开对象范围进入 `qualifiers.source_condition_links`；有限谓词匹配只能关联明确重复的同一能力，不能跨角色、套餐分支、对象或来源继承条件。缓存页面重新抽取时适用，直接读回旧 `normalized_fields` 不自动回填。

已识别的身份认证、保留副本及访问路径例外由 [`source_exceptions.py`](../backend/packages/research/evidence/source_exceptions.py) 从已准入的同一抓取生成局部收据，保留原条目及事件身份。普通原句上限800字符；完整原始条件组／except列表允许最多1600字符，超过时保留缺口，不能裁掉分支。它不授予新来源资格，旧快照不会自动补写收据。

完整规则收据现在按同源身份和全部分支去重，后续 `To unshare...` 操作引导不会吞掉前面的 except 列表。兼容当前官方页面之间的一般规则与具体例外可生成 `source_exception_bindings` 候选；只有完整双方 fact/source 已发送且条件均重放时，才可有限豁免多事实限制。认证规则采用完整有限语法，未知余文拒绝；收据文字不能代替完整 origin。

当前 provider 正文采用 `provider_markdown_v1` 明确标识 Markdown 或转义 Markdown，标题与条件保持原始坐标/哈希；不伪造 DOM 或源站状态。条件窗口使用已验证父级和局部完整规则，旧 HTML 结构只作历史诊断，缺失 FAQ 继续保留缺口。

#### 逐题交付合同

[`question_delivery.py`](../backend/packages/research/question_delivery.py) 在真实 Collector 存储出口生成 `question_delivery_v1`，区分抓取、提案、原文验证、准入、来源转换和快照封存。每个问题保留原问、实际提取批次及事实关联；失败、超容量、未转换或未存储均保留原因。请求条件不成为事实，模型自报完成不能关闭机械缺口。

抓取层从同一正文根提取标题和内容，恢复真实折叠问答。HTML 标题保留真实 DOM 身份、出现顺序和最终正文偏移，并绑定正文哈希；不能用重复标题的首个文本匹配猜位置。无法绑定的正文保留结构缺口，无标题 HTML 中的代码注释不作为 Markdown 标题。[`structured_evidence.py`](../backend/packages/research/extraction/structured_evidence.py) 从当前问题窗口中的完整计费行和实际恢复问答补提案，仍经过原验证器与准入，不新增模型调用、不计算采购总价。

配置 `WEB_SEARCH_PROVIDER=deepseek` 与 `DEEPSEEK_WEB_API_ENABLED=true` 后，真实搜索入口使用独立 Search 接口，仍共享现有锁、缓存及搜索次数预算；默认关闭。Search 仅提供待核验候选。低质正文或结构缺口在既有 advanced 额度内最多尝试一次独立 Fetch；失败保留本地结果和原因，旧模式仍用浏览器升级。Fetch 记录实际请求、API 状态、原文哈希和观察时间，原站状态及最终重定向 URL 保持未知；通过专用来源凭据校验后仍须原文准入。工具请求及成功非空的计费估计单列，不冒充生成 token 或实际账单。新路暂绕过 Redis 抓取缓存，避免把旧调用计入当前额度；同页 RAG 复用约束不变。

封存时用规范正文、实际当前来源及快照重放合同。canonical 的历史 `normalized_fields` 注解不是当前事实的权威，不能因旧注解缺少新事实而误判存储丢失。后续 Agent 在真实消费校验后记录 `question_delivery_view`；它只证明本地选择。Writer 的 `question_delivery_writer_dispatch` 另按实际请求、模型 span、完整原句、值及条件核对准备、发送与省略，其他 Agent 的发送状态保持未核实。一般自然语言的语义完整性和报告质量仍须独立验收。

同页知识库占位来源仅在真实检索、当前准入和规范正文校验均通过后，才用当前完整来源替换原名额；不增加来源预算，不合并旧事实或旧日期。join双顺序与RunJournal恢复重验原有TTL、未来时间、版本、哈希和范围。审计凭据采用必要引用及哈希，普通标题脱敏不应破坏该替换关系。其本轮验收为离线真实SQLite/RunJournal测试，新项目四组未触发该分支。

#### 问题缺口驱动补证

显式功能问题通过 [`question_scope.py`](../backend/packages/research/question_scope.py) 按产品分配到 `ResearchBrief.questions`，保留原问和稳定 ID。请求中的角色、套餐、预算与输出格式只用于选择资料，不写入产品事实。

[`pipeline.py`](../backend/packages/research/pipeline.py) 在分析快照冻结前执行以下步骤：

1. 按问题选择页面与完整连续正文窗口，保留原文位置和上下文；缓存同时绑定正文与问题 focus。
2. [`question_evidence.py`](../backend/packages/research/question_evidence.py) 只把当前产品、维度中已准入的完整原文观察交给 Collector 的有界评估。评估返回 `candidate / missing / unverified` 和合法 evidence IDs，`candidate` 不代表答案已核实。
3. 对缺口先重抽已抓正文，再使用原 brief 剩余的候选、搜索和抓取额度。显式问题分支优先走这条补证链，未带问题的分支保留原有通用补证。
4. 新观察重新通过来源与原文准入，再进入 `RawSource`、知识库、分析快照和各下游 Agent。Writer/QA 继续独立检查实际答案、前提和引用；不会用评估理由代替答案。

每分支最多一轮问题补证、两次问题证据评估。评估输出最多 700 token，输入最多 12000 bytes，按完整记录选择，不能截掉条件；容量省略记为未核实并保留计数。语义提取沿用分支共享调用上限，问题分支通常最多三次，旧操作分支较大上限仍生效；已耗尽时不会为每页重试。相同 focus/正文/窗口不重复调用。无进展、预算不足、容量不足、权威未验证和未核实分别记录在 `question_stop_reason`；问题缺口留在结果、coverage metadata 和 trace。证据依赖拒绝继续抛出，不能降为可选模型失败。

候选原文可以支持“不能”，不要求产品满足请求才算找到证据。人数上限和用户请求人数分别保留；操作含糊时，支持不同分支及澄清的原文也可进入候选。明确计费问题可选入完整最低费用、用量组成或销售报价规则，作为原文观察重新准入；不因此获得合格采购现价，也不能据请求量计算完整账单。角色表格仅缺装饰管道且可唯一恢复完整原行时才恢复，改角色、漏实质单元格或多义匹配仍拒绝。

计费问题使用 [`billing_rules.py`](../backend/packages/research/extraction/billing_rules.py) 的共享规则信号，通过语义选择、质量检查及原生来源准入。完整表格必须带有可重放的表头、列单位和数字／星号多行脚注；缺项、错误列数或无法解析的脚注标记保持拒绝。条件按最近的可验证服务小节绑定，无章节时只使用连续局部范围；完整正文 hash 和验证过的 headings 都进入 focus 签名。完整规则仍是 `feature/evidence_terms` 原文观察，不生成采购现价或账户账单字段；示例与实际请求量分别保留。

计费页先用有序标题位置、层级和明确完整服务名称选连续窗口，再考虑短页／多问题全文回退；缺失 peer／引言边界保持拒绝，不能跨未知标题。无计费信号的角色页不受账单题服务约束。其余多问题短正文保留全文，避免遮住另一问题。完整服务标题要求仍可能令只写部分名称的自然语言问题返回空窗。这轮接线与验证见[交付记录](optimization/2026-10-18-question-gap-delivery.md)和[问题补证计划](optimization/2026-10-18-question-gap-plan.md)。固定官方 URL 的阶段诊断仍不代表 Planner 自动发现、完整 Graph 或生产稠密 RAG 已验收。

### Survey：用户研究检查

- **入口**：[`survey/logic.py`](../backend/packages/agents/survey/logic.py) 的用户研究 enrichment。
- **输入**：用户研究相关维度及当前产品的已有资料。
- **执行**：检查是否有真实用户研究信号。real 模式不自动生成模拟问卷或访谈来填补事实；没有相关维度时跳过。
- **输出**：检查/跳过事件及仍需外部研究的范围。demo 中的模拟资料带合成标记。
- **边界**：跳过属于明确执行结果，不能宣称已经完成真实用户调研。

### Analyst：按产品与维度分析

Analyst、Comparator、Reflector、Writer 现共用 [`question_packets.py`](../backend/packages/orchestrator/question_packets.py) 与 `_begin_question_evidence_use` 逐题选择入口。包绑定当前产品、维度、原问题、快照及检索配置；分别记录选择、视图、实际模型派送，不能仅以 ID 存在证明原文送达。每阶段沿用自身预算，核心／例外遗漏、无合格候选、词法零召回和派送未核实分别保留。无显式问题使用原路径，Collector 不读取未来快照。

- **入口**：[`analysts/logic.py`](../backend/packages/agents/analysts/logic.py) 的产品×维度分支。
- **输入**：当前已准入分析快照中，符合产品与维度范围的 `EvidenceView`。
- **执行**：抽取与比较结构化事实，保留原始金额、数量、单位、角色、套餐、操作对象及访问前提；根据预算选择有界分析路径。记录使用了哪些来源与事实。
- **输出**：结构化产品知识、分析主张、引用及证据消费/产物依赖。一次性模型响应发生明确的 JSON 格式错误时，使用同一已准入视图的确定性回退并记录 `module_status=fallback`、`llm_json_format_error`；原调用仍记为失败。认证、配置、混合供应商非格式错误和证据校验错误继续抛出，不增加重试或预算。
- **边界**：无合格证据或上下文容量不足时标记 `skipped` 或回退原因；不能把上下文没选到写成原页面没有。回退产物也必须通过依赖验证。

### Comparator：同口径能力与价格比较

- **入口**：[`comparator/logic.py`](../backend/packages/agents/comparator/logic.py)，上下文组装见 [`context.py`](../backend/packages/agents/comparator/context.py)。
- **输入**：有效 Analyst 产物与当前快照中的共同能力、报价及条件证据。
- **执行**：按相同操作、对象和前提比较；构造矩阵、差异与缺口，绑定具体来源和结构化操作。仅有评论证据不能冒充完整协作能力。
- **输出**：比较矩阵、操作覆盖、价格比较及有依据的比较结论。
- **边界**：不足以判定时保留未知或保守并列；使用确定性回退时记录 `module_status=fallback`，不能宣称模型评估已完成。

### Reflector：检查矛盾与分析缺口

真实入口现在传入 `DecisionBrief` 与内部交付范围，服务端仅排除闭合语法中明确不适用的比较要求。完整分析、相对优劣、不同目标产品、多产品、混合题内缺证和未知问题继续阻断。逐题实际输入中已知核心或例外省略会生成明确约束；局部未见不能代表全库缺证。机械对齐不证明模型一定正确理解，具体语义效果见页首最新复验。

- **入口**：[`reflector/logic.py`](../backend/packages/agents/reflector/logic.py)。
- **输入**：共享证据视图、有效分析与比较结果。
- **执行**：检查矛盾、来源薄弱、范围遗漏及待核验建议，为写作提供边界。
- **输出**：反思结果及其上游、来源消费依赖。
- **边界**：反思不是新增一手证据，不能用推断填补缺失的能力或报价；回退状态单独记录。

### Writer：把有效分析写入报告

v3 逐条隔离支持审核：仅选定 operation quote／source span 及完整来源条件支持该主张，父级宽原文和其他主张不能支持额外谓词。明确独立动作与未重建必要条件在实时及最终 QA 共用守卫，保留角色权限前提、权限选项、日期与例外；有限识别不构成通用 NLI。

[`request_clarification.py`](../backend/packages/agents/writer/request_clarification.py) 从当前生命周期结果请求生成有限的纯澄清，使用现有 v3 partial／clarification／depends、空引用及固定正文／理由。步骤、释义、已识别的独立并列子问不获得整题资格；已给输入不重复问。完整来源规则继续独立答案复核，失败／无关规则可回到安全询问；真实核心资料和预算缺口继续阻断。Writer 已运行时，零 supported 的澄清分流不调用答案模型；采集失败仍可能阻止 Writer 执行。

逐题选择在8条/14000 bytes中先保核心事实和必要例外；阶段视图与最终compact用同一函数核验完整quote/value/qualifiers，只有元数据不算送达。模型从实际发送候选选择 `source_span_ids`，服务器生成可重放的 `source_span_bindings`；父事实只施加限制。合格澄清可局部交付，缺核心事实/例外仍硬阻断。显式功能问题现一次返回 `question_plans`，模型明确列出事实原子，服务器逐条核对整句与引用；不按标点猜拆，操作陈述仍需真实操作绑定。`claim_review_version=3` 的实时与持久化回放共用准入门，不能因模型自报 supported 而跳过。

- **入口**：[`writer/runner.py`](../backend/packages/agents/writer/runner.py)；分维度写作见 [`dimension_writer.py`](../backend/packages/agents/writer/dimension_writer.py)。
- **输入**：有效 Analyst、Comparator、Reflector 产物及准入证据包。
- **执行**：按维度分段写作；价格单独成段；将事实、比较、推断和待验证机会分别表达；逐条核对主张与引用，必要时做有限修复。证据不足时生成简短局部报告，保留阻断与补证清单。
- **输出**：报告、分段结果、主张审核记录、引用、版本与依赖。功能问题在三种深度都进入分维度入口：保留产品和子问作用域，联合问逐产品审核，代词继承最近具名范围，末尾请求限制随原问保留。
- **问题选证**：[`question_retrieval.py`](../backend/packages/agents/writer/question_retrieval.py) 在首轮草稿投影前及分段入口，对当前准入快照做本机 embedding 与词法 RRF；最多 128 个候选，普通候选每问三条、总计八条，可显式传入本机精排。删除、离职、归属与保留问题增加 Writer 本地跨语种召回，相关核心原句和例外优先于套餐背景；独立核心分支共同受总八条／14000 bytes 约束，不能再被普通每问三条截掉。真正核心缺口进入既有 prompt 与 audit gaps，最终 QA 保持 incomplete；完整原文、值及条件均相同的冗余 ID 未发送不制造缺口，各来源身份仍独立。使用已冻结的本机 E5 时，配置 `KB_EMBEDDING_PROVIDER=local-e5`；没有本机 provider 时明确记为 `degraded_lexical`，配置了严格本机模式而模型加载/推理失败则抛出。有限意图规则与排序不证明事实正确，不保证全召回。模型计算离开事件循环，来源资格、当前快照与作用域在计算前后校验；选中顺序、版本和降级原因进入 trace。
- **覆盖保留**：最终选择从同一候选池补入缺失操作，保留已选操作的完整角色、套餐、对象、效果及条件分支；显式登录、邀请等必要前提只依据本条原文保护，排名上下文不能制造前提。同一原文中的其他操作不会关闭保护。容量不足时保留前提并记录 `missing_operations`；`candidate_missing_operations` 只表示本候选池缺少可识别结构，`ranking_only` 始终为 true，不是答案准确率。
- **例外绑定**：问题选证在总八条容量内补入当前可验证的认证、保留副本及独立链接例外，不能靠重复普通观察挤掉依赖；缺失时记录具体依赖缺口。Writer 输入显式携带完整例外及实际待澄清字段；通过同源明确名称识别的已知输入保留，未知命名仍可能保守遗漏。主张和最终答案分别核对角色、移除／保留／同步对象、否定以及恢复分配主密码和移除前使用该主密码登录等前提。保留数据、访问账户、停止同步、保留本地副本和有效链接分别处理。收据需重新验证捕获、源条目、上下文和事件，外来或伪造收据不能制造约束；已准入依赖被视图容量遗漏时保持未核实。有限明确规则外的表达保守处理，不承诺一般语义蕴含。

中文“没有／只能”等明确答复进入最终断言与主语核对，示例、引述、疑问和不完整条件仍不能代替正式结论。保存记录必须通过实际已发表主张、逐字片段、角色对象、数量、否定及必要条件复核；解析拒绝保留具体原因，不能以中间模型标签覆盖。

缺报价答复分别保留显式购买范围、期限、币种、税费与实际付费席位。员工人数不换算席位，一年购买期限不推断年付，已给条件不重复询问。服务器审计当前完整准入快照，防止把 Writer 视图省略误称为全库缺价；一般不完整请求保留 partial，具备合格计费规则的明确缺项答复可标记 insufficient，QA 仍检查其状态与快照绑定。不计算未经核验的采购总价，也不声称官方网站永久无价。
- **消费与回答**：视图按实际排名装入完整观察，消费凭据保留有序 `requested_fact_ids` 供 QA 重放。分段来源从 live snapshot 取得，避免旧词法投影排掉新来源。逐问记录实际 `answer`、`resolution`、`conclusion`、已支持 `claim_ids` 和从已发表主张逐字复制的 `evidence_spans`；审核 `reason` 不充当答案。格式、对象或可识别主体不符时降为未核实。超容量不截断问题、原文或条件。
- **回答选择合同 v2／v3**：显式功能问题新写作使用 `answer_binding_version=3`，无题及历史 v2 保持原合同。模型选择已审核主张 ID，服务器复制完整 `claim.text` 与完整 span；未知／重复 ID、超过原有 600／1200 字限制均保留未核实，不裁前提。v3 澄清另存有限 `missing_fields`，服务器按操作、归属、保留副本、访问路径生成询问；事实 span 不包含问句，`reason` 仅说明实际状态及缺项。最终 QA 重建全文、顺序与询问，篡改及未知版本拒绝。它保证投影与绑定一致，不证明自然语言语义已合格。
- **问题上下文保留**：最多八条已选事实的显式功能问题使用最多 32 KiB 的本地证据视图，实际 compact 输入仍限制为 14000 bytes。普通问题保留已检索的完整原文和绑定候选，不从原文反推请求操作，也不按操作排掉同一问中的归属、数量等子问；定向重做仍限于指定操作。容量不足按整条省略并记录缺口，历史消费凭据继续按原容量重放。
- **回答二次核对**：`dimension_answer_coverage` 初审只看实际已发表主张，不能用未发表事实补回答；`dimension_answer_review` 再看完整原文及服务器拼接的实际 answer、evidence_spans、binding_version，提案不带审核理由。复核检查否定方向、所有子问、操作和归属歧义、SSO／离线／副本等例外；只能选择已发表 ID，不能用未发表来源或理由补答案。无预算、容量超限或格式无效时不保留首轮 answered。完整上限句只增加有限断言识别，真伪与适用范围仍须语义核对。报告显示最终结论或澄清提示；超过八题全部保留未核实并提示拆分，不静默截断。
- **混合事实**：同一观察里有其他操作候选时，非六类主张仅在它是单一已发送 `evidence_terms` 的完整原句或完整原文条目时允许无操作 ID；六类操作仍要求绑定。原句保留原语言，问题答案使用所选输出语言；原文匹配仍须通过来源、日期与模型主张审核。
- **预算与角色范围**：完整原始事实先装入14000 bytes，`non_operation_originals` 与完整例外 pair 提示只用剩余容量，不挤掉后续事实。`RESOURCE_SCOPE_RULES` 共享给 Writer、主张审核、覆盖与答案复审，区分角色本身给定资源权限和个人全部权限；后者须保留题设无其它授权，不因官方未写用户域名过拒，不外推到账户级角色。
- **缺报价与账单**：[`price_answers.py`](../backend/packages/agents/writer/price_answers.py) 先识别明确金额请求，再检查市场、套餐、币种、周期及税费；人民币不能代替市场，一年合同不等于年付。缺少输入时列出具体待确认项；口径齐全后检查完整当前快照，不受 Writer 排名截取影响。完整账单还需实际用量明细，只有合格当前来源中的肯定收费依赖才可提示 CPU 总量；否定收费、其他套餐及单次执行上限不充当该条件或总用量。未知范围不借来源单价填补，不推算总账单；账单查看权限、导出格式及留存期限不会被自动询价答复接管。有限高置信意图外的问法继续走原问答链。新生成的具体缺报价记录使用 `partial + insufficient + unknown`，绑定当前快照并在最终 QA 重算；历史记录仍可读取，重新审核时旧 `answered + insufficient` 不再满足当前不足状态要求。这表示已明确答复不足，报价证据仍未齐全，不虚构金额或引用。无关活动日期不会覆盖报价核验日期。
- **计费适用性重放**：同一命名语法核对每处 scope span 与题设，未知或混入其它套餐／模式拒绝。表格须有完整肯定 plan+mode 适用原句、匹配当前行及CPU表头→单元格正时间费率；否定／仅共现／未知限制不能证明适用。全部背景和脚注继续送QA；prose缺本句范围仅继承无歧义父级。`Free`名称误触否定仍未修，有限语法不是通用NLI。
- **边界**：不得自由查询新资料替换原引用。历史错误绑定继续拒绝；局部报告不等于完整覆盖，生成成功不等于事实准确率已通过独立人审。

此前数量越界结论的格式误拒已修，本轮 Bitwarden 正文出现正式“否”及请求澄清；日期、单位和作用域仍须独立审核。已采原文到完整主张的语义投影、其他文字规则的结论形成，以及采集／省略／准入状态的准确区分仍须按页首真实结果验收，不能由上述合同说明推定合格。

回答校验另检查明确套餐排他性及强制升级建议：被引用主张必须有相同套餐集合的明确限制，不能把某套餐被包含写成只有该套餐可用。未知范围保持未核实；有限词法规则不等于普遍语义证明。中文明确报价年月日按请求解析，无效或矛盾日期不自动生成已回答记录。

完整中文“只有……才能访问……”可作为闭合问句的必要条件断言；新增识别路径对完整主张块检查引号、示例、建议及未完成句，不从审核理由补答案。主体、对象、套餐、完整主张和 v2 引用重放仍须分别通过。

### QA：审核与重做决策

有限原文金额组件只从已发表、已允许的精确span重放，分别核对费率与账户最低费的套餐、币种、单位、周期及收费对象，多个金额保持各自诊断。未知推导/额外收费范围仍阻断。本轮真实CF没有发表金额，不能据零金额问题宣称真实费率验收通过；保存reason与不足答复状态也须独立核对。

- **入口**：[`qa/logic.py`](../backend/packages/agents/qa/logic.py)，引用对齐见 [`evidence_alignment.py`](../backend/packages/agents/qa/evidence_alignment.py)。
- **输入**：阶段资料、当前证据快照、结构化分析、矩阵、报告与已有审核记录。
- **执行**：采集 QA 检查来源、覆盖和时效；分析 QA 检查结构化产物；最终 QA 检查虚构引用、矩阵/正文一致性、主张与条件、来源质量以及发布阻断。
- **输出**：阻断/警告、审核结论、人工审核请求与 `redo_scope`。操作主张检查逐项记录角色、对象、操作、效果及前提对应的原文和主张片段；问题覆盖只可引用已支持主张。最终 QA 重放回答/片段守卫，检查实际回答仍在正文；缺价答复须与当前快照重算的服务器记录完全相同。缺项或问题范围变化保留 Writer 阻断，重放使用原消费记录的有序 `requested_fact_ids`，不重新排名或借用其他资料。
- **日期与请求边界**：创建日期例外按同主体、谓词、日期对象及极性核对；已知 Admin/Owner 中英文别名可归一，未知跨语种角色保持未核实。预算等请求条件只在已验证生产者、消费凭据和精确问题显示行相符时从产品金额审查中排除；实际答复与普通正文金额继续审核。缺证稿可通过结构预检，但发布合同、证据阻断及 `force_pass` 保护保持原有要求。
- **边界**：确定性检查只能验证其覆盖的规则；规则通过不等于自然语言语义绝对正确。工作流终态、报告生成、业务可交付分别判断。

新来源条件收据在 Writer 主张审核和最终 QA 同步重放：短句命中原文不能豁免完整套餐与公开对象前提；逐个实质子句检查，逗号或后续句不能隐藏无条件结论。未知套餐不能改成免费或付费套餐。规则仅覆盖已识别的来源依赖，未识别表达继续交给原语义审核；历史记录不因此自动变为已审核。

## 3. RAG 怎样接入所有 Agent

常规检索入口是 Collector 调用 [`rag_retrieve_tool`](../backend/packages/tools/rag_retrieve.py)，共享检索在 [`RetrievalService`](../backend/packages/knowledge/retrieval.py) 中执行。检索响应附带查询规划、候选、模型与范围诊断；Collector 将合格原文转换为来源，再走证据准入。

新产品现可通过[部署者审核的精确官方文档登记](optimization/2026-10-16-official-source-registry.md)进入生产身份解析、实际抓取核验和有界语义提取。授权不扩散为主页或整域名，缓存重绑定及完整正文入库前会重新核对回执。Writer 正式执行入口为 `WriterEvidenceAlignmentMixin._real_writer_step`，包含证据投影和产物提交；直接调用 `_write_report_draft` 不能代替这一步。真实模型的完整前提归属与正文引用质量仍按[本轮交付记录](optimization/2026-10-16-official-writer-delivery.md)独立判断；各 Agent 的职责说明不等于新产品已端到端通过。此前固定短节选诊断仍保留[历史结果](optimization/2026-10-16-condition-model-delivery.md)。

后续 Agent 通过 [`evidence_context.py`](../backend/packages/orchestrator/evidence_context.py) 与 [`views.py`](../backend/packages/research/evidence/views.py) 选取当前快照的视图。视图按产品、维度、来源和上下文容量裁剪，记录所用事实、来源及省略原因。这样，检索改善会进入实际分析和报告消费链。

- **规划层**：查询保留原始输入，区分事实检索与输出语言/引用要求；`raw` 用于保留比较基线。
- **召回层**：SQLite FTS5/BM25 稀疏检索，Qdrant 稠密检索，多查询与多路结果采用 RRF，按配置选择本机精排。
- **准入层**：校验 canonical 正文、有效状态、模型索引版本、来源哈希、工作区与项目等条件。检索时间不会覆盖原资料核验时间。
- **消费层**：Analyst、Comparator、Reflector、Writer、QA 消费同一准入链。每份派生产物记录来源消费和上游哈希，更正来源后不能沿用过期的分析结论。
- **补证层**：缺证返回 Collector 收集并重新准入；后续阶段重新验证受影响产物。Writer/QA 不直接绕过快照添加证据。

这些规则在 real Agent 执行入口生效；独立模型检索评测、Agent 集成测试和真实联网报告验收分别提供不同层面的证据，不能互相替代。

离线贯通测试执行真实 RAG 工具、提取准入、canonical 入库、快照及五阶段证据消费。旧用例曾替换报告 hardening；新增 [`test_offline_agent_retrieval_alignment.py`](../backend/tests/integration/test_offline_agent_retrieval_alignment.py) 保留真实报告 hardening、发布校验与最终 QA，并加入双产品、错项目、历史报告、过期资料、未标产品及跨产品引用反例。网页正文和 LLM 回复仍为合成固定重放；模拟审核声称“支持”也不能绕过引用绑定规则。它验证执行与保护规则，不能代替真实模型报告语义准确率或联网时效验收。

当前规划策略为 `intent-v7`，词法策略为 `lexical-v4`，检索管线为 `dual-context-v1`。自动规划最多生成 5 条事实查询，结合产品、维度和已识别主题；未知中文条件保留在 `unknown_terms`、`preserved_clauses` 与原始问题中供后续核对。生产入口默认同时执行原句一路，结构化子查询先内部融合，再与原句一路等权 RRF；重复查询按去空白和大小写归一去重，精排/MMR 使用完整原句。两路保持相同范围与 canonical/索引校验。检索到主题资料不表示用户命题或未知条件已经得到支持，当前规则也不能完整理解任意自然语言关系。查询侧支持同一文档标题中的产品/型号与正文主题联合匹配，以及保留数值和量纲的有限单位拼写匹配；分词存储格式未变。

排名确定后，[`knowledge/evidence_context.py`](../backend/packages/knowledge/evidence_context.py) 从当前文档恢复短章节/短全文，过长时尝试同章节的前后相邻块。锚块文本、ID、排名及向量引用保留；补全单独记录当前文档 ID/version/hash、原文区间、文本哈希、覆盖块与方法。`parent_document_id` 是历史版本链，不用于上下文补全。老块缺坐标时仅接受当前正文中的唯一精确匹配；歧义、哈希不符、跨章节、部分表格、超预算或重复区间均跳过并给出原因。每条完整上下文最多 3000 字符，每次额外最多 6000 字符；缓存命中仍从 canonical 重建，诊断分开记录本次零召回与冷排名来源。

Collector 对校验通过的上下文保留完整片段，避免原先的 1000 字符摘要再次切掉开头前提。它仍是 `kb_retrieval_chunk`，必须经过抓取/复核、提取、准入及快照后才成为可引用事实。Analyst、Comparator、Reflector、Writer、QA 继续消费该共享快照；补全文本中出现条件，不代表该条件已正确绑定为某个操作的前提。新增 [`test_dual_context_agent_alignment.py`](../backend/tests/integration/test_dual_context_agent_alignment.py) 用禁网的固定回放核对该链路与真实 QA，无需更改各 Agent 的提示词或授予独立绕过准入的检索权限。

缺少产品实体、但问句完整落在有限领域主题与语法范围内时，可走 `topic_scope_lookup`。诊断明确记录 `missing_product_scope_topics_only_for_verification`，保留完整问句与条件，仅返回主题候选；不得从语料或金标推断用户指的是哪个产品。纯语气、只有条件词、未知实体及无法可靠拆分的多产品关系保持保守。独立句尾“请保留原始口径和条件”属于输出要求；“消息保留”“保留历史”等真实留存需求继续用于事实检索。此规划同时进入实际 `RetrievalService` 与 Collector，后续 Agent 继续通过准入快照核对产品和条件。

长中文调研简报没有可识别的具体主题时，可使用 `dimension_scope_lookup`。它仅在单一声明产品、单维度、明确知识范围和 `source` 来源角色、没有额外数值条件时启用，在精确元数据过滤下按产品名做 FTS 范围查找。短查询和英文关键词保持原路径。诊断为 `metadata_scoped_browse_without_fact_parse`，不代表问题已被语义解析；目标产品与当前竞品分别处理，目标名称不会污染其他竞品分支。

`raw` 对照保留原始查询、不做事实查询规划，但与 `structured` 共享当前词法策略；历史 `lexical-v1` 的 0/6 是保存的旧结果，不能说新脚本冻结了旧检索引擎。评测中的候选覆盖指各子查询、各模态经范围及 canonical 校验后的联合池：每路取 20 条时，5 个结构化子查询的 hybrid 理论上最多 200 条 chunk；双路再含一条不同原句时最多 240 条，精排仍取最多 20 条，最后输出 top-3。联合候选覆盖不等于最终 Recall@20，实际调用、候选数与补全字符单独记录。`--ablation` 比较原句、仅结构化、双路、双路加补全十二组；旧默认六组关闭双路与补全，保留可复现的比较基线。

## 4. Prompt 与运行状态

项目已有各 Agent 的系统指令、任务上下文和结构化输出 schema，并非所有阶段共用一句通用提示词。[`prompt_contract.py`](../backend/packages/agents/prompt_contract.py) 提供共同证据规则及 Prompt 身份记录：

- 外部网页、检索片段、旧报告均作为不可信资料，不能修改角色、工具权限和任务。
- 只能引用提供的来源，保留数字、单位、产品、市场、套餐、席位、账期和日期限定。
- 区分已支持事实、分析推断与证据缺口；弱摘要不能单独支撑胜负和当前价格推荐。
- 跟踪 `prompt_id`、`prompt_version`、模板哈希与本次输入哈希。已登记模板有显式版本，其余模板仍可能记录为 `unversioned`，尚未完成全模板版本治理。

核心阶段可记录 `llm`、`fallback` 或 `skipped` 及原因。预算不足、超时、格式错误、无证据和上下文省略分别检查；不能只看节点完成事件推断模型真正执行。实际调用、重试与保守计费记录见 [`execution_budget.py`](../backend/packages/llm/execution_budget.py)。系统为分析、比较、反思、写作和审核预留资源，仍需满足整次运行及工作区额度限制。

### 金额分类与后续学习数据

[`monetary.py`](../backend/packages/research/evidence/monetary.py) 在实际 Writer／最终 QA 金额审核入口逐金额区分 `credit_allowance / purchase_price / unknown`。额度例外须匹配本段引用且在当前生成视图放行的完整原文，绑定币种、金额、套餐、周期、授予动作和 credit 单位。试用期、仅限新用户等额外限制无法完整处理时保留 unknown；逗号／分号不能截掉限制。额度不进入结构化采购价，缺少市场、税费等条件的精确报价继续不足答复。

[`prepare_agent_readiness.py`](../backend/scripts/prepare_agent_readiness.py) 只读真实运行的六类已保存产物，导出脱敏 `question_episode` 及共享运行轨迹。模型动作和 token 按运行计一次；单题候选标签、任务终态与真实性奖励分开。已曝光运行进入 development；独立候选按全量产品／文档身份校验隔离，运行没有回答审计也不能漏掉来源身份。原数据哈希、源码哈希、引用选择版本和截断标记保留；不能把这些摘要当作无损训练轨迹。

项目用户已确认八题参考边界及 T1–T3 单题标签，见[确认记录](optimization/2026-10-18-conditional-evidence-human-review.md)。T1 只确认单题条件结论，不能升级为整份报告或旧引用绑定成功；原候选与旧导出保持历史状态。`reward.correctness=null`、`training_ready=false`。新题 runtime 只含问题与来源身份，不含参考答案、原文节选或标签；生成后机器核对不冒充用户对新报告的人审。暂未训练模型，也未建立自动奖励优化器；范围及结果见[关键证据与条件交付](optimization/2026-10-18-conditional-evidence-delivery.md)。

上一轮[事实保留与回答复核回归](optimization/2026-10-18-answer-preservation-delivery.md)使用同一已曝光八题：40 调用／151462 token，4 正确、2 错误、2 遗漏，0/4 完整报告达到内容标准。二次模型审核仍未纠正 SSO 例外和取消共享结论，运行时零阻断不能作正确性证明；两道计费题仍未答。模型调用和工程测试通过均不转成训练成功标签，后续需先补例外闭合与计费意图／准入。

### 部署、缓存和中断恢复

- Collector 的实际 `fetch_evidence_page` 入口可使用 Redis 公共网页缓存；后续 Agent 仍消费准入快照。缓存仅复用完整 typed 正文，拒绝价格请求、凭据/查询串 URL、失败和摘要，损坏缓存按 miss 处理。原 `captured_at`、正文哈希和来源身份检查继续有效，缓存命中不代表事实重新核验。
- 运行创建、工作流、定时扫描、监控、续跑与重做等写入口可启用共享限流。主体取自服务端鉴权结果；限流不能替代 token/费用预算。Redis 默认关闭；缓存故障降级，启用的限流故障返回 503。
- LangGraph 从同一 run/thread 的 SQLite checkpoint 续跑已完成节点之后的工作，恢复前检查执行归属、状态、模型策略及待执行工作，重复恢复请求拒绝。已完成、人工等待、未知归属及限定重做检查点不会作为普通崩溃任务自动续跑。
- `POST /api/runs/{run_id}/recover` 需要 `report:write` 权限；重启不会自动重放真实外部请求。Temporal 的中断重试使用相同图检查点；普通业务失败仍保留失败状态。
- SSE `Last-Event-ID` 从持久事件日志补读后续事件；Nginx 透传游标并关闭响应缓冲。运行状态、图检查点及产物存于持久数据卷，Redis 不保存业务唯一真值。

当前只支持单 API / 单运行 Worker。中断节点可能重做尚未提交的模型调用，未提供跨进程 lease 或外部调用 exactly-once 保证。离线假模型恢复通过不等于 Temporal/Redis 容器故障验收通过，跨机步骤见 [部署说明](docker_deployment.md)。

## 5. 人工介入和定向重做

| 范围 | 返回位置 | 适用问题 |
| --- | --- | --- |
| `writer_only` | Writer | 资料和分析有效，仅改写表达或报告结构 |
| `comparator` | Comparator → Reflector → Writer | 比较口径、矩阵或比较结论需修复 |
| `analyst` | Analyst 分支及后续阶段 | 产品事实分析有误或遗漏 |
| `collector` | Collector 分支及后续准入 | 缺少一手资料、来源过期或条件证据不足 |
| `full` | Planner | 研究问题或整体范围需要重设 |

限定重做先验证已有快照和产物依赖。补证没有带来新证据时保留有效旧报告与原阻断，记录无进展；不能用空结果覆盖成“已修复”。人工改稿生成独立版本，并保留原 AI 报告及审核历史。

## 6. 如何判断执行是否符合设计

排查时同时核对：研究计划及分支数、每阶段真实调用/回退、已准入快照、证据消费、上游依赖、产品×维度/操作覆盖、最终正文主张与引用。单看报告字数、任务状态或调用次数不足以判断完成度。

运行与检索评测命令见 [README](../README.md)。十二组比较、前提贯通回放与剩余稀疏/语义绑定问题见 [双路检索与上下文补全](optimization/2026-10-16-dual-query-context.md)。上一轮样本边界见 [离线复测](optimization/2026-10-15-offline-rag-followup.md)；历史验收、月度配额阻断及部署项见 [正式验收记录](optimization/2026-10-14-formal-acceptance.md)。

## 7. 本轮答案覆盖与条件归属验证

实现与真实模型结果见[交付记录](optimization/2026-10-16-answer-condition-delivery.md)。`answer_coverage` 是待答问题的审核结果，用户条件不能成为证据；`permission_option` 的限制只适用于其列出的操作选项，`role_scoped` 不可直接提升为另一个角色的共同前提。缺证、写作遗漏、上下文超限分别保留，不能用一次 `supported` 或引用 ID 正确冒充报告验收。

本轮固定官方 URL 的 Collector→下游模型诊断没有执行 Planner 发现、完整 Graph 调度或生产稠密 RAG；不宣称整个主流水线已通过。
