# Collector 逐题交付合同实施计划

> For agentic workers: 使用 subagent-driven-development，实施后先 SPEC 再 QUALITY；单个实现任务串行，独立只读诊断可并行。

**Goal:** 每个问题保留原始请求、来源结构证据、模型提案、验证提取、准入及实际交付的关联和明确缺口；恢复可验证正文与关键结构资料，避免静默丢失。

**Architecture:** 沿用用户已确认的逐题合同、分阶段状态、缺口路由和效果验收四点。推荐在现有抓取／准入链增量接线：HTML 仍在内存时恢复真实披露块，源结构原句通过原有验证器，服务器按原始ID串联交付。仅加强提示词不足以防止静默丢失；重建一套独立采集 Agent 会重复现有预算和来源控制，因此不采用。模型自报 candidate 不能关闭机械缺口，也不授予事实资格。

**Tech Stack:** 现有Python、lxml、pytest/Pydantic、已缓存本机E5、现有DeepSeek；不加依赖、不下载、不训练、不执行Docker。

## 授权、基线与不变量

- 用户本轮已明确批准实施上述通用功能、离线后四家真实测试，沿用当前隔离工作区及 codex/pastoral-desktop，无需再次请求同一方案批准。
- 起点2bb07363b795690dbab3c1715690e395e823ab6c；后端5664通过／1跳过，上轮四组40调用／148957 token，正文3正确／1错误／4遗漏，0/4报告合格。
- 八题及三条轨迹已曝光，仅作开发回归；参考答案、审核节选、期望类别不能进入生产运行输入。
- 四组各一次，24 calls／80000 token／输出2048／retry0；沿用实际CLI与已有E5，不提高Writer 14000 bytes／八事实或1600条件组上限，不删除条件换通过。
- 不输出秘密配置。所有旧产物运行前哈希，新产物使用collector-question-delivery-2026-10-18新目录。

## 根因调查结论

1. FAQ metadata与正文来自不同处理结果，HTTP200且正文长并不代表结构完整；旧归档无原HTML，不能断言真实答案在SSR还是动态加载。
2. Dropbox删除链接规则停在model-proposed→verified-fields，原因是尾部Help标题缺失令section未闭合、全页条件回退超6条；不是canonical无故丢失。条件门禁仍须保留。
3. 旧Dropbox normalized→SQLite canonical→snapshot离线重封完全一致，无不同原句去重丢失。此处增加守恒核对及失败状态，不制造无证据的数据库修复。
4. Cloudflare价格行已在模型输入却未被提出；既有原文验证器可接受完整原行。需加入源结构驱动的候选恢复，不把是否得到关键表格行完全交给模型自由选句。

## Task 1：结构完整抓取

Files: tools/fetch_page.py；tools/evidence_fetch.py；必要的tools/advanced_fetch.py、research/capture/webfetch_adapter.py；新 tests/unit/test_collector_capture_completeness.py。

- [x] RED：长正文的第二个折叠FAQ被清洗遗漏；真实关联panel应恢复完整问题＋答案，只有标题／空region保持缺口，不能造答案。
- [x] 使用同一内容根（main/article或可靠body）处理正文和标题；正文外导航／页脚不能制造未知业务边界。按details/summary或唯一有效aria-controls关系恢复真实披露原文，拒绝重复ID、隐藏控件、disabled、脚本／模板、跨根引用和无关隐藏报价切换。
- [x] 保留完整性诊断与恢复来源，正文hash重算。basic完整性有疑点时最多一次现有advanced browser升级；受原有allow_advanced及次数预算控制，浏览器缺失／失败保留partial，而非称完整。
- [x] metadata经EvidenceFetchResult→CapturedPage保留；advanced路径也不能用inner_text覆盖完整rendered结构。匿名测试须走真实HTTP适配器／capture入口，无外部网络。
- [x] 原始材料资格与结构完整性分开：无关空FAQ不拒绝整页有效正文。跨渲染只用可核验的稳定结构身份消缺；原生details无稳定身份时保留缺口，DOM路径和同文问题不能证明恢复。
- [x] SPEC→QUALITY通过后冻结本任务；不放松来源、SSRF、认证／403、标题歧义及条件门禁。

## Task 2：源结构恢复与逐题交付守恒

Files: 新research/question_delivery.py、research/extraction/structured_evidence.py；必要的extraction/semantic.py、pipeline.py、question_evidence.py、agents/collectors/logic.py、evidence/admission.py；新unit/integration测试。

- [x] RED：显式计费问题的完整同服务表格行在body，模型忽略仍应经原验证器形成原文观察；所有表头、单位、脚注、套餐／模式限制必须保留，错服务／缺脚注／不完整行仍拒绝。不创建采购价格或计算账单。
- [x] 源结构恢复只取当前页、当前问题选窗的完整表格行及已恢复披露原句，经semantic原文／条件验证及admission同一路径。现有语义补充继续工作；未知普通自然语言需求仍标未核实，不借词法相似度证明完整。
- [x] 为semantic每条模型提案记录稳定quote hash、page/hash、verified字段ID或明确拒因；proposed不等于extracted。兼容现有semantic_extraction调用，诊断不能改变原门禁结果。
- [x] 定义版本化逐题交付记录：question_id／原问、product／dimension、capture完整性、源结构anchor(quote+位置/hash)、提案／verified字段／accepted item IDs、normalized source IDs、缺口及next_action。请求只作关联，不变成事实；model candidate不能关掉capture／extraction／admission／handoff缺口。
- [x] 缺口路由：原文已有而字段缺先局部恢复／补提取；正文缺使用已有受控抓取升级；accepted未normalized记录conversion_missing并保留ID，不静默成功。预算／容量／拒绝各有原因，失败不无限重试。
- [x] 真实Collector出口写入来源metadata及clean_research_pipeline trace；提供服务器replay函数按snapshot.fact.evidence_item_ids和实际各Agent consumption核对：已入快照、实际发送、因容量未发分别记录。无匹配ID／错产品／跨快照／伪造metadata不能算ready，不新增公共API DTO。
- [x] 持久化位置收敛为既有Collector trace.full_output中的瘦capsule，来源metadata仅放轻量关联，不复制整页正文。现有seal读canonical的位置重放原提取/准入及normalized守恒；没有可核验canonical正文就partial。各Agent的已验证消费只证明view_selected；Writer另以实际LLM span、原prompt/hash及transport次数证明dispatch，其他Agent的发送状态允许unverified。
- [x] 离线集成走fetch→提取→admission→RawSource→canonical→seal→各阶段视图，证明关键原句与前提实际存在；fake模型仅验证接口，不当语义准确率。原存储链已正确的反例只加守恒检查，不重构数据库。
- [x] SPEC→QUALITY通过后冻结；完整上下文不足须显式partial，不能宣称任意问题都已理解或所有证据必全选。

## Task 2B：同页知识库来源升级

离线调查证明：canonical 的 normalized 注解不是当前事实权威。当轮快照读取 current RawSource，两个 accepted items 已进入快照；不为旧注解新增存储版本体系。另已真实复现：batch 中既有同页 RAG 来源使当前合格观察因 source_capacity 或 duplicate_source 不能转换，需在真实复验前修复。

- [x] 先 RED：已有同产品、维度和 URL 的 RAG 来源，来源名额已满，当前合格原文观察仍应升级该来源，而非转换为 0。
- [x] 复用实际来源替换入口，升级同页的现有名额，不提高来源预算；不同产品/维度/URL不得合并，不同正文不得混入旧事实。升级仍通过当前 capture/admission/canonical 来源资格。
- [x] 真实 Collector join、规范入库、snapshot 和逐题 replay 核验新增观察及完整前提，不只测试独立转换函数。拒绝的提案不升级来源，保留明确缺口。
- [x] SPEC→QUALITY 后进入最终门禁，最终冻结包含此项的累计代码版本。

## Task 3：真实复验与交付

- [x] 全后端、变更范围Ruff E9/F、OpenAPI字节对比、diff、实际凭据扫描；全库既存4项F401单列，不改无关测试。进程测试需ps权限。
- [x] 冻结所有backend Python、入口/helper、登记、参考及每组manifest。四组固定官方来源阶段各一次，记录调用／token／失败／capture hash，不替换官方内容、不静默重跑。
- [x] 按每题检查关键证据经过captured→proposed→verified→accepted→normalized→snapshot→实际Agent视图，并独立实读正文、回答和引用。单列Collector交付与报告质量，未进入Writer不靠receipt文字证明已交付。
- [x] 更新README／Agent执行／交付JSON，保留旧失败。新报告未获用户验收，reward=null、training_ready=false。

Git交付：沿用用户授权提交并推送当前分支；提交和远端核验结果在任务交付消息中报告，文档不嵌入自身提交哈希。

## 执行记录

- Task 1：2026-10-19 v4 完成 SPEC→QUALITY；127 项定向测试，两审各自重跑。修复只有标题误报完整、同文问题错消缺、局部缺口误拒整页、隐藏根/控件、无稳定ID的DOM移位和后续恢复吞掉先前引文。冻结 `670f774d517eea6b9269b3d43eb011c335a701a27c22a9d2fdd05dc18aa62f6c`，268 份旧产物保持不变。
- Task 2：v2 完成 SPEC→QUALITY；49 项新增用例，617 项相关测试，两审各自复跑。修复跨题借用关联及成对伪造 producer ID。冻结 `898715d62a7834a3d5ba2ec87d64720fd1a81f835b6808009857ba516ab2f429`。同正文 SQLite 实证确认 canonical 旧注解不构成当前事实权威，不新增存储修订机制。此时外部项目模型调用为 0。
- Task 2B：v2 完成 SPEC→QUALITY，49 项新增用例、310 项相关测试，两审独立复跑。覆盖真实 RAG 命中→当前采集→SQLite→RunJournal→实际 join 双顺序、快照及视图；31 天过期/未来 canonical 拒绝复用，29 天有效/默认邮箱脱敏正常恢复，瘦凭据实测 1019 bytes。冻结 `98ea1e070c32c65f1c9179eee75b9991167ee2190f4568b4d11228b8b77c812d`，前序其余文件及旧268份产物未变。根代理另独立复跑本轮147项新增测试全部通过；全后端和累计审查开始，此时外部项目模型调用仍为0。
- 累计审查通过。脱敏后的逐题胶囊保守 partial 是已知审计限制，实际两条正文事实仍进入 snapshot；不关闭脱敏、不将其冒充 ready。全后端首轮5810通过/1失败/1跳过，唯一失败是旧事件循环测试仍拦截旧解析入口；仅适配测试至当前 `_capture_html`，保留响应顺序断言。定向163项通过，审查者另独立16项通过；再次完整回归进行中。

- 最终工程门禁：后端5811通过/1跳过/212 warnings（167.09秒），变更范围Ruff E9/F、diff和OpenAPI字节对比通过。全库4项F401均在未改动旧测试；前端未变不重跑。累计集成审查及解析入口测试补充审查均通过。生产包SHA `9afef23c3ae0f92e2614d5f15371489b865eb100202e601066f863b2bc317fd4`；四组manifest及全Python/相关参考/helper冻结后开始真实运行。

- 真实四组各首次运行完成，无重跑：30 transport/85808 token，三组核心下游执行、Dropbox因无可准入来源阻断。正文3正确/0错误/5遗漏；最终记录2正确/0错误/6遗漏；0/4完整可交付。逐题缺口和各层事实分开记录在2026-10-19交付文档及JSON，未改标签、未训练。运行前后707份冻结文件及268旧产物相同。
