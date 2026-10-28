# 已审核任务结论到最终答案的统一合同计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development。一个实现者串行写源码，每项先规格审查、再质量审查；旧原件只读。

**Goal:** 让同题已审核、精确选证完整的任务推断可靠进入最终答案，修复Bitwarden数量否定和Trello跨资源非蕴含被重复门禁撤回的问题。

**Architecture:** 保留GEN5与REVIEW3，在现有最终独立ANSWER调用中增加v6任务决策审查。服务器从实际GEN任务、合并结果、独立claim审核和接受快照重建候选；模型只审候选是否回答指定任务，服务器签发可重放的小型见证。解析、正文与QA消费同一已认证见证，事实与推断的kind不互换。只支持quantity_excess和resource_non_entailment，不提供任意supported推断的通行证。

**Tech Stack:** Python、Pydantic、pytest，固定官方页与当前配置DeepSeek的生产阶段回放。

基线`006e94e6c91494d0e9fc354fed176706a5c9c904`，现有`codex/pastoral-desktop`。用户已批准“统一已审核任务结论到最终答案合同，解决推论通过后无法发表”；本计划细化该授权，不扩大到训练、Docker、UI、新抓取、默认实验开关或主分支合并。沿用现有checkout。

## 已证实的根因与方案选择

N4目录`data/artifacts/task-conclusion-contract-2026-10-27/`已锁定上一轮整个211文件目录。纯生产认证重放复现三份真实run。BW的upper_bound要求fact，虽然当前结论本身是已审核inference；仅在内存将relation改为explicit_negative，相同所选原文与结论即可通过。Trello的“不能由A确定B”恰是非蕴含的答案，却被普通不确定性筛子删掉。现有task_results只有生成状态，不能当独立审核过的决策。

比较三个方案：继续扩大有限句式会重复依赖自由改写；直接放行所有supported inference无法证明指定任务、极性和条件已回答；采用绑定真实任务与审核的决策见证，可区分事实真值、任务完成及实际权限。选择第三种。缺证、角色不符或仅有模型自报/digest时保持未知。

## Task 1：候选与类型化见证（不接实际入口）

**Files:** 新`backend/packages/agents/writer/task_decision_witnesses.py`及`backend/tests/unit/test_task_decision_witnesses.py`；必要的schema定义随Task2接线再加。

- [x] 从已认证GEN payload的generation_tasks和compact.question_answer_plans[].task_results[].claim_ids恢复任务身份及claim映射，repair合并不得改变初始task身份；只取独立审核supported、同题、同产品/维度、完整source_span可从当前真实facts重建的inference。
- [x] 为候选分配服务器ID，绑定consumption/snapshot、完整canonical question、parent/request_context、task与claim完整内容、精确source支持和独立claim REVIEW transport。模型不得自行制造任务、source_ref、witness或这些身份。生成状态和空review不授权。
- [x] quantity_excess只接受people_limit/container_limit对应的同单位、同操作、同角色/套餐/人口规则；从该inference自己的完整所选原文核字面最大值与当前题较大请求，允许单个失败必要条件否定AND整体。不能借未选属性/另一claim/不同题；未知条件、例外、并发或人口不明保留未知；人数能力句不能凭空提升为人数上限事实。
- [x] resource_non_entailment只回答跨资源赋权能否推出另一资源状态：待答片段本身必须引用两个明确资源，且精确原文有正面的逐资源规则，不能以未提及关系证明No。不能把“不由A决定B”变成“B禁止”。计费片段仅提A，不因parent包含A/B而获得此见证；缺计费证据保持缺证。
- [x] 现有最终ANSWER v6审候选的target_grounding/task_fulfilled与conclusion；关键证据只引用实际派送的完整支持。服务器根据真实审核响应和身份签发紧凑凭证，证据hash只是未变证明，不当语义真值。凭证必须能从实际transport与原件重建。
- [x] 先红后绿：真实BW collections推断、Trello跨板与独立品牌/数值正例；错误source/hash/offset/题/任务/role/单位/套餐/条件/缺原件/空或伪造review/无上限/同资源/运行时权限/计费错引反例。命令：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_task_decision_witnesses.py -q`。
- [x] 规格审查后质量审查，两个审查通过再接线。只改必要文件，不重构其他Agent。

## Task 2：ANSWER v6、认证重放、正文与QA

**Files:** `writer/question_atomic_delivery.py`、`writer/answer_coverage.py`、`writer/subquestion_premises.py`、`writer/answer_presentation.py`、`writer/dimension_writer.py`、`qa/question_reconciliation.py`、`research/evidence/answer_coverage_models.py`、`research/evidence/report_claims.py`；必要窄集成tests。模型字段采用服务器候选ref，完整重数据留在实际dispatch与审计；不复制整页到每个branch。

- [x] 新`subquestion-premises-v6`显式选择；v6 SYSTEM使用不含旧fact-only上限限制的公共基底，不能简单在v5矛盾指令后追加覆盖；旧v1–v5 SYSTEM、schema行为、缓存和失败回放逐字保留。GEN5/REVIEW3/QA9不变，不新增Agent或外部调用阶段。ANSWER仍独立审核。
- [x] 在既有ANSWER payload中加入服务器候选与可选source refs；返回的task_decision只能引用真实候选，缺项/重复/冲突/unsupported不得签发。旧回答无v6凭证不能自动升级。每分支只保留其合格见证及claim，保留完整未知peer和必要澄清。使用重建的claim→task映射验证子问归属，禁止计费等推断经不重叠的not_applicable格式指令分支重新进入正文；生成诊断不证明任务完成。
- [x] 对带合格见证的目标，使用已审任务决策，不再将同一inference当fact重证cap，或将非蕴含误作未回答。未带见证的分支继续原规则；不跳过源绑定、角色、动作、对象、条件或QA，模型keep不由服务器清除。
- [x] 相同凭证factory用于live与实际transport认证replay。QA/正文资格须验证真实facts与当前receipt；修改task、claim、parent、review/output、witness或DTO均失效，不能只认序列化digest。避免渲染递归调用自身重放。
- [x] 两个实际Writer入口使用v6；ReportDimensionAudit登记新合同，必要小型branch字段进入API。使用标准OpenAPI导出/TypeScript生成与编译，不改UI。
- [x] 预算使用实际新SYSTEM/user/output字节；全局预算、旧checkpoint已付费用、保护阶段及最多一次GEN补交均保持。超过窗口明确未审，不裁条件、不增加隐藏重试。紧凑ref减少重复支持。
- [x] 完整GEN→REVIEW→ANSWER→canonical→report→QA→replay集成测试，旧三run真实记录按旧合同逐字一致；当前无凭证/篡改/计费错引控制仍失败。规格通过再质量审查。

## Task 3：冻结、真实四家验收与交付

本清单随实现提交，记录提交前状态；不预记提交或推送成功。实际远端SHA、提交文件、源码与干净状态由发布后记录核对。

- [x] 相关回归、一次最终完整后端、按真实文件配置与HEAD比较新增Ruff、标准API生成和类型编译；后端恢复测试必要时仅放行只读进程身份。任何失败日志原样保留。
- [x] 新N4冻结源码/输入/hash和不含秘密的源码ZIP。复制同一固定页wrapper并适配到新目录；不import会写旧目录的helper。锁定旧211原件及更早锁，使用原8题22分支/rubric，不把标准答案或审核单传给Agent。
- [x] 同四家固定2026-10-21页、最多两产品并行、48calls/160000tokens/0.25USD估算保护、temperature0、默认模型配置、1200秒、retry0；只在本轮测试启用两个实验flags。记录实际版本、送达材料、调用/tokens/未知usage/超时/截断/回退/最终QA，不称新抓取、盲测或全Graph。
- [x] 独立逐项读四份最终report.md与精确所选span，分别计原题/必要分支、文字/完整支持/原子性/系统QA。重点核BW No真正发表、Trello跨板非蕴含不变B禁止、计费错引不放行、QA仍审当前目标；缺项如实保留。
- [x] 更新README、Agent执行说明、交付文档与原样报告。新轮结果与旧3/8、12完整分支、0/4报告分开；不把离线/反事实当真实生成成功，不以调用数宣称降本或因果提升。未训练、默认flags0、模型权重只确认alias。
- [ ] 只在测试、双审与文档复核完成后扫描明确待提交文件，不提交本地凭据/运行数据。按持续授权精确提交并推现有分支，记录远端SHA、源码不变与干净状态；报告是否达标由独立正文验收决定。

## Task 4：真实窗口失败后的定向修复（2026-10-28）

N4首次真实回放已完成，但四家实际签发凭证为0。Bitwarden有已审核collections超限推断，最终ANSWER因context窗口超限未派送；Trello2虽实际送审，但输出JSON无效，其跨板生成目标也未对齐。N4源码、输入、调用、原始报告及独立失败评分完整保留，不能把合同单测当成真实恢复。

- [x] 先用当前生产器离线重建真实待发payload，量出UTF-8字节与重复来源，确认窗口失败根因。
- [x] 候选改为紧凑ref及必要语义，重用完整任务、published claim/support和父级原文；哈希/坐标等认证身份留服务端。不得裁条件、抬14k或1600上限、增加调用阶段、跳审核或扩其他生成/价格/QA功能。若需要wire版本，明确区分并保留N4真实v6重放。
- [x] 在新`data/artifacts/task-conclusion-window-2026-10-28/`保存新红绿、代码与证据；锁定整个N4目录后旧原件只读。唯一实现者串行修改，规格与质量双审后做必要最终门禁、API核对、重新冻结。
- [x] 重新跑四家同输入真实阶段回放，独立读最终正文与精确选证；分别报告N4失败和最终轮，0凭证不得冒充新通道已实际验收。沿用8题22分支标准，不训练、不新抓取、不启默认flags。文档、凭据扫描及分支提交推送统一在Task3收尾。

## Task 5：将已审核原子决策核心独立投影（2026-10-28）

N5真实Bitwarden已送ANSWER并从真实GEN／REVIEW／ANSWER认证签出一张collections凭证，但同一原始分支选择了无对应凭证的人数推断，现有全体推断均合格条件将整分支撤回。只读反事实保持真实传输／原始模型输出／上下文不变，仅让canonical选择原分支已包含的合格collections核心，现有全部守卫即保留No。这说明发表单位仍耦合到整包混选，而未真正按已审核原子决策交付。

选择显式版本化的交付策略：仅在完整单题、原模型明确No、所有服务器请求任务均为people/container数量需求、已有真实quantity_excess凭证且不存在OR／其他操作任务时，保留原模型已选择的一条决定性合格推断。记录原IDs、保留IDs、排除IDs及策略版本；原输出不改，其他主张仍保留在审计。资源权限、计费、混合任务和未知前提不进入此策略。新增策略必须由实际producer派送并认证，旧无策略的v1–v6记录按原语义重放。

- [x] 在新`data/artifacts/task-decisive-core-2026-10-28/`锁整个N5及历史原件，保留N4/N5真实失败评分和报告；不将离线反事实计作新生成或真实交付。
- [x] 唯一实现者先红后绿，采用必要最小策略标记和canonical调整，解析、正文、QA和重放共用真实认证核心。不新增主张、不改kind、不将裸approved当资格、不借未知peer或其他任务，不改SYSTEM／阶段／14k／1600／global／retry／默认flags。
- [x] 窄正例用真实N5混选场景，负例覆盖OR、价格／权限混问、跨题、无原始选择、父／源／任务／审核或凭证变化；旧检查点原样重放，规格与质量审查后做必要最终门禁和新冻结。
- [x] 四家同资料真实再验，直接核对No是否进入最终正文，同时保留其余失败；文档与发布按Task3收尾。报告仍未达标须如实说明，不能把已调用或已签凭证当作最终发表。
