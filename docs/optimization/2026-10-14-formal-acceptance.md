最新状态（2026-10-18）：[引用、金额与 Agentic RL 数据准备](2026-10-18-agent-readiness-delivery.md)已完成结构绑定、额度分类与候选轨迹导出。后端 **5043 通过／1 跳过**，前端 **279 通过**且构建成功；两组同源码真实诊断共 **18 调用／65092 token**。正文核对为 **2 正确／1 局部／2 遗漏**，但仍有条件遗漏和问题选证缺口，**0/2 完整报告可交付**。旧＋新六次运行 16 单题只用于 development；三类标签各 1 条候选，其余 13 未标注。新 4 产品 8 题待用户人审、未跑模型；训练、奖励赋值与权重下载均为 0。参见[结构化结果](2026-10-18-agent-readiness-results.json)与[人审单](2026-10-18-agent-readiness-human-review.md)。

前一轮状态：最新状态（2026-10-18）：[问题缺口驱动补证](2026-10-18-question-gap-delivery.md)已接入实际 Collector；最终工程验证为后端 **4934 通过 / 1 跳过**、前端 **279 通过**且构建成功。三组首次真实流程及一次 GitBook 定向重跑共 **40 调用 / 136205 provider token**。最新报告选择的八题正文为 **7 正确 / 1 遗漏**；但引用片段、主张绑定、金额分类和 Miro Guest 来源仍有问题，**0/3 完整报告可交付**。这是已曝光题的生成后只读代理核对；Miro、Basecamp 未用最后版本完整重跑，离线解析重放不能冒充新报告验收。详情及版本哈希见[结构化结果](2026-10-18-question-gap-results.json)。

以下保留历史版本结果，不作为最终版本的新验收。

# 五项修复的正式验收记录

当前状态（2026-10-15）：查询规划与稀疏召回已接入实际 Collector→准入快照→下游 Agent 消费链。本机固定样本的 structured sparse top-3 为 **5/6**，raw 为 **0/6**，四个 hybrid/精排对照均为 **6/6**；外部模型和网络调用均为 0。完整报告交付仍未验收，四家新真实流程仍受月度额度阻断。最新范围、验证与限制见 [Agent 检索接线交付](2026-10-15-agent-retrieval-delivery.md) 及 [结构化记录](2026-10-15-agent-retrieval-results.json)。

下面保留前期不同源码版本的报告和验证记录，不能作为当前代码的新真实验收。

## 前一轮状态：资料到正文与短稿

资料到正文、条件归属与缺证短稿修复已通过当时的最终本机测试及独立审查；新四家真实验收被工作区月度 token 配额阻止，等待临时配额授权。该轮结构化记录见 [结果](2026-10-15-evidence-to-report-results.json)。

## 本轮：资料到正文与短局部报告（最终工程验证）

最终源码 SHA：`56b22bd7e4e312fd6a87f83ed99fded30b91df2cbb63e04ca4c65a6e1cf2ee79`，883文件，全量前后相同。后端 **4050通过、1跳过**；前端与本轮 **279通过、构建通过** 的版本逐文件相同，API JSON与生成类型一致。SPEC/QUALITY审查中发现的真实限制被过度过滤、软件未知轴被删等回归均修复，保留失败记录与31个新增参数化回归。执行计划见 [资料到正文修复计划](2026-10-15-evidence-to-report-plan.md)。

- **遗漏**：非法候选逐条拒绝，原Notion模型响应可解析候选从1到4，后续评论、共同编辑不再随中间无绑定候选丢失；这只是解析重放，未冒充模型重审。
- **上下文**：共享完整重复条件以提高有效原文容量；按操作与对象选择，普通页面评论不会被数据库属性或重复表格角色挤掉。相同原文重新结构化后Notion、Confluence、Nuclino六类候选齐，Coda仍缺阅读、评论、权限管理。旧错误绑定继续拒绝，未暗改旧审计身份。
- **条件**：分类、说明性背景及其他主体能力不自动成为前提；已补受邀、登录、only-after、父级访问及“Owner先授权Guest再操作”的反例。原文保留供语义审核，有限规则不能等同完整自然语言关系理解。
- **短稿**：真实缺产品×维度且有相应采集阻断时，走逐条审核的局部报告，合并空范围与补证清单。硬件离线原文/审核fixture经真实Writer入口生成1376字符，保留2个采集blocker；比较的是20332字符的读回副本，不能当作同一真实模型输入的A/B或人工准确率。

### 真实四家验收的当前阻塞

最终代码的本地API已重启，新空项目 `project-acceptance-72225e10679343d3` 已创建。但新建任务被应用配额规则返回429：工作区月度token上限2000000，估算累计2089864（104.5%），**此次尚未创建run，外部模型调用为0**。已请求用户确认是否临时提高到2500000，仅完成此次验收且保持单次200000 token/60 calls，结束后恢复原配额。没有删除历史用量、清零统计或绕过拦截。

下面的四家12/24及旧报告URL均为上一轮结果，不能视作当前源码的新真实验收。当前不能宣称报告达到完整交付标准。

## 上一轮结论（bedff52，保留历史）

最终源码 SHA：`bedff52e4c1cff678c1ab19e794efc68eb5f23730f43cc2866467ac91f7e4b9c`，882 文件，运行前后相同。后端 **4019 通过、1 跳过**；前端源码与已通过 **279 项测试及构建** 的版本相同，API JSON 与生成类型重新对比一致。collector 重做与 Coda 极性增量均通过独立规格、质量审查，审查中发现的反例已保留并修复。

| 原五项 | 本机验证状态 | 剩余边界 |
| --- | --- | --- |
| 请求条件与来源事实分开 | 准入、snapshot 与输入边界回归通过 | 仍需核验来源中的背景说明与操作执行前提的语义区别 |
| 核心阶段预算与回退 | 最新四家 Analyst、Writer、审核全部真实调用；126101/200000 token、29/60 调用 | 最新真实任务未触发 collector redo；无进展保留以真实保存来源、SQLite canonical 和 AI 图测试证明 |
| 产物消费与操作引用绑定 | 分析进入正文，旧错误 effect 被拒绝；明确单一操作极性矛盾不可由模型 supported 放行 | 正文只覆盖 12/24 格，条件归属及已采证据利用仍不稳定 |
| 生产语义 RAG | 实际项目 11 个全文索引 ready；E5/BGE 中英文检索、版本与作用域验证通过 | 两组检索 sparse 候选均为 0，不能宣称关键词融合已有效；小集召回不等于回答准确率 |
| 人审、改稿、下载与范围授权 | 独立 8 题经用户审核；本机改稿、重启恢复、浏览器落盘、项目范围与跨工作区反例已验证 | 完整商业报告验收未通过；生产基础设施验收仍缺 |

最新真实报告：[四产品操作对照草稿](http://127.0.0.1:5173/runs/run-f884e48518d2ff52bf8d55c79e5b2fc5?view=report#report-section-%E7%AB%9E%E4%BA%89%E5%8F%91%E7%8E%B0)。这是局部分析，不能视为完整采购或产品结论。任务 `completed` 只表示流水线结束：本轮 11 源、4937 字符（核心 3770）、37 个 warning，12 个模型审核观察格，引用 ID 合法，发布主张均通过当前确定性规则；这不是独立人审的事实准确率。

最终增量只改操作解析与主张校验，因此重跑受影响的四产品真实流程；硬件保留第三轮 `3557c1e2…` 的真实运行和离线读回证据，没有把它伪称为最终同 SHA 的跨品类全流程验收。它仍被缺证阻断。前后两轮的联网返回资料及模型选择不完全相同，12/24 与前轮 16/24、token 变化都不构成严格 A/B 结果。

### 下一步优先级

1. **已采证据到正文的利用率**：按产品×六种操作分配可用上下文，保留动作对应的角色、套餐、对象与条件；Notion 已有评论与共同编辑资料，最新正文仍漏出，先修投影与选择，避免继续堆资料。
2. **条件的语义归属**：最新 Coda 段把“工作区有三种成员类型”写成创建操作的前提，这是分类背景与执行条件混淆。需要固定证据输入的人审反例，不能只校验原文出现过相同词句。
3. **缺证时生成短局部报告**：硬件报告重复缺口、含未引文的品类背景；取消低证据场景的机械长篇，逐条标注可交付事实与待补内容。
4. **检索与阅读入口**：定位中英文 sparse 均无候选的原因，再评估融合和精排收益；报告页缩短任务标题、默认收起原文证据，直接展示分析。扩独立未曝光的回答/澄清/拒答评测后再谈 RAGAS 或微调。

HTTP Qdrant、Temporal、Redis 多 worker、实机 Postgres RLS 均未在本轮验收。健康检查仍有 Temporal 切流策略错误；当前 Memory 模式仅能恢复报告相关投影，不能作为完整生产项目数据库。

## 首轮已执行的基线

源码 manifest SHA：`2b23c06aa06b3f5f05f6f67a6b8b856f6d13bbe4f261ab35e82cc997d130ee11`。该版本后端 3844 通过、1 跳过；前端 279 通过、构建通过；临时 OpenAPI 生成对比一致，实际配置凭据扫描无命中。脱敏基线保存在 [2026-10-15-acceptance-baseline.json](2026-10-15-acceptance-baseline.json)。

- 独立 8 题中的 6 道答案题：sparse 的 top-1/top-3 为 0/6，E5 hybrid 和加 BGE 精排均为 6/6。拒答与澄清行为、RAGAS 尚未运行；这个已曝光小集不能证明泛化准确率，精排也未在本集证明增益。
- 四产品流程：`completed_with_blockers`，11 个来源，四家 Analyst 均实际调用并产生有效结构化结果；正文仅 9/24 操作格已审核。发现可选访问模式误作普遍前提、权限配置误作实际编辑，以及容量投影造成假缺口和重复重做。
- 硬件流程：在 `collect_qa` 正确阻断，没有生成报告。已抓取的规格被软件规则丢弃，用户研究仅有合成模板；不能视作验收通过。
- 两组流程合计记录 51 次实际 provider transport。临时 Qdrant 清理路径别名造成脚本退出异常，知识库统计又未使用实际 project 范围；保存的原始失败产物保持原样，待修脚本后用新目录复验。

当前补丁的局部测试、规格及质量审查记录单独封存；只有最终同一源码的全量与真实流程复验后，才更新交付结论。

## 第二轮结果：仍未通过交付

运行前源码 manifest SHA：`59a9e51f1daca76479e1c0cdb7243109df59d9a75b272031a5412b1de5d796ca`（878 个源码、测试、配置与评测文件）。该版后端 **3967 通过、1 跳过**，前端 **279 通过、构建通过**，OpenAPI JSON 与生成类型字节一致。实际配置凭据扫描 1102 个文本文件及 4 个构建文件，无命中；这不覆盖 Git 历史或所有外部存储。原始结果保存在 `/tmp/plan_a_acceptance_v2`。

| 验收项 | 实际结果 | 判断 |
| --- | --- | --- |
| 四产品真实 API 流程 | 11 源；首次正文 4221 字符，补证后只剩 1695 字符、1/24 个已审核操作格；`completed_with_blockers` | 不交付。补证先撤旧证据，正式 facts 从 204 降至 159，新增 0；随后全链重跑且尾部预算不足，覆盖既有审核内容 |
| Steam Deck 标准深度、多维流程 | Analyst、Comparator、Reflector、Writer 均有真实调用；部分规格已接纳；机会假设段格式重试仍失败，最终 `failed`、0 正文 | 不交付。保留 LCD、用户研究等真实缺口，修写作结构失败路径 |
| 实际应用项目 RAG | 11 个全文文档均 ready；中英文查询均调用本机 E5 与 BGE，索引和查询版本一致；所有命中属于当前工作区和项目 | 生产入口接线已验证。两组查询均 dense=12、sparse=0、reranked=8，尚未证明关键词融合收益或回答准确率 |
| 独立人审集检索 | 22 源、8 题；6 道答案题 sparse 为 0/6，hybrid 和加精排均为 6/6；网络和外部模型调用均为 0 | 仅小集检索证明；已曝光，不能视为盲测或 RAG 整体合格 |
| 前端闭环 | 中文技术详情正常；合法项目范围检索及无效项目阻断；人工 v2 重启恢复；浏览器 Markdown 下载落盘且与后端文件 SHA 一致 | 这些交互已验证；下载样例是旧 DEMO，不用于证明真实报告质量 |

四产品实际应用任务为 `run-1ffdeb31d4820f3f3cae3cd4c7f3aed7`，项目为 `project-24076287ed312e2e`。本轮记录四产品 40 次、硬件 22 次明确 provider transport；另有分别 19、12 个搜索包装 span 没有 transport 字段，不能把未知计为 0，也不能直接当成额外付费调用。四产品预算计入 187967/200000 token，硬件 146759/200000 token；配置单价估算仍不是账单。

前端浏览器下载落盘证据为 `/tmp/plan_a_browser_download_saved_proof.json`；项目检索和本机精排证据为 `/tmp/plan_a_acceptance_v2/api-operations/rag-api-proof.json`。上述临时路径供本机复核，不能当成 GitHub 随仓交付附件。

健康检查 HTTP 200，但聚合状态仍为 `error`：Temporal 切流策略检查未满足；本机实际运行的是 LangGraph。未执行实机 Postgres RLS（缺少测试数据库，1 项跳过），HTTP Qdrant、Temporal、Redis 多 worker 也未验收。不能宣称全部服务健康或生产集群已通过。

## 第三轮：流程可生成，完整交付仍未通过

运行前后源码 SHA 一致：`3557c1e23e4f9b1ca97f1f2fefad288e7b3f98ed503a8fc2b47a1d521d9157d1`，880 文件。后端 **3997 通过、1 跳过**；前端 **279 通过、55 文件、构建通过**；OpenAPI 与类型一致，diff check 通过；1144 个文本/构建/本轮产物的实际凭据字面扫描无命中。规格与质量审查均通过，原历史报告替代一手来源的 P1 修复及反例保留。结构化记录见 [第三轮验收摘要](2026-10-15-acceptance-v3.json)。

- **四产品真实 API**：空项目 `project-acceptance-2637264dcceb4cd9`，任务 `run-d5fabe5c920583a0938ff62e80a673fa`。11 源，5780 字符报告，16/24 操作格含模型已审核观察；四家 Analyst 与每家写作/审核都有真实执行。29 次明确 transport，10 个搜索包装 span 的 transport 未知；预算计入 135265 token。任务终态 `completed`，但仍有 31 个 warning，同操作与完整条件未全部补齐，业务完整交付未通过。本轮没有 collector redo，不能把预算下降全部归因于 no-op 修复；该分支本轮以保存来源重放、真实 SQLite canonical 对照和 AI 图测试验证。
- **硬件标准深度、多维流程**：`completed_with_blockers`，21105 字符报告（core 11578），2 源，32 次明确 transport、18 个包装 span 未知，预算计入 185221 token。机会假设结构不再令全任务中断，但 LCD/真实用户研究等缺口仍阻断。验收导出的整段 Markdown 被保守脱敏规则隐藏，10 条写作生成段仍可读；全文实质复核须与生成成功分开记录。
- **实际项目 RAG**：11 个全文文档均 ready，中英文两次查询真实调用本机 E5 与 BGE，索引/查询版本相同，命中均属于本项目。两次均 dense=12、sparse=0、reranked=8，未降级；没有外部模型查询。离线 22 源/8 题结果维持 sparse 答案题 0/6、hybrid 与精排 6/6，不能视为回答准确率或精排增益证明。
- **实读发现的新缺陷**：Coda 原文与正文均否定管理访问权限，但 `claim-4207e655a1bc6d3316ea` 的绑定把 `not manage access` 标为 `effect=allowed`，模型审核仍给 supported。正文有来源不代表结构绑定正确；需要修否定短语解析及主张与 effect 的确定性矛盾检查，保留本轮记录，后续补丁另列版本。

实际服务重启还确认：当前 Memory enterprise store 的未关联任务空项目不持久化；本机 journal 恢复的是报告关联投影，不能当成完整项目数据库。生产部署边界与上文保持一致。

硬件后续离线读回：用保存的最终通过段及原确定性机会假设重放组装，重建出的全文/核心字符数、全部 section 索引和 audit 正文与保存记录相符；原全文哈希没有独立保留，因此不能声称字节级认证。实读确认报告重复缺证说明较多，LCD 定位首段仍写了没有引文的“品类常识”叙述；格式校验通过不等于事实交付合格，仍保留阻断。

## 数据与复验方法（可复现命令）

独立数据为 `eval/product-research-independent-v1-{corpus,queries,labels}.jsonl`。8 题由用户在 `request_user_input_async_call_10e1726901774af98094b651290c4101` 明确认可，原始审核时间、输入 SHA 和边界记录保存在同前缀的 manifest。新增 6 个来源与原 `product-research-reviewed-v2-corpus.jsonl` 的 16 个来源合并为 22 源；未改旧人审集。新题的 query、label 文件与审核输入逐字节一致。

新增来源是 AI 编写摘要加短官方引文，并非连续官方原文；抓取时“pending review”的历史说明由后续审核记录补充。题目已被实现者看到，不能称为盲测。6 条 answer 的检索指标与 1 条 insufficient、1 条 clarify 的检索噪声分别报告。拒答与澄清行为没有执行回答模型，因此仍为 `not_run`；没有独立回答裁判的 RAGAS 也保持 `not_run`。

检索比较使用相同 22 源、原问题、广泛产品范围与 top-3 排名中的 top-1/top-3，分别执行 sparse、E5 hybrid、E5 hybrid 加 BGE 精排。广泛范围只取消 competitor 预过滤；工作区、项目、市场、日期、source role 保持固定。全球题有 13 个合格候选；大陆价格题仍按大陆市场隔离。每题输出实际过滤配置、合格来源数、top-k 是否已覆盖全部候选。单次初始化复用已有冻结 E5/BGE 权重，warmup 推理另外计数；脚本禁网并记录网络尝试数与外部模型调用数，不下载其他模型。

在仓库根目录执行（`--run`/`--live` 仅在同源码全量绿且冻结后添加）：

```bash
PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m scripts.eval_independent_retrieval \
  --local-profile docs/optimization/2026-10-14-local-rag-profile.env.example \
  --output /tmp/plan_a_final_acceptance/independent-retrieval.json --run

PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m scripts.eval_live_products \
  --cases eval/operation-comparison-v1.jsonl --case operations-four-products \
  --local-profile docs/optimization/2026-10-14-local-rag-profile.env.example \
  --output /tmp/plan_a_final_acceptance/operations --timeout 1800 --live

PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m scripts.eval_live_products \
  --cases eval/hardware-comparison-v1.jsonl --case steam-deck-hardware-multidimension \
  --local-profile docs/optimization/2026-10-14-local-rag-profile.env.example \
  --output /tmp/plan_a_final_acceptance/hardware --timeout 1800 --live
```

真实流程沿用 `get_settings()` 的既有凭据和模型，只输出允许的模型名称、provider 与数值预算；不输出 settings 或凭据。固定每任务 200000 token、60 calls、max retries 0。`--live` 必须明确提供本地语义 profile，每个 case 使用空的临时 SQLite 和 Qdrant local，不预置产品答案。冷启动检索可能为零命中，摘要如实记录 warm-start 尝试/命中/接纳、全文索引状态与 query/index 模型版本。权重缺失拒绝本轮正式语义验收，hash 不冒充语义模型。

每个真实 case 保存脱敏 run JSON、events JSON、report Markdown 与 summary JSON。summary 区分 `llm_transport_attempts`、`llm_phase`、`llm_execution_status` 和模块的 `llm/fallback/skipped/cache`；span 为 ok 不代表实际模型调用或有效结构产物。provider usage 缺失使用 null/unknown；费用范围来自配置单价与 trace token 估算及缓存极值，不是实际账单上下界，原生搜索工具费用未知。预算 checkpoint 单独保留。

最终人工验收须逐项阅读来源、条件、矩阵、主张、正文引用、QA 和 blocker，不能将终态、机械引用合法或小集召回视作语义准确率。Coda 缺源不得强放赢家；Steam Deck 不得保证所有游戏达到续航上限，不得编造大陆含税价格或实测表现。

待补正式结果：统一 source manifest SHA、全后端和前端测试/build、OpenAPI 临时生成对比、diff check、只输出路径与计数的秘密扫描、本机三模式比较和两组报告的实质审查结论。源码 manifest 使用 `/tmp/plan_a_remediation_source_manifest.py`，包含源码/测试/配置/eval 的未提交内容，运行前后校验一致；不能以 HEAD 代替。

边界：本机 LangGraph、SQLite 和 Qdrant local 的验证不覆盖 HTTP Qdrant、Temporal、Redis 多 worker 或实机 Postgres RLS；本机 Memory journal 仅恢复报告父子版本与审核投影。没有可靠语义核验的新人工措辞保守保留 draft/pending，不作可发布保证。
