# Agent 实际执行与证据约束

本文描述真实执行入口，供开发、测试与排查使用。总图以 [`graph.py`](../backend/packages/orchestrator/graph.py) 为准；demo 图生成合成数据，不能作为 real 图事实准确率的验收依据。

本轮[Collector 原文入库、逐子问选证与交付预算复验](optimization/2026-10-25-collector-task-delivery.md)（2026-10-25）：**正文严格1/8，低于上一轮3/8，四份报告均未达标，实验默认关闭**。新Collector隔离返回6条提案，经生产定位与准入离线重验6/6；逐任务说明、候选合并和完整父题设进入实际入口。最终QA计划28项全部实际送达且身份合法，10个内部原问也全部送达，但机制仍判0通过／10阻断；送达不是内容通过。七角色各一条请求隔离为5通过／1部分／1失败，Writer仍生成越出单任务的复合主张；Trello逐板规则在上游逐题检索时已从Writer范围丢失，另有9次生成及1次尾答零派送预算拒绝。四家70次／193892 token，七隔离7次／26616 token，**本轮合计77实际调用／220508已知token，未知0**；未重跑single，不与上轮single混作同版对照。新增69项测试；全后端首次7724通过、1项沙箱ps受阻、1跳过，仅受阻项以必要权限复验通过，同源码7725个不同用例验证通过，非单次全套全绿。1Password两条生成完整输入因导出脱敏仍未验；未训练，未验新抓取／全Graph／生产稠密RAG。[结构化结果](optimization/2026-10-25-collector-task-delivery-results.json)。

上一轮[子 Agent 隔离验收与实际交付](optimization/2026-10-25-agent-isolation-handoff.md)（2026-10-25）：后端 **7656通过／1跳过**，新增135项。已修复实验逐任务Writer缺少三类上游内容、拆题共享前提失绑及真实规模装包顺序；预算与默认关闭保持。固定资料同版对照：流水线 **3/8通过，70次调用／194658 token**；单Agent **6/8通过，含共享采集15次／81820 token**（新增生成4次／53558 token）。七角色各一条请求隔离为4通过／2部分／1失败，不能当完整Agent闭环。**四份流水线报告仍未达标**：Collector原文定位准入、选证误拒、原子写作与尾部预算／审核仍有缺口；正式主张6/6完整支持、3/6单谓词。最终QA计划27项仅23项送达合法，内部原问10项仅9项送达。四次迭代及对照／隔离累计290实际调用／929199已知token，未知0，失败均保留。原八题已曝光且每请求一次，不作泛化或因果结论；未训练、未验新抓取／全Graph／生产稠密RAG。[结构化结果](optimization/2026-10-25-agent-isolation-handoff-results.json)。

上一轮验证见[任务谓词、实际载荷与范围绑定复验](optimization/2026-10-24-task-predicate-budget.md)（2026-10-24）：后端 **7521通过／1跳过**，新增52项；紧凑完整选证、按所选规范事实生成、有限复合守卫及范围召回已进实验入口。四家同版回放 **63实际调用／175187 token**，12个分析／比较／反思模块均真LLM、无回退；最终QA13次，28项27合法、1历史项未送，10个内部原问均送且合法。**固定原八题仍3/8，报告未达标，实验默认关闭**；全文所选支持6/7、单谓词2/7。BW容量恢复但附加人数解释漏绑，CF跨域结论仍缺且账单CPU正文退缺；Trello3次预算拒绝转至生成／审核，并有共享Observer前提丢失。合法身份重放不替代内容验收，未训练，未验新抓取、全Graph或生产语义RAG。[结构化结果](optimization/2026-10-24-task-predicate-budget-results.json)。

上一轮验证见[已采证据选用、原子写作与剩余QA调度复验](optimization/2026-10-24-selected-support-writing.md)（2026-10-24）：后端 **7469通过／1跳过**，新增45项。逐任务ref选证、限定支持写作与完整派送验证进入实验入口；最终QA严格整题ID回显，局部支持另列，并有界推进剩余窗口。四家真实回放 **62调用／187976 token**，另3次零transport预算拒绝；QA29项中28项合法，1项完整上下文超窗未送，未出现失效返回。**原八题仍3/8，报告未达标，默认关闭**；可见主张完整支持8/8、单谓词3/8。1Password访客恢复、BW容量遗漏，复合写作和Trello预算仍待修。12个分析／比较／反思模块均实际LLM执行无回退，不代表整题或完整Agent系统已合格；未验新抓取、全Graph、发布或生产语义RAG，未训练。[结构化结果](optimization/2026-10-24-selected-support-writing-results.json)。

上一轮验证见[原子任务覆盖、引用边界与独立最终QA复验](optimization/2026-10-24-atomic-independent-qa.md)（2026-10-24）：后端 **7424通过／1跳过**，新增55项。服务端有限请求补全、越引用守卫及独立逐题QA进入实验入口；实际provider重试、超时、未送与合法返回分开记账。两轮四家106实际调用／已知326148 token，另1次usage未知。最终原八题严格 **3/8**，可见主张完整支持6/6、单谓词4/6；四家均调用QA，31项中17项合法、12项未送、2项返回失效，**报告仍未达标，默认关闭**。两轮各12个分析／比较／反思模块均实际LLM执行无回退，不代表写作与整题交付完成；未验新抓取、全Graph、发布或生产语义RAG，未训练。[结构化结果](optimization/2026-10-24-atomic-independent-qa-results.json)。

上一轮验证见[任务答案交付、共同状态与预算复验](optimization/2026-10-24-task-answer-contract.md)（2026-10-24）：最终后端 **7369通过／1跳过**，新增23项。局部任务答案、服务端原问分段、具体失败反馈和同题共享QA进入真实入口；共同状态只是诊断，不授予完成。两轮四家102次真实调用／已知302260 token，另3次usage未知。最终原八题严格 **3/8，报告未达标**；最终QA6次、只有三家调用，含一次超时且有未送项，1Password Reflector回退后没有最终模型重核。不能宣称全部Agent或最后QA完整通过。实验继续默认关闭；未验自动发现、多产品同矩阵、全Graph、发布或生产语义RAG，未训练。[结构化结果](optimization/2026-10-24-task-answer-contract-results.json)。

上一轮验证见[已审核任务投影、局部修复与最终 QA 复验](optimization/2026-10-24-task-projection.md)（2026-10-24）：后端 **7346通过／1跳过**，新增40项；局部主张投影凭据、任务失败修复及最终QA诊断进入实际入口。两轮四家封存页面真实回放共100次实际调用／304236已知token，最终QA共8次；最终轮原八题严格 **2/8**，低于历史旧流程4/8。最终轮12个分析／比较／反思模块均真实调用且无回退，但最终QA只送达11/20项，另9项保留待审。**报告仍未达标，实验保持默认关闭**；任务决策尚未编译为完整最终答案，Trello／Cloudflare／Bitwarden／1Password仍有遗漏或不完整。未验新抓取、全Graph、发布或生产稠密RAG，未训练。[结构化结果](optimization/2026-10-24-task-projection-results.json)。

上一轮验证见[按任务 ID 执行与交付预算复验](optimization/2026-10-24-task-execution.md)（2026-10-24）：最终后端 **7306通过／1跳过**，较基线新增113项。任务协议、逐项生成／审核及派送重放已实现；真实内容回归后保持**默认关闭**。两轮四家封存页面回放共74次实际调用／228320已知token；最终轮41次／130248 token，12个分析／比较／反思模块均实际调用，最终QA模型重核0次。原八题严格1/8，低于旧4/8；Trello仍有漏答和预算延期，Cloudflare关键稿未发表，BW有证否定被最终守卫挡回，1Password复合主张被拒。机制测试不等于报告交付，未训练。[结构化结果](optimization/2026-10-24-task-execution-results.json)。

上一轮验证见[子问证据分配、原子主张与QA归属](optimization/2026-10-23-subquestion-allocation.md)（2026-10-23）：后端 **7193通过／1跳过**，新增68项；子问完整资料分配、统一14KB实际派送门、条件推断原问绑定、严格缺项分离及QA问题归属已接入。最终四家同版固定页面真实回放 **68次实际调用／229379 token**，另3次零transport预算拒绝；首两家诊断另34次／114740 token，全部保留。原始八题严格 **4/8**，报告仍未达标：CPU规则已进正文，Trello的A/B与下载、导出恢复，但义务／第二题仍漏答；Cloudflare权限结论因最终审核预算不足未发表；Bitwarden旧core gap覆盖误阻已消除，矩阵阻断仍保留。精确支持、复合主张和报价来源仍有缺口。不是新抓取／全Graph／发布／生产稠密RAG验收，未训练。[结构化结果](optimization/2026-10-23-subquestion-allocation-results.json)。

上一轮验证见[子问定向选证与局部重写](optimization/2026-10-23-targeted-question-repair.md)（2026-10-23）：后端 **7125通过／1跳过**，新增106项。完整规则提案、单轮定向修复、引用预留、CPU事实合同与最终QA重核进入实际入口。两轮四家固定页面回放共119调用／已知395823 token，另2条usage未知；最终轮73调用／242831 token、全部stop。原始八题严格完成4/8；Trello逐项与条件仍遗漏，CPU前提未发表，部分可见主张过宽，BW有效澄清仍被全局context gap误阻，**报告仍未达标**。Analyst另有一次空结构回退。不是全Graph／新抓取／发布／生产稠密RAG验收，未训练。[结构化结果](optimization/2026-10-23-targeted-question-repair-results.json)。

上一轮验证见[子问前提与正文／QA一致性](optimization/2026-10-23-subquestion-decision.md)（2026-10-23）：后端 **7019通过／1跳过**，新增97项；最终复审Prompt调整后89项专项通过，OpenAPI/前端构建与变更审查通过。可读引用、逐子问前提摘要、精确支持隔离和统一问题块已接入。两轮四家固定页面真实回放共 **123调用／391144 token**；最终轮61调用／193421 token。原始八题严格完成 **3/8**，正式可见主张11/11完整支持、9/11单谓词，但另有CPU服务器事实漏绑。**报告仍未达标**：1Password漏选、Trello并列对象/第二题漏答及早期Reflector与最终QA冲突仍待修。不是新抓取、全Graph或生产稠密RAG验收，未训练。[结构化结果](optimization/2026-10-23-subquestion-decision-results.json)。

上一轮验证见[问题结论绑定与完整规则投影](optimization/2026-10-23-question-conclusion.md)（2026-10-23）：后端 **6922通过／1跳过**，新增89项；有限操作覆盖守卫、完整可选举例前规则候选和正文操作识别已接入实际入口并通过独立审查。四组固定历史页面、真实模型回放共 **60调用／193790 token**，无截断。原始八题有6题核心内容覆盖、1题部分遗漏、1题整题遗漏，但仍有1Password否定前提漏绑、Cloudflare正文与答案状态冲突、Trello权限漏答及服务器事实漏绑；11条正式主张10条完整支持、仅4条单谓词，不能当完整报告合格率。**局部报告仍未通过严格验收**，实际QA共10阻断。不是新抓取、旧八题＋新四题全量复验、全Graph或生产稠密RAG验收，未训练。[结构化结果](optimization/2026-10-23-question-conclusion-results.json)。

上一轮验证见[Collector 正文交付与 Writer 截断](optimization/2026-10-21-collector-input-writer.md)：Collector 从同一可见DOM重放并重验标题，空提取窗在模型调用前跳过；provider Markdown仅恢复唯一完整纯转义引文，含raw HTML的文档不进入新恢复；Writer仅feature逐题模式使用短support_refs，并从实际发送的同canonical支持恢复完整绑定。原exact/legacy、公有schema、预算与1600写作cap保持。后端6833通过／1跳过；四个有来源产品的Analyst、Comparator、Reflector、Writer都实际调用，Dropbox/Miro准入前阻断。旧八题6正确／2遗漏、新四题4遗漏；claim ID 9/10绑定、6/10单谓词。问答结论、具体前提和服务器事实仍有支持缺口，严格局部资格旧0/4、新0/2，实际QA共12阻断；不是全Graph／发布／生产dense RAG验收。中断丢失的临时辅助证据已披露，恢复后的审读和日志直接保存在项目忽略目录，未训练。

上一轮验证见[完整主张审核与问题结论投影](optimization/2026-10-20-claim-semantics.md)：新增v3选定支持的有限语义冲突守卫，实时/最终QA共用；Writer与独立审核提示逐谓词保持can/must及条件；问题级结论识别完整中文闭合范围，产品规则与请求对象分离。最终后端6649通过／1跳过；旧八题4正确／4遗漏，新四题全遗漏，6条发表claim ID完整绑定但仅4条单谓词，另有服务器CPU短句缺精确绑定。BW/1P/CF的Analyst、Comparator、Reflector均实际执行无回退，Writer均调用但BW length出错；Dropbox、Trello、Miro准入前阻断、下游未执行。Trello实际提取body为空，CF已抓角色规则未进facts，不能用packet标记当语义送达。阶段QA分别10/2个阻断；全Graph、自动发现、发布、生产dense RAG未测，固定runner False不作系统失败评分。未训练。

上一轮验证见[完整引用支持与回答投影](optimization/2026-10-20-bound-answer-projection.md)：最终6452通过／1跳过；四组各首次38调用／129433 token。正文及保存均5正确／0错误／3遗漏，全部发表主张5/7完整绑定。BW上限否定和固定离职澄清已正常生成；BW额外共享动作越过窄引用、1Password“可以”到“必须”的模态强化、CF范围题漏答与Dropbox正文仍待修。内容合格2/4，内容与绑定同时0/4，系统0/4、6阻断。三家Analyst／Comparator／Reflector／Writer真实调用且核心模块无回退；Dropbox无接受来源未调用核心阶段。Writer实际输入已核实派送，但两套遥测状态仍不一致，BW真实核心资料仍有遗漏；不能仅据unverified遥测断言未发送。730冻结文件、5 helper及1332旧文件保持；不是Planner／全Graph／生产稠密RAG验收，未训练。

上一轮验证见[逐题证据包与原子回答](optimization/2026-10-20-agent-question-packets.md)：后端6308通过／1跳过，四组各首次30调用／123676token。正文及保存记录均3正确／5遗漏；发表观察5/6完整绑定，内容与绑定同时0/4、系统0/4交付。三组核心Agent真实调用，Dropbox采集阻断。各入口已统一选择身份；真实Writer两套派送遥测状态仍不一致，实际输入可独立核实。BW澄清、1Password复合句及CF范围误判仍待修，非feature逐题、Planner／全Graph／生产稠密RAG未验收，未训练。

上一轮真实验证见[逐题证据交付修复](optimization/2026-10-20-question-delivery-repair.md)：后端6151通过／1跳过，四组各首次30调用／116410token。正文5正确／3遗漏，记录4正确／1错误／3遗漏；Cloudflare两题及全部发表绑定合格，系统仍0/4交付。三组核心阶段真实调用，Dropbox无正文未调用生成模型。实际Reflector视图与Writer仍未逐题对齐；两条额外主张只有半句绑定。不是Planner/全Graph/生产稠密RAG验收，未训练。

上一轮真实验证见[Search／Fetch与证据消费](optimization/2026-10-19-deepseek-web-delivery.md)：后端5982通过／1跳过，四组各一次22调用／75844token。正文2正确／1错误／5遗漏，记录2正确／6遗漏；Cloudflare限定两题内容合格，系统仍0/4交付。Bitwarden、Cloudflare各核心下游实际执行且三模块状态为llm，1Password／Dropbox在采集处阻断。9份捕获完整可核验。默认关闭的新路线只在隔离CLI启用，Planner发现、全Graph及生产稠密RAG未在本轮验收；未训练。

上一轮真实验证见[Collector逐题交付](optimization/2026-10-19-collector-question-delivery.md)：后端5811通过/1跳过；四组30次真实调用，正文3正确/5遗漏、记录2正确/6遗漏，0/4完整报告可交付。三组核心下游Agent实际执行，Dropbox采集阻断未调用下游。合同已接线不代表全召回或语义合格；抓取、选窗、Writer原始选证及最终回答状态仍有明确缺口。

此前真实验证见[完整证据与答案发表恢复](optimization/2026-10-18-evidence-recovery-delivery.md)：5664项后端通过，四组40次真实调用；正文3正确／1错误／4遗漏，记录2正确／6遗漏，仍0/4报告达标。下面是有限规则及实际入口；中文数量结论误拒、下载规则投影遗漏、计费行／FAQ漏提取和错误缺证陈述仍未解决。实现检查通过不等于语义验收。

## Collector 定位、任务证据与联合预算合同（2026-10-25）

- Collector 默认 `question-focus-v2:<focus>`：只恢复唯一、完整、连续原文中的安全排版，最后核对 `quote.text == body[start:end]`。准入及逐题收据重建按 typed `extractor_version` 分派；历史v1原样重放，未知版本拒绝。改词、否定、数字、跨窗／跨段及歧义不恢复。离线已贯通 semantic、admission、RawSource、SQLite、snapshot；一次隔离通过不等于全部网页抓取或持久化生命周期通过。
- 子问按局部请求选动作，完整父题设保留为假设；`task_instruction` 同时进入选证、生成、任务审核，并以固定 SYSTEM `Server task instruction v2. ` 重建身份。每个任务独立构造完整候选，再按规范事实／span合并引用，有限拆批。候选JSON及其前缀上限10000 bytes；任务生成／审核user窗口14000 bytes，SYSTEM另计。**完整是当前可见候选范围内的完整，不能保证上游快照的相关事实全部进入该范围**；本轮Trello已证明更早的逐题检索仍会漏证。
- 任务修复总计最多两个唯一任务、各一次，新版可拆dispatch，历史协议仍保持原单次dispatch行为。指令、focus、父题设、selected support和上游产物均按实际派送重验；不能用未选父文档补足整句产品断言。
- 尾答按完整问题分窗，保留该题已审partial事实与所有前提／例外，完整system＋user上限10000 bytes；不同题不能互借claim。只在最后一窗完成后结束阶段，未送项保留延期和恢复状态。
- 预算预检与实际reserve共用请求构造和保守计量。空生成输入只给出可证明的最小消费下界，不能保证所选完整包必可发送。尾答保护12000、最终QA保护11608，原24调用／80000 token及旧checkpoint已记费用不变；本轮仍有10条零transport拒绝，联合调度尚未解决。
- 独立最终QA使用 `independent_questions_v3`，完整父题设参与context身份；同context完整共享、原问优先，维持6000 bytes／最多六批及每项最多两次。题设假设不要求官方证明，产品规则须selected支持；许可不推出义务。**必要澄清正文可能正确而机制仍阻断**：本轮BW2因 `diagnostic_only`、无正式产品claim及待澄清状态被 `_affirmative` 拒绝；不能因此认定正文澄清错误，也不能把mechanical valid当审核通过。

本轮只验证封存资料的阶段回放及每角色一个实际请求。四家12个分析／比较／反思模块均实际调用LLM，不代表产物被正确用于正文；Cloudflare任务规划仍有 `bounded_request_fallback`。本轮七角色隔离的Writer失败、Comparator部分通过，其余通过均仅限各自实际输入，详见页首交付记录。

## 子 Agent 隔离与 Writer 交付合同（2026-10-25）

实验逐任务入口在实际生成前，从当前快照验证 Analyst、Comparator、Reflector 三类产物，并传入 `upstream_analysis`、`comparison_assessment`、`reflection_constraints`。这些内容是可出错的分析建议，不能替代规范事实及引用。仅真实生成 transport 验证后，才登记实际发送的上游依赖；零 transport 不记消费成功。

比较与反思使用第2版有界投影：保留状态与完整条目，明确记录省略数量，仍遵守原1800／1600字节配额；整块超界不能静默丢失或截断条件。历史第1版按旧整体装入规则重放，服务端SYSTEM代际身份用于防止字段删除后重算哈希的降级。真实输入规模仍须核查，字段在小fixture中存在不能证明整条生产请求已发送。

候选选证优先装入完整任务、父题设和规范事实；三项建议在选证后交给生成及任务审核，发送前后都重验。新generation的两阶段SYSTEM身份绑定对应的新review标记；删除新review标记不能降级，历史无此generation身份的真实审核继续原路径。原件因窗口不足未装入时为预算延期，真正无原件或无合法引用时为缺证；不会为了送达而提高14000／10000字节上限。

[`question_scope.py`](../backend/packages/research/question_scope.py) 从同产品唯一的原始请求行恢复完整父题设，生成版本、父身份和子问绑定。选择、生成、任务审核、最终回答及独立 QA 保留该上下文。人数、套餐和 A/B 设置仍是请求条件；子问本身继续作为召回主意图，父题设只辅助，不能让“下载”和“导出”退化成相同查询。跨产品、歧义父请求不借前提。

父上下文第2版另复用服务器原有的拆分／分组纯逻辑，验证同一原始行能否精确产生完整子问，修复“？请将……”被拆成“？ 请将……”后的失绑；没有删除任意空白或跨行模糊匹配。父文本、公开子问全文及ID保持。generation／review的固定SYSTEM身份选择重建版本，新代不能靠改JSON版本或删除单处审核标记降级；没有新身份的历史实际请求按第1版原样重放。

新格式在服务端 SYSTEM 中带代际身份；回放会重新验证 canonical 子问全文、父题设和当前上游产物。删除新字段后重算普通哈希不能降级到旧格式；真实旧格式仍可回放。此处是服务端交付一致性检查，不提供全库同时伪造下的密码学签名保证。实验默认关闭，24 次／80000 token、最终回答与 QA 预留保持。

[`eval_agent_isolation.py`](../backend/scripts/eval_agent_isolation.py) 只读已完成封存阶段运行，按原提示哈希恢复实际 system/user/schema；Planner、Collector、Analyst、Comparator、Reflector、Writer、QA 各重放一条实际模型请求。无实际请求时标记未验证。它验证的是**模型请求隔离**；网页抓取、工具执行、规范准入、持久化及完整 Graph 须另外验收。

```sh
# 未加 --live：本地预检，不加载模型凭据、不发请求；输出目录必须不存在
PYTHONPATH=backend .venv/bin/python -m scripts.eval_agent_isolation \
  --source-run /absolute/path/to/completed-replay/execution \
  --output /absolute/path/to/new-isolation --mode isolate --role writer

# 同批已采规范事实与完整原题，直接生成短报告；显式启用模型
PYTHONPATH=backend .venv/bin/python -m scripts.eval_agent_isolation \
  --source-run /absolute/path/to/completed-replay/execution \
  --output /absolute/path/to/new-single --mode single --live
```

单 Agent 不读取旧报告或参考答案；流水线与它共享已采证据，但提示布局、上游分析和运行时审核不同。成本分别列流水线总量、共享 Collector、直接生成新增量及含采集总量。每请求一次、已曝光开发题、同模型别名和温度并不能提供统计或因果结论；底层模型版本也未独立验证。

直接对照的完整重复对象及文本使用无损共享，服务端展开后对payload／facts双SHA校验；事实主行ID、source_id和问题正文／ID保留字面，原题sources数组可以共享，解码后的完整原题与输入必须全等。未知、循环、歧义引用拒绝。输入预留与生产一致，为逻辑消息UTF-8字节加256，不把HTTP JSON的二次转义重复计入；此方法仍是保守估计，不是精确tokenizer。

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

本轮新增 [`native_question_rules.py`](../backend/packages/research/extraction/native_question_rules.py)：在当前提取窗中召回与原问有关的完整规则块，经 `structured_evidence.py → semantic_extraction → admission` 原入口重验。无可靠结构时上限800字符，有可验证标题时完整小节上限1600；子例外不能被切掉，跨窗和超长整体拒绝。它是候选提案恢复，不直接向 Writer 写事实；坏 disclosure、表格或标题身份仍拒绝。

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

本轮 [`task_protocol.py`](../backend/packages/agents/writer/task_protocol.py) 将有限规则识别的请求与模型计划合并：明确的协调主问逐项保留，宽泛 source_rule 和多子问共享短片段不能吞掉已识别请求；原片段仍是原问精确子串，动作路由继承原问的疑问性质。条件和格式要求不生成独立任务，未知自然语言仍交语义审核。服务端补项不受模型48行解析上限静默截断；超过12个活动任务的请求有稳定ID与延期原因。明确并列动作的前后顺序、跨句形式共用原子守卫；条件内的动作词和动作对象不据此判复合。新增 [`classification_denials.py`](../backend/packages/research/evidence/classification_denials.py) 拒绝所选 span／operation quote 没有的有限分类否定，父文档不能补支持，实时与最终重放同用。

默认关闭的实验逐题入口（`WRITER_TASK_EXECUTION_ENABLED=1` 显式测试）使用 [`task_protocol.py`](../backend/packages/agents/writer/task_protocol.py) 和 [`task_execution.py`](../backend/packages/agents/writer/task_execution.py)。小型规划只接收原问，输出必须是原文片段与有限 focus，不能产生来源事实；服务端派生绑定产品、维度、原题、片段、动作和对象的稳定任务 ID。规划无效时记录有限规则回退。普通生成每批最多3项、每项最多1条原子、最多12个活动任务；独立审核每组最多2条原子、10项检查，三任务必要时最多3组；超额、无响应或无审核额度显式延期，一个无效项不会删除其它项。命名对象分别推理，另有按动作区分的 `rule_ACTION` 规则任务。请求场景仅供条件推断，不能变成产品事实。

各批只携带任务所属的完整原问及对应逐题资料，不带其他原问的重复包；从当前准入视图交错优先安排任务的完整原文，再按真实字节窗填充；不切断角色、套餐、访问范围、AND／OR或例外。原子只能引用该批实际发送的规范目录，服务端恢复完整绑定。主张审核和 task→predicate 完成度分别核对，所选合法 ID 不代表整句成立。`question_task_delivery` 保存每次实际 transport span、请求 hash、任务与 fact IDs；QA 逐次校验规范原文、支持和完整原题，再合并真实送达事实。任务状态和本地选择标记不能替代派送证明。

新增 [`task_support_selection.py`](../backend/packages/agents/writer/task_support_selection.py)：每次任务生成前先进行一次有界、仅返回引用的选证，操作／谁可操作须选择对应 o-reference，其余规则使用完整 s-reference；最多一个操作或必要例外对的两个片段。选证不是事实证明，非法、遗漏或无完整支持的任务明确延期／缺证，不给默认引用。生成只能使用该任务所选的完整支持，引用集合必须一致，之后仍经过原绑定、主张守卫和独立审核。选证与生成都核对真实 agent、scope、完整 system／user、返回内容和 transport；生成回执不符时整批延期，不解析为合格主张。可读操作身份从已验证目录对应的规范事实恢复，未验证操作行不能覆盖。选证输入与结果单列保存在任务收据，额外调用受原全局预算约束。

最终原题答复只消费已支持主张，执行一次独立 `dimension_answer_review`，继续 v3 完整子问与引用合同；紧凑模型载荷去掉重复 hash／坐标，保留完整选中原文和操作条件，完整身份仍保存服务端。没有完成此审核不能自动标记已回答。`answer:<scope>` 与 `final_qa:run` 单独预留额度，完成／复用后释放，checkpoint 恢复不压缩已持久化的最终预留；不提高原24调用、80000 token、1600写作输出或14KB实际JSON上限。`WRITER_TASK_EXECUTION_ENABLED=0` 回滚以下旧逐题生成／修复路径；非功能、无题及操作定向重做也沿原入口。

新增 [`task_projection.py`](../backend/packages/agents/writer/task_projection.py)：任务审核保存有限完成度、`conclusion/relation`，最终模型接收明确任务决策。只有当前运行／快照／消费、稳定任务身份、完整主张摘要及实际独立审核 span、输入 SHA、assignment 和原始审核结果全部一致的局部推断，才可在整题未核实时进入正文；不自动升级整题状态。Writer 隔离草稿通过独立 live 凭据参数重放新消费，不把本地自洽 task 状态当成证明；QA 使用同一展示函数。

[`task_answers.py`](../backend/packages/agents/writer/task_answers.py) 从同一完整凭据恢复已审核任务的结论、对象、原问片段与主张，显示在完整原题下。整题未核实仍可保留明确局部结论；这不是把 task_fulfilled 自动升级为整题已回答。服务端编译连续完整原问分段，模型只回传有序完整 `segment_id`；禁止自行替换分段，坏同行及非字符串 ID 局部隔离，字符串 foreign／重复 ID 继续受原守卫约束。完整 v3 来源、前提与分支验证仍执行。

选证请求从已验证目录派生紧凑载荷，保留每个完整可选片段、操作身份及角色／套餐／时间／例外限制；去掉重复提取位置、规划提示与生成专属字段。实际生成只发送所选引用所属的完整规范事实及已验证例外依赖，重建逐题包并保留原引用编号。选择、生成各自仍核对实际完整请求与响应，QA 可重放；精简不授予新的事实支持。

[`task_predicates.py`](../backend/packages/agents/writer/task_predicates.py) 提供实时和保存投影共用的有限复合属性守卫：私人空间与共享容量、人数／容器上限与核心功能、计费与运行时限、工作区级可用性与逐人逐板设置分别处理。明确题设人数只用于条件推断；同对象、同单位的一个官方上限可以否定整体合取请求，不推断其他单位的上限。这里只识别已覆盖的表达，未知自然语言仍依赖独立审核，不能视为通用蕴含分类器。

对于明确中文角色授予片段、双域名和操作的范围题，问题检索在创建 evidence use 之前，从当前产品已准入候选中补同来源角色规则及范围限制，仍受原候选／事实／字节窗约束；新任务规划可补一个独立范围规则任务。旧任务 ID、延期状态与12项活动上限保持，新增任务受48条总记录限制，不将旧超限服务端任务重新规划。此路径尚不覆盖任意语言或资源范围表达。

来源支持而任务不完整时保留 claim、记为 partial；最多一轮、两个 rejected／partial 任务修复，沿原 ID、规范来源及独立审核。修复成为 supported 时退役旧 partial，仍未完成时保留原支持并退役本次替代稿，避免重复发表。`task_repair` 诊断不进入证据。默认旧修复打包器仍最多两组；普通三项任务生成必要时最多三组审核，每组原有上限不变。

这些是执行合同，尚非语义效果保证：当前发表已支持 claim 文本，没有把完整 task decision 编译成最终答案，最终模型仍重新判断整题关系／分区；部分支持不能自动填补未发表的场景结论。上一轮任务投影复验发生3次最终回答审核、4次最终QA模型重核，但仅11/20项finding送达，9项未送。当前实验最终QA每批最多6000 bytes、每次最多六批，完整条件不截断，仍可能存在未送项。Trello的任务延期未因三项生成批次根治，最新实际结果以页首交付记录为准。

新增 [`question_repair.py`](../backend/packages/agents/writer/question_repair.py) 的逐子问定向修复入口：失败诊断用于检索排序，不能成为事实。事实装窗时先预留合法完整引用，缺失谓词在裁窗前参与排序；修复上下文将失败原问、失败检查、已通过主张和完整资料放在同一个实际压缩窗口内装入，不再分开预估后回填；长审核评语留在原审计中，只带有界诊断，不增14KB上限。一次最多4个新原子、2批独立主张审核、2次受影响答案复核，总额外调用最多5次；Writer输出仍1600。坏响应/传输失败不盲重试，原支持和成功答案保持。审核主张与原文回写目标使用字面字符串，模型不能回传 `text_ref` 对象代替严格字符串审核。明确的多对象请求逐项校验，未知自然语言仍需语义审核。

新增 [`question_allocation.py`](../backend/packages/agents/writer/question_allocation.py)：从原问生成有限子问／动作／命名对象任务，先给各任务安排完整原文，再填普通背景；引用提示只从该次实际派送的规范目录取得，不构成事实。初写最多8个原子，修复最多4个；下载与导出各自成原子，AND／OR条件不能被拆散。超出修复原子上限单列 `question_repair_atom_capacity_exceeded`，整批拒绝，不静默截取或盲重试。初写、修复以及派送回执共用最终 `min(14000, use.max_bytes)` 门；32KiB本地视图不扩大实际写作窗口。

主张审核只把服务端解析 `question_answer_plans` 中已绑定的 `kind=inference` 与原问关联为 `scenario_claim_questions`；题设仅供明确条件推断，不能补产品事实或来源引用。`request_context_questions` 仅用于解代词，不能补未知身份或设置。原子须写明自己的条件，正文、答案及最终QA仍核对完整主张。修复元数据另给 `question_plan_missing_fields`，只来自现有请求澄清规则；账单的CPU、税费等资料缺项不再被误抄到严格计划澄清字段。

服务器缺价答复也消费正式审核主张：CPU时间计费前提必须具备当前同模式、单位、表头/脚注及精确绑定，不能直接用 raw fact 发表产品断言。缺少正式支持时只要求补输入，金额仍未知；最终 QA 用同批主张重放。

新增[有限问题操作覆盖](../backend/packages/agents/writer/answer_action_scope.py)：下载、导出、导入、投票、清缓存的明确子问，只能用涉及相应操作的已发表主张给出完整或确定是／否结论。生成、复审和保存重放共用 `coverage_resolution_reasons()`；已给场景不直接当作待回答操作，未知表达仍须语义审核。新增正文 `claim_operations()` 与规划关键词扩展分离，前置条件后的明确操作仍需绑定。源候选只恢复完整原文规则后的有限可选举例边界，必要列表和条件不能截断。这些检查拒绝已知错误，不证明一般蕴含；真实模型仍有否定前提、全文缺席断言、状态投影及服务器事实漏绑。

v3 逐条隔离支持审核：仅选定 operation quote／source span 及完整来源条件支持该主张，父级宽原文和其他主张不能支持额外谓词。明确独立动作与未重建必要条件在实时及最终 QA 共用守卫，保留角色权限前提、权限选项、日期与例外；有限识别不构成通用 NLI。

[`request_clarification.py`](../backend/packages/agents/writer/request_clarification.py) 从当前生命周期结果请求生成有限的纯澄清，使用现有 v3 partial／clarification／depends、空引用及固定正文／理由。步骤、释义、已识别的独立并列子问不获得整题资格；已给输入不重复问。完整来源规则继续独立答案复核，失败／无关规则可回到安全询问；真实核心资料和预算缺口继续阻断。Writer 已运行时，零 supported 的澄清分流不调用答案模型；采集失败仍可能阻止 Writer 执行。

逐题选择在8条/14000 bytes中先保核心事实和必要例外；阶段视图与最终compact用同一函数核验完整quote/value/qualifiers，只有元数据不算送达。模型从实际发送候选选择 `source_span_ids`，服务器生成可重放的 `source_span_bindings`；父事实只施加限制。合格澄清可局部交付，缺核心事实/例外仍硬阻断。显式功能问题现一次返回 `question_plans`，模型明确列出事实原子，服务器逐条核对整句与引用；不按标点猜拆，操作陈述仍需真实操作绑定。`claim_review_version=3` 的实时与持久化回放共用准入门，不能因模型自报 supported 而跳过。

- **入口**：[`writer/runner.py`](../backend/packages/agents/writer/runner.py)；分维度写作见 [`dimension_writer.py`](../backend/packages/agents/writer/dimension_writer.py)。
- **输入**：有效 Analyst、Comparator、Reflector 产物及准入证据包。
- **执行**：按维度分段写作；价格单独成段；将事实、比较、推断和待验证机会分别表达；逐条核对主张与引用，必要时做有限修复。证据不足时生成简短局部报告，保留阻断与补证清单。
- **输出**：报告、分段结果、主张审核记录、引用、版本与依赖。功能问题在三种深度都进入分维度入口：保留产品和子问作用域，联合问逐产品审核，代词继承最近具名范围，末尾请求限制随原问保留。
- **问题选证**：[`question_retrieval.py`](../backend/packages/agents/writer/question_retrieval.py) 在首轮草稿投影前及分段入口，对当前准入快照做本机 embedding 与词法 RRF；最多 128 个候选，普通候选每问三条、总计八条，可显式传入本机精排。完整同模式CPU表格行复用计费适用性、表头与脚注守卫，先作为该问题的core候选保留，再进入相同装窗与合法引用目录；脚注、免费CPU及异套餐／异模式不能代替整行。删除、离职、归属与保留问题增加 Writer 本地跨语种召回，相关核心原句和例外优先于套餐背景；独立核心分支共同受总八条／14000 bytes 约束，不能再被普通每问三条截掉。真正核心缺口进入既有 prompt 与 audit gaps，最终 QA 保持 incomplete；完整原文、值及条件均相同的冗余 ID 未发送不制造缺口，各来源身份仍独立。使用已冻结的本机 E5 时，配置 `KB_EMBEDDING_PROVIDER=local-e5`；没有本机 provider 时明确记为 `degraded_lexical`，配置了严格本机模式而模型加载/推理失败则抛出。有限意图规则与排序不证明事实正确，不保证全召回。模型计算离开事件循环，来源资格、当前快照与作用域在计算前后校验；选中顺序、版本和降级原因进入 trace。
- **覆盖保留**：最终选择从同一候选池补入缺失操作，保留已选操作的完整角色、套餐、对象、效果及条件分支；显式登录、邀请等必要前提只依据本条原文保护，排名上下文不能制造前提。同一原文中的其他操作不会关闭保护。容量不足时保留前提并记录 `missing_operations`；`candidate_missing_operations` 只表示本候选池缺少可识别结构，`ranking_only` 始终为 true，不是答案准确率。
- **例外绑定**：问题选证在总八条容量内补入当前可验证的认证、保留副本及独立链接例外，不能靠重复普通观察挤掉依赖；缺失时记录具体依赖缺口。Writer 输入显式携带完整例外及实际待澄清字段；通过同源明确名称识别的已知输入保留，未知命名仍可能保守遗漏。主张和最终答案分别核对角色、移除／保留／同步对象、否定以及恢复分配主密码和移除前使用该主密码登录等前提。保留数据、访问账户、停止同步、保留本地副本和有效链接分别处理。收据需重新验证捕获、源条目、上下文和事件，外来或伪造收据不能制造约束；已准入依赖被视图容量遗漏时保持未核实。有限明确规则外的表达保守处理，不承诺一般语义蕴含。

中文“没有／只能”等明确答复进入最终断言与主语核对，示例、引述、疑问和不完整条件仍不能代替正式结论。保存记录必须通过实际已发表主张、逐字片段、角色对象、数量、否定及必要条件复核；解析拒绝保留具体原因，不能以中间模型标签覆盖。

缺报价答复分别保留显式购买范围、期限、币种、税费与实际付费席位。员工人数不换算席位，一年购买期限不推断年付，已给条件不重复询问。服务器审计当前完整准入快照，防止把 Writer 视图省略误称为全库缺价；一般不完整请求保留 partial，具备合格计费规则的明确缺项答复可标记 insufficient，QA 仍检查其状态与快照绑定。不计算未经核验的采购总价，也不声称官方网站永久无价。
- **消费与回答**：视图按实际排名装入完整观察，消费凭据保留有序 `requested_fact_ids` 供 QA 重放。分段来源从 live snapshot 取得，避免旧词法投影排掉新来源。逐问记录实际 `answer`、`resolution`、`conclusion`、已支持 `claim_ids` 和从已发表主张逐字复制的 `evidence_spans`；审核 `reason` 不充当答案。格式、对象或可识别主体不符时降为未核实。超容量不截断问题、原文或条件。
- **可读引用**：显式功能问题的短引用传输为 `{support_ref, quote}`；服务器只从该次实际派送且唯一匹配的候选还原完整原文绑定。重复、未知、篡改、截断条件或跨事实引用拒绝；精确支持、原句身份和旧坐标路径保留。四家固定上下文检查原候选零损失，未提高预算；它不保证模型会选对引用。
- **回答选择合同 v2／v3**：显式功能问题新写作使用 `answer_binding_version=3`，无题及历史 v2 保持原合同。模型选择已审核主张 ID，服务器复制完整 `claim.text` 与完整 span；未知／重复 ID、超过原有 600／1200 字限制均保留未核实，不裁前提。v3 澄清另存有限 `missing_fields`，服务器按操作、归属、保留副本、访问路径生成询问；事实 span 不包含问句，`reason` 仅说明实际状态及缺项。最终 QA 重建全文、顺序与询问，篡改及未知版本拒绝。它保证投影与绑定一致，不证明自然语言语义已合格。
- **问题上下文保留**：最多八条已选事实的显式功能问题使用最多 32 KiB 的本地证据视图，实际 compact 输入仍限制为 14000 bytes。普通问题保留已检索的完整原文和绑定候选，不从原文反推请求操作，也不按操作排掉同一问中的归属、数量等子问；定向重做仍限于指定操作。容量不足按整条省略并记录缺口，历史消费凭据继续按原容量重放。
- **回答二次核对**：`dimension_answer_coverage` 初审只看已审核主张；`dimension_answer_review` 保留主张 `kind`、精确绑定支持和初稿，但原始父段落不再作为正向证据回流。操作引用只提供已验证的操作原句与条件；短引用只提供已验证的完整 span。另列 `restrictive_source_context` 中已识别的时间/例外约束，只能拒绝或限定，不能补未发表答案。无预算、超容量或格式无效时不保留首轮 answered。
- **逐子问合同**：新有题报告记录 `answer_review_contract=subquestion-premises-v1`，仍使用 v3 ID 选择格式。最终复审按连续原问片段列出子问、自己的已发表主张、结论与关系；题设背景随相应请求保留，不单独当产品事实判断。服务器验证原问完整覆盖、父引用等于各子问引用并集、完整主张与来源摘要、父子结论一致。否定、容量、资源范围、许可不推出义务及完整删除结果使用有限拒绝规则；不能借另一分支的否定，不能把“可以升级”变成“必须升级”。摘要只证明身份和内容未改变，不能证明自然语言蕴含；未知词汇与完整条件仍需独立内容审核。
- **统一发表与重放**：正文和 QA 共用 `answer_presentation.py` 的问题块。存在明确问题时，独立观察段保留事实，推断只通过最终选中的 answered/partial 答案出现；能力表也按同一规则过滤。QA 仍重放全部主张绑定，并逐产品/维度检查完整问题、状态、结论、答案及引用块；篡改、重复或移动到其它产品不能通过。历史无题/v2 路径保留；服务端缺价及请求澄清继续按原快照合同重算。
- **混合事实**：同一观察里有其他操作候选时，非六类主张仅在它是单一已发送 `evidence_terms` 的完整原句或完整原文条目时允许无操作 ID；六类操作仍要求绑定。原句保留原语言，问题答案使用所选输出语言；原文匹配仍须通过来源、日期与模型主张审核。
- **预算与角色范围**：完整原始事实先装入14000 bytes，`non_operation_originals` 与完整例外 pair 提示只用剩余容量，不挤掉后续事实。`RESOURCE_SCOPE_RULES` 共享给 Writer、主张审核、覆盖与答案复审，区分角色本身给定资源权限和个人全部权限；后者须保留题设无其它授权，不因官方未写用户域名过拒，不外推到账户级角色。
- **缺报价与账单**：[`price_answers.py`](../backend/packages/agents/writer/price_answers.py) 先识别明确金额请求，再检查市场、套餐、币种、周期及税费；人民币不能代替市场，一年合同不等于年付。缺少输入时列出具体待确认项；口径齐全后检查完整当前快照，不受 Writer 排名截取影响。完整账单还需实际用量明细，只有合格当前来源中的肯定收费依赖才可提示 CPU 总量；否定收费、其他套餐及单次执行上限不充当该条件或总用量。未知范围不借来源单价填补，不推算总账单；账单查看权限、导出格式及留存期限不会被自动询价答复接管。有限高置信意图外的问法继续走原问答链。新生成的具体缺报价记录使用 `partial + insufficient + unknown`，绑定当前快照并在最终 QA 重算；历史记录仍可读取，重新审核时旧 `answered + insufficient` 不再满足当前不足状态要求。这表示已明确答复不足，报价证据仍未齐全，不虚构金额或引用。无关活动日期不会覆盖报价核验日期。
- **计费适用性重放**：同一命名语法核对每处 scope span 与题设，未知或混入其它套餐／模式拒绝。表格须有完整肯定 plan+mode 适用原句、匹配当前行及CPU表头→单元格正时间费率；否定／仅共现／未知限制不能证明适用。全部背景和脚注继续送QA；prose缺本句范围仅继承无歧义父级。`Free`名称误触否定仍未修，有限语法不是通用NLI。
- **边界**：不得自由查询新资料替换原引用。历史错误绑定继续拒绝；局部报告不等于完整覆盖，生成成功不等于事实准确率已通过独立人审。

此前数量越界结论的格式误拒已修，本轮 Bitwarden 正文出现正式“否”及请求澄清；日期、单位和作用域仍须独立审核。已采原文到完整主张的语义投影、其他文字规则的结论形成，以及采集／省略／准入状态的准确区分仍须按页首真实结果验收，不能由上述合同说明推定合格。

回答校验另检查明确套餐排他性及强制升级建议：被引用主张必须有相同套餐集合的明确限制，不能把某套餐被包含写成只有该套餐可用。未知范围保持未核实；有限词法规则不等于普遍语义证明。中文明确报价年月日按请求解析，无效或矛盾日期不自动生成已回答记录。

完整中文“只有……才能访问……”可作为闭合问句的必要条件断言；新增识别路径对完整主张块检查引号、示例、建议及未完成句，不从审核理由补答案。主体、对象、套餐、完整主张和 v2 引用重放仍须分别通过。

### QA：审核与重做决策

实验任务入口使用 [`independent_question_review.py`](../backend/packages/agents/qa/independent_question_review.py)，从当前 report audit 的真实原题建立独立检查，优先于历史 Reflector finding；反思无 finding 或回退不会因此跳过最终逐题审核。模型核对实际可见正文和所选支持，资格不足只能诊断，不能解除阻断。完全缺少 audit 时依赖现有报告缺失阻断，零候选收据为 `not_requested`，不声称模型已审。

实验模式 `independent_questions_v2` 每次最多六批，每批最多10项与6000 UTF-8 bytes；完整题目上下文装不下则整项保留未送，不裁前提。未送项优先于已付费失败项，同类先审原题，再审历史问题。合法同行缓存；失败、超时与未送项可在后续审核调用中按剩余预算续审，不是无界或后台自动重试。每项最多两次实际请求，provider 内置重试及备用 provider 共用本次剩余额度；`max_request_attempts` 经实际调用预算约束，不修改共享 settings，默认 None 保留其他入口的旧行为。

`expected_claim_ids` 显式给出整题 answer 的回显身份，`task_support_claim_ids` 另列同题局部支持；审核返回仍须严格等于整题 IDs，包括空列表，不能用局部任务 ID 替代或把局部支持升级为整题完成。新运行最终QA预留覆盖完整 system＋6000B user＋256余量＋1600输出（当前11000）；最终回答12000、全局24调用／80000 token不变。调用预留按真实问题数有界安排且不超全局；旧明确持久化预留保持。可继续派送的待审项保留阶段，新 basis 只重开阶段、不清零旧用量，完成或已无可继续项时释放。

`planned_issue_ids`、`sent_issue_ids`、`valid_review_issue_ids`、`unsent_issue_ids` 与 `model_unreviewed_issue_ids` 分开；`completed` 要求已有候选全部返回合法审核，不表示报告已通过。历史 `timeout_issue_ids` 与仍未完成的 `unresolved_timeout_issue_ids` 分开：真实 adapter 的 `llm_timeout_attempts` 不被后续错误或成功覆盖。无 usage 按完整输入字节上界加输出预留保守记账；缓存不伪造新 transport，checkpoint恢复保留已扣账。异常链只保留新建脱敏 cause 和超时类型，不能借诊断回显凭证。

新增 [`question_reconciliation.py`](../backend/packages/agents/qa/question_reconciliation.py)：在最终 QA 对可明确映射的历史 Reflector 问题复核当前正文和精确支持，最多一次1600输出调用、14KB输入；保留原反思，记录 `keep/superseded/current_limitation` 和快照/Writer/支持摘要收据。真实证据错误存在时保守保留旧问题；来源、矩阵、混合缺口或无法映射的问题不凭回答状态消除。预算/模型失败保留问题，不能将复核入口已接线当作旧问题已解决。

实验逐题路径另将无解除资格的问题作为 `diagnostic_only` 送最终QA，包括有证据阻断或混有可解除候选的情况；模型意见不能消除原阻断。每题只带该题最终答案的主张，以及经完整任务凭据重放的同题支持；不把其他题的全部可见观察重复塞入窗口。同题 finding 可共享完整上下文，每批6000 bytes、每次最多六批；没有送到模型、没有返回合法审核或失败的项保持keep，分别记录。返回其他批次的 finding ID 会使当前批响应失效，正常批仍保留；相同依据的收据可复用，缓存不计新 transport。

共同诊断函数 [`question_state.py`](../backend/packages/research/question_state.py) 将“原文未送达”“证据待核实”“已提供来源上下文”“已审核局部答案”和“整题状态”分开记录，进入 Reflector、Writer 与 QA。来源可用不代表结论成立，局部答案也不代表整题完成。当前仅统一状态表示与交付依据，真实语义判断仍有不一致，未宣称全部修复。

新增 [`question_context.py`](../backend/packages/agents/qa/question_context.py)：按当前快照、消费／选择凭据、真实成功Writer派送及完整原文／操作／引用身份，重放context缺口属于哪个问题。只有与服务器精确必要澄清完全一致的纯请求问题，才可关闭自身core遗漏的最终coverage误阻；事实问题、例外缺口、未知归属、旧凭据或篡改继续阻断。原gap和派送遥测保留，`answered` 标签不能获得豁免。资料摘录的沉默不能证明整页不存在规则；有限缺席守卫不误把有原文支持的“导出文档不含评论”当成来源缺证。

有限原文金额组件只从已发表、已允许的精确span重放，分别核对费率与账户最低费的套餐、币种、单位、周期及收费对象，多个金额保持各自诊断。未知推导/额外收费范围仍阻断。真实费率是否发表、其计量表头是否显式绑定，均按页首本轮内容验收单独报告；零金额问题不能当作费率验收，保存reason与不足答复状态也须独立核对。

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

实验任务模式新运行的最终回答预留为12000 token；对应单次完整回答审核请求最多10000 UTF-8 bytes，加256记账余量和1600输出，最坏11856不超过预留。最终QA预留11000，其他全局调用／token／费用上限不变。旧checkpoint中的20000回答及既有QA额度保留，不在恢复时压缩；未完成的后续阶段继续受保护。超窗时保留未核实，不裁来源条件或伪造审核成功。这一调整经过实际 admission／transport 回放，但没有根治所有任务延期。

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
