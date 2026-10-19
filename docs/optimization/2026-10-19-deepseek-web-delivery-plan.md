# 新版 DeepSeek 网页工具与证据消费实施计划

> For agentic workers: 使用 subagent-driven-development；每项先 SPEC 后 QUALITY，通过后再实施下一项。只读根因调查可并行，代码实施单写者。用户已确认方案及执行，无须再次请求同一授权。

**Goal:** 接入官方独立 Search/Fetch，实测失败页面，再修重复标题选窗和问题级原始证据消费，按同一冻结版本复验四家报告。

**Architecture:** 主模型继续使用 `deepseek-flash`。新版网页工具为可配置的独立适配器，返回来源候选和原文，沿用当前 Collector→准入→canonical→snapshot→Writer 链。模型输出、搜索摘要、API成功和可引用事实资格分别记录；保留旧接口以便回退。不加训练、下载权重、Docker或基础设施。

**Tech Stack:** 既有Python/httpx/Pydantic/pytest、SQLite、现有DeepSeek配置。

## 授权、基线与验证边界

- 用户2026-10-19明确批准本顺序及真实联网测试，沿用现有隔离worktree、`codex/pastoral-desktop`。
- 基线commit `218fe06162fda7841648fbe61d222af938d0b6aa`，production package SHA `9afef23c3ae0f92e2614d5f15371489b865eb100202e601066f863b2bc317fd4`；后端5811通过/1跳过。上轮正文3正确/5遗漏、回答记录2正确/6遗漏、0/4完整交付。
- 旧产物由 `/tmp/plan_a_v30_previous_artifact_sha.json` 固定。只在新 `data/artifacts/deepseek-web-delivery-2026-10-19/` 写本轮结果，不改已审核题、旧报告或标签。
- 官方API文档：<https://api-docs.deepseek.com/guides/search/>、<https://api-docs.deepseek.com/api/fetch/>。Search请求query为1–128字符、count1–50；Fetch仅给title/content。401/402/403/404等保留失败，不循环重试。
- 两个Dropbox失败URL和1Password定价URL，各做一次本地链与新版Fetch对比；另外两个产品检索查询各一次，不调用生成模型。实际请求数与成功计费条件独立统计，不编造LLM token。
- 四家各首次固定来源阶段复验一次，保持24 calls/80000 token/2048 output/retry0。输入只含问题和官方来源身份；独立实读正文、回答记录、引用和证据链，曝光dev不作盲测或整体改善结论。

## Task 1：独立 Search/Fetch 与真实失败页对比

Files：新增 `backend/packages/search/deepseek_web_client.py`、`backend/packages/tools/deepseek_fetch.py`；必要修改search/client.py、config/settings.py、orchestrator/search_execution.py、tools/evidence_fetch.py、orchestrator/service.py、research/capture/official.py及`.env.example`；新匿名单元/集成测试。

- [x] RED：MockTransport检查固定官方端点、Bearer、Search结构化results/Fetch正文与hash；拒绝空/畸形结果、摘要充原文、超长query、非法目标及非200。外部错误不泄露请求头或密钥。

  ```python
  assert request.url.path == '/v1/tools/search'
  assert result.provider == 'deepseek'
  assert result.status_code is None  # 原站状态未由API报告
  assert result.capture_metadata['provider_fetch']['response_status_code'] == 200
  ```

- [x] 在可配置开关下使用新Search，旧native模式兼容；真实search入口共享缓存/锁及Collector搜索次数门禁。工具请求及费用估计单独记录，不伪造模型token或占用模型生成配额；长query在传输前明确拒绝，不静默截去条件。普通短查询必须可执行，语言/域等仅用受支持语法与本地后过滤，未知实时性约束不能声称已满足。
- [x] 新Fetch仅用于公开网页的低质/结构缺口补充，受当前advanced次数预算控制；不能越过robots、SSRF、认证或明确访问拒绝。接口失败保留本地结果和诊断，不无限补抓。
- [x] 明确provider读取凭据：固定端点、requested URL、API状态、原文hash、观察时间，原站状态/最后URL保持未知。原文来源资格采取显式provider分支，校验实际请求与hash/标题/范围，不能把200或任意metadata当作原站证据；搜索摘要始终待核验。准入和canonical重放需要保留相同资格。
- [x] 离线贯通实际fetch→capture→原提取/准入→SQLite→snapshot→Writer视图，包含错URL/hash/产品及伪造不完整凭据反例。保持原直接HTTP门禁不变。
- [x] SPEC→QUALITY，两审通过后冻结Task1，再调用新接口完成三页/两查询的有界对比，保留失败和正文差异；不偷偷用历史正文替换实时结果。

Run：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_deepseek_web_api.py backend/tests/unit/test_deepseek_fetch.py -q`，先预期失败，再通过；旧DeepSeek搜索/抓取/官方来源测试同跑。

## Task 2：通用章节定位与完整计费选窗

Files：调查确认后的 `tools/fetch_page.py`、`research/extraction/semantic.py`、`research/extraction/billing_rules.py`、新测试。不得顺手重构来源体系。

- [x] RED：匿名两服务表格/完整脚注/重复Footnotes标题，实际正文非空但选窗为空；源结构规则与模型入口均须重现。
- [x] 抓取时保留heading对应的真实原文位置/occurrence身份，按实际区间定位；不猜第一个同名标题。完整服务表头、单位、脚注与分支保留，未知来源仍保守缺口，跨服务/不完整脚注继续拒绝。
- [x] 经真实选窗→提案→admission→normalized→snapshot及Writer选择重放证明完整原行和条件进入，不以窗口非空代替正确性。
- [x] SPEC→QUALITY后冻结；使用上轮捕获只做离线开发回归，不能当本轮实时来源。

Run：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_source_window_identity.py backend/tests/unit/test_service_window_recovery.py backend/tests/unit/test_billing_rule_context.py -q`，保留重复标题、缺标题、错服务、超容量反例。

## Task 3：问题级原始证据消费与最终回答保存

Files：`agents/writer/question_retrieval.py`、`answer_coverage.py`、`answer_resolution.py`、`price_answers.py`、`dimension_writer.py`、实际证据选择模块及对应匿名测试，按调查最小改动。

- [x] RED：两个问题中第一题套餐与第二题删除/归属共存，已入快照的第二题关键原句在Writer前丢失；另一例模型中间审核有效否定，被服务器中文断言/主语解析误拒而将最终record降级；缺价答复遗漏CPU/定制报价或索取已给条件。
- [x] 在现有容量内按问题匹配并保留必要原始事实/前提，解决通用跨语种意图遗漏；不以分析转述代替原始绑定。不得硬编码产品/金标，不抬Writer14000 bytes/8 facts或条件1600上限。
- [x] 修复实际审核→断言/主语校验→最终回答记录的绑定；已给一年/产品等只作请求约束，不成事实；一年购买期限不自动等于年付周期。缺证答复保留可验证的定价方式/明确未知，不能一律声称已回答。
- [x] 实际Writer入口、完整prompt投影、claim/引用审核与最终QA同时验证；非法claim、来源/题目漂移、缺前提及未知语义保持拒绝。
- [x] SPEC→QUALITY后冻结，参考答案不进入实际Agent输入。

Run：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_writer_question_delivery.py backend/tests/unit/test_answer_coverage.py backend/tests/unit/test_answer_selection_contract.py backend/tests/unit/test_incomplete_quote_answers.py -q`。

## Task 4：最终验收、交付与GitHub

- [x] 最终全后端、变更范围Ruff E9/F、OpenAPI字节对比、diff和凭据扫描；既存4项F401单列，未改前端不重跑。
- [x] 累计独立审查通过后冻结所有backend/vendored Python、运行helper、登记、参考和每组manifest，再分别运行四组一次。保留工具请求数与费用估计、模型transport/token、失败、捕获hash和缺口。
- [x] 独立核对每题正文/最终记录/引用，局部计遗漏；按实际正文及关键事实匹配判可交付，不将QA0/dispatch完成当正确。报告未获用户验收，reward=null、training_ready=false。
- [x] 更新README、Agent执行、交付Markdown/JSON，保留历史失败。
- Git交付方式：按既有授权提交推送当前分支，结束时以远端SHA核验；不合并主分支。

## 执行记录

- 已确认现有linked worktree及干净基线。已启动只读Cloudflare窗口与Writer消费根因调查，项目外部模型/新工具调用尚为0。

- 只读诊断：CF丢失具体heading身份后对Footnotes全局反查歧义，模型/规则同窗口为空；匿名去掉兄弟服务重复标题即恢复目标完整表格，错单位/缺脚注继续拒绝。Writer问题是中文意图词面召回及断言/主语解析误拒，不是最终存储丢失；一年期限与年付周期须分开。详细临时复现脚本在`/tmp/plan_a_v30_*_repro.py`，未修改旧产物。

- Task1 v1实施90项新增用例，220项相关通过；独立SPEC确认API200内维护页/错误页/纯Markdown导航误授full_source，暂未通过。已按失败链补v2正文质量反例，未放宽来源门禁，真实新接口调用仍为0。v1冻结SHA `8a48dc358af45c8351ac222c9bc16d46d127dc2792604a9b50e5319f62ef273f`保留。

- Task1 v2：232相关测试通过，SPEC独立复跑及三原误收反例验证通过；同时修复多域OR/多语言语法、已知空上游响应不计费估计。冻结SHA `24f94025b3c4ab333cc443f85fca4d20a2f8e26c608914c4c8d735663923fc00`，QUALITY进行中。原站状态/最终URL未知仍明确保留，未用API200冒充。

- Task1 v3：QUALITY发现维护通知混请求编号/版权尾注仍误收、Redis重播失败Fetch计数；修复后254相关测试通过，SPEC独立通过，root亦254通过，QUALITY复审中。新provider route暂绕Redis抓取缓存，避免重播历史调用计为当前；flag关旧缓存回归通过。v3冻结SHA `57c5ea440d189f15dc67b7e978b6c0eef92c3fc8997cf4c3ff027bdd8c66d52a`；v1/v2及312旧产物保留。

- Task1 v3两审PASS后，预冻结706个Python文件和比较helper，三页各本地/新Fetch一次＋两Search完成，无重试/生成调用。Fetch：Dropbox两URL均404（本地仅33chars亦拒绝），1Password本地1159chars/新2541chars均取得正文，但新增主要为产品说明/FAQ，没有当前金额或完整报价条件，不能据长度宣称价格补齐；Search各3候选。共5个工具请求/3个成功非空计费估计（非账户账单），0生成调用。比较期706文件和312旧产物保持不变。
- Task2实施中，额外通过现有robots/SSRF直接HTTP一次归档当下Cloudflare原HTML（26644chars正文），供离线结构定位；不调用模型或新网页API，原档不入Git。

- Task2实现冻结：两个生产文件及匿名测试，331相关通过，root独立331通过。实际当前HTML离线两路（规则与真实模型入口mock）均贯通原准入、SQLite、快照和Writer视图；30heading/5730字符窗口，完整表头/四脚注/最低费用前提保留，视图5635/8192Bytes。已处理重复答案去重造成marker漂移，严格完整块及DOM出现次数约束保留，短答案substring掩盖变更的负例先RED后修复。冻结SHA `a7b1444778c998ddcf129a5a6813cf4498ffce91d008dbd0d8aca44727da02b0`；等待SPEC→QUALITY。

- Task2 v1 SPEC未通过：未标记div正文时缺失标题被补到文尾，产生无gap的错误源顺序/空服务窗口；HTML anchors删光source_path仍被pathless分支接受。独立两例2failed，正向当前HTML两路贯通不掩盖这两处通用缺口。实施v2修复中，原freeze与诊断保留，不进入Task3/QUALITY。

- Task2 v2冻结SHA `9029281cbcc3466c2444c9642d1d6849d49c0ea9ad42971fb4cd9f188989a9ce`：339相关通过（含独立SPEC复现2项），root亦339通过。针对未绑定flow正文拒绝猜补，pathless只允许完整Markdown。当前HTML两路仍完整贯通；v1及312旧产物未改，SPEC复审中。

- Task2 v2 QUALITY又发现无DOM标题HTML中的Bash注释被当Markdown标题、完整正文窗口误清。v3按原捕获格式区分0heading HTML与Markdown，非空HTML仍要求完整paths；341相关通过（含审查三原反例），root亦341通过。冻结SHA `6795bf791bedf6055793887db3182bf58504ace3f7439be2741b8a6243b6f705`；原v1/v2与诊断保留，当前HTML链仍成功，SPEC→QUALITY复审中。

- Task2 v3 SPEC与QUALITY均PASS，独立各341通过并各重放实际HTML完整链，无marker漏出；root341通过。三版31份冻结证据及旧312产物不变。现进入Task3 Writer，仅一个实现写者，禁止改已通过的Task1/2与参考答案；继续原授权，不训练。

- Task3 v1冻结SHA `876105e2bc306e77efd113173abd79db25e5c351bf0d44eec53dcff60eace550`：402相关通过（root与SPEC各自402），真实Writer mock到最终QA覆盖生命周期原句、中文否定与计费竞争；11项初始RED及4风险RED保留。SPEC另复现四独立核心因perquestion3而遗漏（仅3708/14000Bytes）、明确250付费席位与300员工并存仍重复索要席位。等待正式finding后修v2；尚未付费生成模型调用。

- Task3 v2冻结SHA `ccb29431f515dc45c5654464aee2aa148929a752128c18a8791a7f63dcd0f981`：406相关通过，新增四项实际Writer及保存答复RED回归。核心分支不再先受普通每题三条限制，仍共用总八条／14000 bytes；真正容量缺口进入已有prompt及audit gaps，QA保留incomplete。明确员工数与付费席位分别保留为请求条件，不重复索取已给席位。v1及312旧产物、Task1/2哈希保持不变，SPEC复审中；真实生成仍未开始。

- Task3 v2复查发现重复原文 ID 未发送也触发核心不足的假阳性。root完整后端回归另为43失败／5928通过／1跳过：新增裸“访问”断言绕过旧的引述、示例、疑问及不完整条件守卫（42例），以及一项已知套餐提示文案冲突。原日志保存在`/tmp/plan_a_v30_backend_v2_before_fix.log`；v3须修复并重新全测，不能以406相关通过替代完整验收。API字节一致，变更范围Ruff与凭据扫描通过，四项既存F401文件与HEAD相同。

- Task3 v3冻结SHA `e1db47e5e481775c8b6cf4b9a2dce0503dd583a076357647e98dbaf1b16409de`：562相关通过，SPEC独立562通过。仅完整quote/value/qualifiers均相同的已发送原文可消除冗余missing，保留不同条件及来源身份；删除多余裸“访问”断言，已知请求标明“购买范围”。重复原文真实Writer链最终QA通过，遗漏legal-hold条件仍incomplete。root全后端5973通过／1跳过（212 warnings，173.43s），比基线新增162测试；旧43失败记录保留。QUALITY进行中，模型真实复验尚未开始。

- Task3 v3 QUALITY未通过：独立重现第四条不同原文携带legal-hold前提，但旧“已有三条且标签覆盖即停止”将它排除，5692 bytes下既未发送也未记缺口，实际保存answered／最终QA0。此前冗余去重修复不覆盖这类不同条件，v4需最小删除该停止规则，并保留原总容量与完整条件身份。独立脚本SHA `29aa8c17ffb641fcb2366a0142e40e9d5043dfd2066e63736b5add99829ac8ee`及旧冻结保留，不能以5973全测通过代替语义审查。

- Task3 v4冻结SHA `1dd005bf7fff17ce4a0a1b9ce225f8b3afc4570b11b4bf782a868840ddfb4f41`：生产仅删旧停止规则两行，新匿名双预算用例核对实际prompt、完整条件claim/span、保存及QA。564相关通过，SPEC独立564通过；14k下第四条件发表，3k下缺口继续阻断。root最终全后端5975通过／1跳过（212 warnings，173.29s），新增164测试，Ruff/API字节/diff/凭据扫描通过。所有旧版本与312旧产物保留，QUALITY复审中，真实模型尚未开始。

- Task3 v4 SPEC与QUALITY均PASS，独立各564通过；QUALITY完整链验证14k的7facts／6953bytes保存第四条件且QA0，3k的2facts／2348bytes保留缺口并QA incomplete。62处历史证据hash引用及Task1/2、312旧产物不变。进入新鲜累计集成审查，尚不启动四家付费生成。

- 新鲜累计审查164新用例通过，但发现两个P2：Fetch POST发出后总超时取消会丢工具span／计量；live wrapper只检查preview，vendored或helper冻结漂移要事后才发现。真实调用继续暂缓。前者最小异常白名单计量桥已冻结SHA `436786d416d3cb7e417f2a57c1a5cfbc500ee6fb3495505e9afe1f0591c83573`，261相关通过，5个取消阶段和2正常对照覆盖，不吞取消／不重试／不补抓；请求未发释放advanced预留，已发无响应标记`web_api_billing_unknown_requests`而不假称未收费。后者每组调用前校验完整冻结文件及所有helper，8个正反场景仅合法包进入fake live入口；实际模型调用0。两项进入SPEC→QUALITY，所有旧freeze／repro／日志保留，Task1旧版本由新最小修复明确接续。

- 取消补丁SPEC独立261及wrapper8场景PASS，另测响应200/402退出阶段仍同异常／一次span，保护432处hash。root新鲜完整后端5982通过／1跳过（212warnings，179.26s），变更Ruff/API字节/diff通过；QUALITY检查中。当前新增171测试，源未再改，四组真实生成仍为0。

- 取消补丁两审及最终累计复审PASS；新鲜累计独立171新增测试、取消5场景及wrapper8场景均通过。最终生产SHA `6fe7b9cff959f8674b69751636bf8d142d3f91d140258f0896caac530dce1509`，冻结713文件与所有运行helper、四组manifest；新Fetch开关仅在隔离CLI临时开启。本轮四组各一次开始，所有参考答案均不进入运行输入。

- 最终累计复审PASS（新报告SHA `c1b279df80fe64261befde831676b6c9fe2c325483d0b0c7b55be48163c4272d`），171新增用例与取消／wrapper反例独立通过。运行前冻结713文件，freeze SHA `57105b0a933311e1455b5d7275d2c6d85b0e3eee4192dff7b7c8895121bcd48f`。Bitwarden首次执行完成：3源／72facts，10调用／36131token，1QA blocker，尚待独立内容评分；其余组顺序运行，不重跑取优。

- 四组首次运行全部完成并通过713文件／helper／312旧产物后验校验：22调用／75844token，5工具请求／3成功非空估计／0收费未知；九份捕获哈希完整，无脱敏。独立正文2正确／1错误／5遗漏，记录2正确／6遗漏；仅Cloudflare限定两题内容可交付，系统机械交付0/4。已更新README、Agent执行、正式验收及交付Markdown/JSON，等待最终凭据扫描、提交推送。未重跑取优，未训练。

- 交付最终凭据扫描1369文件PASS，当前配置密钥无命中、实际env不在Git；scope含代码、文档、前端dist和本轮归档，不含Git历史。仅将源码、测试、示例配置和交付文档提交当前开发分支。

- 暂存diffcheck补发现未跟踪的新测试文件EOF多一空行；清理后AST完全一致，22项复跑通过。原713冻结不重写，当前712份逐字相同＋1测试格式差异显式记录；生产SHA、全部运行helper及312旧产物仍一致。无需为纯测试空行重跑付费模型。
