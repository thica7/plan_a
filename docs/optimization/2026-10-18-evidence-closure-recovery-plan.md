# 证据闭包与服务选窗恢复计划

> 用户已确认继续上一轮列出的下一步，沿用现有隔离工作树 `codex/pastoral-desktop`。按 subagent-driven-development / TDD 执行；任务之间不重复请求确认，规格和质量分别审查。保留上一轮失败，不训练模型、不下载权重、不执行 Docker。

**Goal:** 修复真实产物暴露的收据膨胀、完整例外组误弃与计费子服务误选，验证完整证据进入 Writer 及实际发表的回答。

**Architecture:** 在来源处去除重复证明文本，保持当前字节和事实条数上限；将完整条件组与后续操作说明分开。验证有序标题的实际位置，选窗使用经验证的来源章节与问题子服务，不奖励无关规则数量。跨页依赖只对同产品、同事件/对象及兼容条件的当前合格原文进行显式检查，并同时保留双方身份。逐题审核只使用已发表主张，不以审核理由补足答案。

**Tech Stack:** 现有 Python / pytest / Pydantic、已有本机 E5、既有 DeepSeek 配置；无训练和新基础设施。

## 基线与不变量

- 起点为已推送 `c2eebbd2140ef392e684be680a2700aebba64328`，生产 Python SHA 为 `9d12c3173cdb1df2b313c8a023022f243b2b02c243b52bcd702487ad6e3f2488`。
- 上轮5537通过／1跳过，真实正文3正确／3错误／2遗漏，0/4报告达标；它是已曝光开发回归，不是盲测。
- 147个既有产物文件在修改前单独哈希，reviewed八题及三条轨迹标签保持不变；秘密配置不输出。
- `EXCEPTION_CLOSURE_MAX_BYTES=14000`、总八条事实、完整来源组1600字符和既有调用预算不抬高；完整块超限拒绝，绝不截去限制。

## 任务1：恢复真实例外的容量与完整性

Files: `backend/packages/research/evidence/source_exceptions.py`；必要的 `normalization.py`、`agents/writer/question_retrieval.py`、`evidence/report_claims.py`；新 `backend/tests/unit/test_exception_recovery.py`。

- [x] RED：匿名同一抓取、同事件、同完整条件被十个准入项重复承载，归一后仅保留一份逻辑收据及有效来源；顺序改变输出稳定。完整原文不裁剪，当前检索预算可装入关键事实。
- [x] 最小去重按 kind／完整quote／events／branches／完整source_scope；原始观察仍保留，选择可重放的完整原句origin。不同角色、套餐、事件和抓取不合并；伪造/缺失origin仍拒绝。
- [x] RED：三项except列表及解释之后紧跟同动作 `To unshare a folder:`；完整例外组保留三项，不吞后续操作引导。嵌套分支冒号、未知未完成条件和超1600组不被裁成可用。
- [x] 检查规范化→快照→问题检索→Writer compact→主张/答案QA的实际字节和依赖；在完整当前视图中，同事件/对象跨官方页面的具体例外不能被一般句绕过。跨产品/角色/对象/操作和不兼容条件反例不串配；跨页条件需双方事实和出处。
- [x] 用上轮完整capture离线重新提取和准入，验证SSO不再因重复收据超预算、Dropbox三例外完整；不改旧快照。新匿名测试先RED再GREEN，SPEC→QUALITY后冻结。

## 任务2：重复标题与产品子服务选窗

Files: 必要的 `backend/packages/tools/fetch_page.py`、 `research/capture/official.py` / `infrastructure/source_cache.py`、`research/extraction/semantic.py`；新 `backend/tests/unit/test_service_window_recovery.py`。

- [x] RED：同名Footnotes在正文不同服务重复出现；按捕获元数据顺序、层级与前后可靠锚点验证实际位置，不能误认所有正文同名行都是标题；缺失/伪造/顺序错误元数据不能伪造章节。
- [x] RED：产品A的Compute／Standard与Storage的Standard storage同时出现，查询明确Compute，后者不能凭更多费用规则夺窗。只使用原文完整连续块，保留父级条件与全部表头/脚注；无可靠服务归属时明确缺口。
- [x] 选窗以已验证、问题中显式出现的完整服务标题及祖先路径为范围依据；不添加产品名专用字典。相关性相同后不以更多无关规则为正向奖励。
- [x] 原行只遗漏唯一可恢复的项目符号时可恢复；不能接受不完整实质句、不同主体或多义重复。完整条件组按真实标题边界收束。
- [x] 使用本次保存的Cloudflare完整正文及可验证标题离线重放：Workers Standard原行与最低月费进入实际选窗，按原文提取/准入至快照；不由本月请求数推算账单。SPEC→QUALITY后冻结。

## 任务3：逐题发表、拒答与计费缺项

Files: 按离线追踪的实际根因局部修改 `agents/writer/answer_coverage.py`、`answer_resolution.py`、`dimension_writer.py`、`price_answers.py` 和必要的 `research/evidence/report_claims.py`；新 `backend/tests/unit/test_answer_publication_recovery.py`。

- [x] 先只读追踪003未发表访客两限制、007已有作用域仍拒答及008丢Paid/Standard：区分选证、写作、主张拒绝、覆盖审核，不预设增加模型调用能解决。
- [x] RED覆盖“升级可获得更多权限”不等于已发表当前限制、审核理由引用不存在的结论、有效域范围证据被写成无证、已声明模式被要求再次澄清；保留真正资料不足和真实歧义的正确路径。
- [x] 使用实际发表主张/明确来源约束核对各子问；缺证时只陈述当前准入/选证/发表范围，不能用角色页证明未采价格。若需要新的结构合同，先写入本计划的具体接口和反例再实施。
- [x] 完整当前计费规则进入后，CPU缺项从适用肯定规则识别；同列套餐/模式的名称不猜成别的SKU。保留日期、税费、市场及完整用量边界，禁止虚构金额、税率和汇率。
- [x] 只在上述恢复后的真实离线重放通过后进入模型复验；不能以减少错误但全部拒答宣称报告合格。

## 任务4：冻结复验与交付

- [x] 全后端、Ruff E9/F、OpenAPI字节对比、diff check及实际配置凭据字面扫描；前端未变则不冒称新验收。
- [x] 新目录 `data/artifacts/evidence-recovery-2026-10-18/`，冻结生产、实际runner/helpers、登记和每组manifest；四组各一次，24 calls／80000 token／输出2048／retry0；使用已有本机E5，不下载。
- [x] 独立实读正文和回答记录、全部条件及逐条引用；单列生成成功、内容正确、报告完整和用户验收。未知usage如实记录，失败原样保存，不将已曝光题当盲测。
- [x] 更新README、Agent执行、交付和结构化结果；按既有授权提交并推送当前分支，结果以HEAD／远端SHA和干净工作树实际核对为准，不预写未知commit。新报告未获用户验收前reward=null、training_ready=false。

### 已确认的最小跨页合同

沿用 `ReportClaim.fact_ids/source_ids`，不新增公共DTO。`verified_exception_binding(claim, content)`（最终名称由实施确定）只在一个主事实与兼容具体例外、完整文本及双方ID/source绑定均验证后，为 `feature_claim_multiple_observations` 提供有限豁免。其它多事实拼接、跨主体/动作/对象/套餐、假来源或漏条件仍拒绝；当前快照及 `allowed_fact_ids` 继续优先校验。

### 首轮诊断纠正

捕获侧的 basic `_document_headings` 与 advanced `extract_headings` 并未对标题数组去重，不据此改掉捕获实现。真实问题是正文同名行比元数据多，当前验证器将任意一处歧义升级为整表无效；后续以实际顺序和位置验证为依据。003直接限制已在Writer草稿，因非六类操作的正常中文限制被 `operation_binding_required` 删除，应先修该准入分支，再核对覆盖合同。

### 只读诊断后确认的任务2／3合同

- 标题定位采用整体有序候选域的前后约束；残余歧义或矛盾保持拒绝。缺失标题须保留层级和可能区间，不能把未知同级边界当不存在。服务选择须先于短页整页返回，标题为完整连续词组并取最具体显式名称；适用父级引言保留原连续区间。
- 优先沿用现有 literal 非操作合同：提供来自当前已送事实的完整原句候选，不放行任意无绑定中文转述，不新增翻译DTO。中文结论与完整英文引文分开，最终审核仍核对条件。
- 覆盖初审只看实际已发表主张；复核显式接收服务器拼接的 proposed_answer 与原文，原文和 reason 不能补充正文。作用域的受限定推理允许使用题设的两个不同资源和无其它授权，不能要求官网逐字出现用户域名。
- source_exception_bindings 只公开当前合格事实推导的候选pair；parser、selection、report guard及最终QA均重放双方完整来源与条件，默认单事实要求继续。普通角色页不能证明整个采集集合没有价格；缺价答复陈述本次已准入证据的不足。
- 价格请求已知套餐／模式先与同一适用源规则的完整名称匹配，保留题设值但不将其作为事实；CPU缺项来自实际准入肯定规则，不用参考答案或品牌常识补齐。

### 任务1首轮SPEC结果：未通过（保留记录）

181项定点通过不等于真实链路通过。独立重放确认：等价specific证人被逐个强制引用；答案QA把真实主张binding丢成仅text；claimed-domain父条件因包含内嵌SSO子组被整体误分类。按这三项写新的匿名RED并修复；Dropbox容量下未送达的独立link仍需记录partial，不能用“已在完整capture”冒充“已进入Writer”。

### 有限认证合同的架构收紧

QUALITY的两个反例及SPEC复审再次表明，仅匹配认证关键词／首个unless不能证明完整来源组。收敛为完整有限语法：所有header、实质句和分支必须被识别，未知余文要求完整原文进入正常语义审核，否则unresolved。该守卫不宣称通用自然语言蕴含证明；不引入厂商名或审核题号专例。保守未发表属于缺口，不算答对。

### 任务1最终范围与验证

24项新增匿名测试，相关191项通过；独立SPEC及QUALITY最终各复跑88项通过。SPEC/QUALITY发现的失败日志全部保留。真实旧snapshot的SSO完整双绑定通过，漏绑定仍拒；未脱敏capture新提取／准入／seal后AUTH818为5688B，已发送且检索闭包完整。delete-member原捕获导出已脱敏，不能声称exact replay。Dropbox中文copy/link守卫通过，但surviving link与完整规则origin未全入当前容量，整体仍partial；不提高预算或把收据文本当作已验证origin。

### 任务2审查反馈与实际回归

SPEC发现两种整页回退：缺失peer使已选服务不闭合、或仅一项服务含费用时，候选门槛跳过服务约束。改为保留结构peer后，根侧真实roles页重放又发现同brief中的账单问题会误清空无计费规则的角色页。入口须先确认当前页面具有计费规则信号，再以所有结构peer约束选窗；不能要求两个peer都有费用或把未知peer从候选删掉。旧测试仅将歧义的Usage题改为完整Usage service标题，保留其它原文及断言。

### 任务2最终验证

21项新匿名测试，相关175通过；独立SPEC／QUALITY各复跑79通过。后续审查发现的missing首child父引言污染已写RED并修，未知引言拒绝提取。真实两页重放：Workers连续[0,5714]；原完整Standard行＋最低费句的假设诊断产生2字段、2准入、完整表头＋4脚注、快照6事实，不能冒充新模型输出。旧6条模型quote仍0；roles原5条模型quote保持5字段、窗口[0,11952]。147旧文件未变。

### 任务3操作绑定的必要单点接线

`operations.bound_operation_observation`原合同强制单fact／单source，合法例外pair即使保留原操作binding仍在selection／QA被拒。仅这一检查点可用`verified_exception_binding`允许当前合格两事实，原操作候选逐字段校验、binding.fact_id身份与精确来源集合继续；不同主体／角色／套餐、未发送或漏条件仍拒绝，不放行无binding的新六操作断言。该文件列入冻结与审查。

### 任务3首轮SPEC：未通过

30项新测试及298定点通过后，独立SPEC仍复现：optional literal候选挤出完整fact、未知usage model借用CPU规则、非表CPU句对非正费用／按请求收费缺少同等约束。实际缺项答复入口仍insufficient但missing_fields不准确，必须修。旧`test_answer_semantic_review`初审读facts的断言与新“只看published”合同冲突，允许只改初审无facts断言，保留复审完整原文及未发表例外的所有断言。首版离线冻结单独封存，不作真实模型验收。

### 任务3第二轮SPEC：未通过

v2的39项新增及独立165项通过后，unknown-scope守卫仍仅匹配单数plan/tier；合格原文premium plans／tiers会误用于已知其它套餐的CPU缺项。按同一适用范围合同补复数RED并修；保留v2冻结及失败，不启动外部模型。共享resource-scope规则已接Writer、主张审核、覆盖初审及答案复审，接线通过不能冒充真实语义合格。

### 任务3首轮QUALITY：未通过

v3 SPEC124项通过后，QUALITY在真实缺项入口复现同fact已知Free前句会掩盖CPU句中的未知premium plans。需按CPU规则本句校验显式范围，不借另一句已知名。新增匿名RED并保留v3，修后重新SPEC→QUALITY。

### 全量预检的范围修订

预检5619通过、2失败、1跳过：一项是沙箱禁止ps，最终在允许自有测试进程检查的环境重跑；另一项旧选窗题仅说Usage plan，而已审合同要求显式完整Usage billing标题。仅在题设增加Under Usage billing，原文、相同词的晚到能力干扰及全部断言保持，独立复核后再跑全量。Ruff全backend有三个未改旧测试文件的四项F401，经HEAD字节对比确认既存；packages/scripts及本轮所有变更测试通过，不把局部通过写成全库Ruff通过。

### 任务3第三轮SPEC：未通过及范围校验收紧

v4句级检查仍只验证该轴存在任一已知名称，复合句的未知premium plans／legacy usage models仍能借已知前置分句通过。收敛为每一处显式scope mention均须落入同一命名语法的完整匹配span，任一未解析范围保守拒绝；不通过按逗号／while临时切句解决。保持无局部scope但适用父级正控，离线重放实际Workers Paid/Standard避免过拒。未解决的Free名称与否定词歧义继续记录，不把换正控称修复。

### 结构化计费表的有限适用合同

来源的其它套餐背景可能含未命名usage model或base plan，不能一律当当前CPU行的适用范围。表格仅当完整header→当前row的CPU单元格为正time费率、row模式匹配题设、同源完整命名且匹配的plan+mode适用原句存在时识别依赖；实际单元格／row和所用原句的每一scope mention仍须解析，不能从背景借出CPU规则。背景、条件和脚注不删除，全部继续正常QA；错row、缺适用原句和未知局部范围拒绝。这是表格绑定合同，不是通用自然语言条件蕴含。

### 任务3第二轮QUALITY：未通过

v5 scope span及真实表格重放通过后，QUALITY证明只共现plan+mode名称仍不能证明适用：明确“do not have access”会错误补CPU缺项。表格依赖需完整原句表达有限肯定适用关系，所有未解析否定／unless／例外／描述性提及保持拒绝；仅支持来源现有的完整正向模式，命名仍由同一source匹配捕获，不加品牌词典，不以absence-of-not当肯定。背景与脚注不删，完整实际原句正控保留，旧失败全部封存。

### 任务3最终限定验证

v6新增匿名总82，相关四文件162通过，最终SPEC及QUALITY各独立162通过，49项冻结SHA及147旧产物未变。原四阶段fake链仅证明接线／拒绝，不算语义准确率。真实旧Standard表离线重放保留Paid／Standard／USD／monthly及CPU、市场、税费、完整用量缺项，仍insufficient；不虚构账单。Source名字与Free否定词歧义仍有已披露保守遗漏，有限完整肯定关系及table绑定不宣称通用NLI。六版中间失败全部保留，尚未作为真实模型生成成功。

### 冻结真实回归结论

最终后端5664通过／1跳过／212 warnings，170.81秒，127新增匿名用例。冻结690份文件及实际helpers，四组各一次40调用／148957 provider token，实际deepseek-flash；9捕获中1正文脱敏，旧147文件不变。独立正文3正确／1错误／4遗漏、回答记录2正确／6遗漏，0/4达标；不宣称整体改善，不训练。001经隔离重放证实answer_body_unresolved误拒，原批处理污染猜测不成立；现有parser已经逐行隔离。下一步先修数量结论守卫、直接谓词投影与覆盖、服务端资料状态、价格行／FAQ及依赖丢失。具体结果见evidence-recovery交付及JSON。
