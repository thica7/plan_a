# 关键例外闭合与计费答复修复计划

> 用户已授权依次实施、测试与四家重跑，继续当前 `codex/pastoral-desktop` 已隔离工作树；不重复请求确认。按 systematic-debugging、TDD、subagent-driven-development 执行，各任务规格及质量审查完成后冻结。暂不训练模型。

**Goal:** 将来源中的关键例外保留、检索并绑定到适用主张，正确处理含糊操作与访问路径，再让完整计费规则准入并给出具体缺项答复。

**Architecture:** 沿用准入快照、原文观察和 v2 完整主张复制。新增有限、来源局部的例外收据，覆盖身份认证、保留副本与访问路径；不得跨产品、抓取或对象拼接。计费信号与完整表格上下文统一，仍不生成采购现价或完整账单。缺价意图与请求口径齐全检查分开，所有不足答复绑定当前快照并由最终 QA 重算。

**Tech Stack:** 现有 Python/Pydantic/pytest、DeepSeek 与已有本机 E5；无训练、权重下载或 Docker。

## 已验证的根因

- Bitwarden 的 SSO 例外已在既有 fact.value、Writer 与两次审核输入中，仍被忽略；独立完整 SSO 块长 818 字符，超过 800 限制未形成独立观察。主张和答案的既有确定性校验均未报错。
- Dropbox 的 keep-copy、leave/link 原文已准入，每题前三条被重复或偏题观察占满；`except if:` 后固定两行上下文漏掉完整例外列表。错误 conditional/yes 能通过现有校验。
- 计费金额例外和 pricing quality 使用两套信号；权限专用表格上下文不保留请求／CPU 列与数字、多行脚注。无可验证章节时全窗口条件扩散；完整 body/headings 尚未进入 focus 签名。
- 缺价入口要求市场、方案、币种和周期齐全才识别请求，忽略账单／总价等表述，不能产出澄清项。本批被拒计费页的完整捕获未保存，无法精确重放全部上下文。
- 当前相关基线 64 项通过；上一阶段全后端 5361 通过／1 跳过，只是历史基线。

## 1. 关键例外与真实分支

Files: 新建 `backend/packages/research/evidence/source_exceptions.py`；按必要范围修改 `extraction/semantic.py`、`evidence/normalization.py`、`evidence/report_claims.py`、`agents/writer/question_retrieval.py`、`agents/writer/answer_coverage.py`、`agents/writer/dimension_writer.py` 及最终 QA；新增 `backend/tests/unit/test_source_exception_closure.py`。

- [x] 匿名 RED：身份认证例外已在 fact.value 但主张只保证移除后仍可访问；副本／独立访问路径被重复选证挤掉；完整 except 列表超过两行；完整来源条件块超过 800 字符不得静默裁切。
- [x] 在来源身份、适用动作及对象一致时生成完整例外收据；`source_exception_links(item, accepted_items)` 返回原文及所属准入项身份，`claim_source_exception_reasons(claim, facts)` 拒绝遗漏适用例外的保证。跨抓取、产品、对象、角色和相反动作反例不得串配。
- [x] 选证保留实际例外分支，避免重复段落占满；总八条及整体输入容量保持有界。无法闭合则记录具体缺口，不把未选中写成原文没有。
- [x] Writer 输入显式列出所需分支与待澄清项；操作／归属／副本选择未知时正文需要带分支并请求澄清。答案仍只能完整复制已发表 ID，理由或未发表原文不能补答案；最终 QA 重放相同收据和结论守卫。
- [x] 新匿名测试先失败再通过，重放旧两家完整 fact/value 和错误主张，确认遗漏被拒、完整条件通过；独立 SPEC → QUALITY 无未关闭 Important。

例：匿名原文说明被移除用户通常保留个人库，但无主密码的联合登录用户需恢复账户并在移除前至少登录一次；只有“仍可访问个人库”的主张应返回 `source_exception_omitted`，保留两项前提与未知输入的完整主张应通过。

## 2. 统一计费规则及原表绑定

Files: 新建 `backend/packages/research/extraction/billing_rules.py`；修改 `extraction/semantic.py`、必要的 `evidence/admission.py`；新增 `backend/tests/unit/test_billing_rule_context.py`。

- [x] 匿名 RED 覆盖 minimum fee、请求／CPU 金额表、非金额计费及免费例外、数字／星号／多行脚注、同二级章节多服务和超过六条无关条件。
- [x] 共享 `is_billing_question(text)`、`billing_rule_text_signal(text)`；模型金额筛选、质量补充及重放使用一致信号。必须是明确计费问题和实际原文规则，单独 `$`、普通功能描述或请求中的金额都不放行。
- [x] `billing_table_context(body, start, end, bounds)` 只从完整原表提取表头、列单位和相应完整脚注。保留 source observation、原始表格与章节边界，不生成采购金额字段；官方示例不能变成本月总账单。
- [x] 使用最近可验证服务章节及实际连续原文范围；无章节时不把全页条件附到每条规则，也不简单抬高容量。签名绑定完整 body hash 与验证过的 headings，窗口外条件变化必须失效。
- [x] 原文→提取→准入重放→规范字段→快照通过；改单位、脚注、条件、active focus、来源或位置的反例拒绝。SPEC → QUALITY 后停止修改。

## 3. 意图、口径与不足答复

Files: `backend/packages/agents/writer/price_answers.py`、必要的 Writer／QA 入口；新增 `backend/tests/unit/test_incomplete_quote_answers.py`，保留既有价格安全测试。

- [x] 匿名 RED：缺市场的精确含税总价、只有请求数的本月账单、未知套餐及周期，仍需产生具体不足／澄清项；币种不是市场，用户用量不是来源事实。
- [x] 先识别明确金额／总价／账单请求，再检查市场、币种、方案、周期、税费或用量输入。日期无效、相矛盾或仅询问计费机制不自动回答；已存在完整匹配现价不能被遮蔽。
- [x] 不完整口径明确写“请先确认”的字段，不声称市场上没有价格；用量缺项只从本次准入计费规则识别，不引入模型记忆。已知规则留在有引用的正文；不推算总价、税率或汇率。
- [x] 不足答复保留 `basis_snapshot_id`，Writer 与最终 QA 按当前快照重算，篡改、过期、跨项目、容量省略、旧快照继续拒绝。新增行为同步旧夹具断言，不能删除安全断言。
- [x] SPEC → QUALITY，测试包括正确不足、适当澄清、完整报价不拦截和不相关功能不触发。

## 4. 完整捕获与冻结诊断

Files: 仅诊断入口 `backend/scripts/eval_official_writer.py` 及相关测试；生产默认流程不增加模型输入或常驻全量日志。

- [x] 为本轮评测保存每份完整 `CapturedPage`、真实 headings、正文 hash、选择状态及拒入原因，使用现有脱敏写出；原返回值、预算与准入结果不改变。
- [x] 离线夹具验证被拒页面也可重放、失败时已完成捕获保留、秘密脱敏；保存完整数据不意味着数据自动有资格进入报告。
- [x] 新输出目录 `data/artifacts/exception-billing-2026-10-18/`，旧两轮产物哈希不变；八题 reviewed 数据不改，实际 Agent 输入仍只有问题与来源身份。

## 5. 验证与交付

- [x] 所有任务 RED→GREEN、独立规格与质量审查；全后端、Ruff E9/F、OpenAPI 字节对比、diff check、实际凭据字面扫描。前端未改不冒称新前端验收。
- [x] 冻结生产源码、实际 runner/helpers、登记和每组 manifest；四家每组各一次，24 calls／80000 token／输出 2048／retry0，上下游真实阶段执行，已有本机 E5 离线使用。
- [x] 独立逐题核对正文、回答记录、全部条件、否定／澄清、引用及完整报告；零 QA blocker 不视作正确证明。参考已曝光，不作盲测或泛化准确率，失败保持失败。
- [x] 更新 README、Agent 执行说明、交付与结构化结果，准备当前分支审查提交；新报告未获用户验收前 `reward=null`、`training_ready=false`。

诊断归档里程碑：新增3项 RED→GREEN，连同原 official/answer runner 测试29项通过；独立 SPEC 与 QUALITY 均无未关闭问题。归档只作用于隔离 CLI 进程，原始与脱敏后正文 hash 分开记录，实际选择／拒入状态通过 candidate_id 与既有 trace 关联。

缺价里程碑：价格三个定点文件63项通过，独立SPEC及QUALITY关闭了账单功能误接管、否定／跨套餐CPU依赖和单次限制冒充总量。仅高置信金额意图产生自动不足答复；复杂未匹配问法仍交给原问答链。合格来源才可提示CPU总量，通用完整用量缺项不意味着已知最终账单。

关键例外里程碑：64项匿名测试通过，独立SPEC与QUALITY均通过；审查额外关闭否定、角色、动作／保留／同步对象替换、主密码分配及同密码登录媒介遗漏、伪澄清和伪造收据。来源局部有限守卫不提供普遍蕴含证明；尚待四家实际输出核对。

完整回归诊断：首轮5517通过、3失败、1跳过，三失败均为新`source_scope`抓取身份键误当业务条件；新增匿名RED后仅在能力条件识别中排除此身份键，套餐、角色、例外及原文限制仍生效。独立审查与23项能力对齐回归通过；首轮失败日志保留，最终全量另跑。

计费准入里程碑：77项新测试通过，独立SPEC与QUALITY均通过。审查关闭了表前／父级前提丢失、未知Markdown脚注、隐含CPU单位冲突、计费页面权限问题误开金额豁免，以及连续无关键词例外被单行筛选遗漏。完整块超过原预算时拒入；不增加全局容量。最终全后端与四家新产物待核对。

## 真实验收尚未关闭的目标

最终5537通过／1跳过；冻结四组40调用／151761 token。正文3正确、3错误、2遗漏，0/4达到内容交付标准。实现合同审查完成不表示本计划的报告质量Goal已经实现，未赋奖励、未训练。

- [ ] 收据去重后真实SSO事实能进入检索预算，并显式绑定跨页的一般规则与具体例外。
- [ ] 原始完整except组不被尾随操作引导误弃，正确中文副本／链接草稿不被跨动作约束误拒。
- [ ] 逐问由真正发表的限制和引用支持结论，修复003假阳性与007过度拒答。
- [ ] 修复重复heading及子服务选窗、原始整行绑定，区分未采／未提取／未准入／未选／未发表。
- [ ] 新版本冻结后完成未曝光样本与真实报告验收；当前失败产物原样保留。

集成按已有授权提交并推送`codex/pastoral-desktop`，在会话中核对远端commit SHA；提交不解除上述报告发布阻断。最终实际凭据字面扫描1343文件0命中，未跟踪秘密配置，范围不包括Git历史。
