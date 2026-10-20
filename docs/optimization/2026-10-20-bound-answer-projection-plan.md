# 完整引用支持与回答投影实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。每项由一位新实施者顺序修改；规格审查通过后，再做独立质量审查。用户已确认先完整绑定、再结论／澄清投影及四家复验，按此细化执行。

**Goal:** 阻止 1Password 的复合观察借用未绑定原文，并使 Bitwarden 已审核上限形成实际结论、请求歧义形成不夹带产品断言的澄清。

**Architecture:** 沿用 v3、现有 source/operation binding、结论与 renderer。支持审核按单条主张隔离；确定性门槛重放明确的额外独立动作。数量识别只修格式误拒；纯澄清由当前请求和有限字段生成，最终 QA 精确重建。事实、请求条件、结论及询问保留各自身份。

**Tech Stack:** Python、Pydantic、pytest、当前 SNAP／Writer／QA；既有 DeepSeek 生成与 Fetch 适配器。

## 已确认设计与边界

- 基线 `ef53a35eade14f664404aedb3f5eb02769e4fe6a`，复用 `plan_a_pm_modes` 隔离工作区和 `codex/pastoral-desktop`。325 项相关基线测试通过。
- `/tmp/plan_a_v33_previous_artifact_sha.json` 保护 1332 份历史产物、评测及上轮交付记录；参考答案和标签不改、不进入运行输入。
- 采用“明确支持范围＋独立回答投影”。继续叠加宽上下文提示已复现失败；新建数字推理引擎或 v4 协议会扩大范围，本轮不采用。
- 不用产品、题号或答案白名单，不按标点自动拆事实，不把请求数字写成来源事实。
- 不扩大每组 24 次调用／80000 token／2048 输出的上限。v3 逐条支持审核使用既有额度，额度不足记未核实，保留核心阶段与答案复核预算。
- 旧 v2 路径、无问题维度与来源身份／条件／例外验证保留。新纯澄清不代表来源已齐全；真实核心预算遗漏继续记录。
- 不训练模型、不下载新权重、不执行 Docker、不改真实 `.env`，不新增基础设施或 PR、不合并主分支。

## 任务一：让支持范围成为实际审核与回放边界

**Files:** 修改 `backend/packages/agents/writer/dimension_writer.py`、`backend/packages/research/evidence/report_claims.py`、必要的 `backend/packages/research/evidence/operation_claim_checks.py`；新增 `backend/tests/unit/test_bound_claim_support.py`。仅在确需独立纯 helper 时新增一个小模块，不重构邻近逻辑。

- [x] 保留 `/tmp/plan_a_v33_binding_probe.py --red` 原失败；新增匿名 share／manage 与原 c180 的失败回归，使用真实 v3 最终审核入口，即使模型给出全文 supported 也必须拒绝未绑定独立动作。
- [x] v3 按主张独立审核，输入支持池仅含本条准确 operation quote 与完整 source-local 条件，或明确 source spans。其他主张的 span、父级整段 quote/value 不进入支持池。必要限制／日期／例外由现有完整约束及确定性守卫检查，不能因窄化支持而丢条件。
- [x] 移除 v3 operation 审核的宽 original-quote 回退，保留 legacy 审核行为；每条明确返回整个主张的 support／atomicity，理由有界。
- [x] 在 v3 实时审核和最终重放共用额外独立动作检查。不能直接使用检索用 `required_operations`；识别明确 EN／ZH 独立谓词，遮蔽角色权限前提和 permission selector。原中文“可像……并管理其访问权限”必须被识别，单纯改旧集合差集不够。
- [x] 合法单动作、完整 AND／OR 条件、主体已有管理权限后编辑、权限选项设置、否定和日期限制正例保持；同动作不同对象及未知语言仍由窄支持语义审核，不宣称通用谓词证明。

行为验收示例：

```python
assert audit_compound_with_forced_supported_review().status == 'rejected'
assert audit_complete_share_rule().status == 'supported'
assert audit_independently_bound_manage_rule().status == 'supported'
assert sibling_quote not in actual_single_claim_support_input
assert all_required_source_conditions_retained
```

运行：

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=backend:backend/tests/unit:backend/tests/integration \
../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_bound_claim_support.py backend/tests/unit/test_atomic_question_answers.py backend/tests/unit/test_report_claim_audit.py backend/tests/unit/test_source_span_binding.py -q --tb=short
```

先保存 RED，再最小实施、GREEN。冻结 `/tmp/plan_a_v33_binding_freeze_v1.json` 后停写，顺序做 SPEC → fresh QUALITY；同一实施者修具体发现并保留每版冻结。根通过后才开始任务二。

任务一复核：初次 SPEC 发现条件截断和 `only after` 限制丢失，QUALITY 发现条件体动作误归属及合法倒装前提误拒，均保留 RED 并修复。最终 v3 冻结后，SPEC／QUALITY 分别通过；43 项新增、402 项相关回归通过。原 c180 的精确 claim／review／fact 改用可提交的最小 JSON 夹具，测试无需本机历史产物。有限词表不构成通用 NLI，预算不足仍为未核实。最终全量和真实流程结果见后续交付记录。

## 任务二：完整事实形成结论，纯澄清只询问用户输入

**Files:** 修改 `backend/packages/agents/writer/answer_resolution.py`、`answer_coverage.py`、`dimension_writer.py`、`backend/packages/agents/qa/evidence_alignment.py`；新增有限请求澄清 helper 与 `backend/tests/unit/test_answer_projection.py`。必要时复用 `research/evidence/source_exceptions.py` 的字段词汇，保留旧来源例外语义。预计 API schema 不变。

- [x] 原样重放 BW 两次 coverage：Q001 明确 no 仍被 `answer_body_unresolved` 拒绝；Q002 四字段和 unknown 非单点问题。保留原提案／原拒绝记录，不能改旧资料制造成功。
- [x] 数量上限结构识别支持空格和完整名词后缀；一个原子的短引号不能抹掉另一完整 cap 原子。示例、建议、假设、元语言引用、未完成条件不变成事实断言。识别器不判断数值真假、单位／范围关系或生成 yes／no；继续使用现有独立答案复核与“结论：否”renderer。
- [x] 新纯 helper 从当前问题识别真实产品／数据操作结果请求及明确输入歧义，排除拼写／翻译／引文操作；已明确 Remove member／Delete account 或数据归属时不重复询问。仅当请求本身涉及副本／链接且输入缺失时询问相应字段，不从产品常识制造必要前提。
- [x] 对原 BW 模糊离职问题，服务器先询问具体操作和数据归属。输出为 v3、`partial/clarification/depends`、空 claim／evidence、有限字段、固定正文和理由；不写保留／删除结论。零 supported 情况同样可生成，不新增模型调用。
- [x] 接入 `_dimension_question_coverage` 的服务器答案分流，剩余问题继续既有模型提案和独立复核；模型自由 reason／missing_fields 不能反向授权纯澄清。完整源规则澄清保留原路径，不用无关免费组织事实凑非空选择；增加最小规则相关性验证。
- [x] `selection_answer`、资格检查、最终 QA 和 renderer 对纯澄清从当前 question 精确重建完整 record，要求字段、状态、版本、答案、空引用、有限理由及正文一致；任何新增产品断言、换题、缺项／额外字段、answered／yes 均拒绝。新分支只处理零事实询问，不跳过其他主张、源例外和真实预算缺口。
- [x] 不把原模型 unsupported 的离职主张通过缩短理由改为 supported；不把本文的纯澄清计为已核实各操作分支。

行为验收示例：

```python
assert replay_original_cap_selection().status == 'answered'
assert '结论：否' in render_original_cap_selection()
assert original_cap_claims_and_full_spans_unchanged
assert pure_clarification.claim_ids == pure_clarification.evidence_spans == ()
assert pure_clarification.missing_fields == ('actual_action', 'data_ownership')
assert not qualifies_as_pure_clarification(metalinguistic_question)
assert not qualifies_with_unrelated_sharing_claim(offboarding_question)
assert final_qa_rejects_added_product_assertion
```

运行：

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=backend:backend/tests/unit:backend/tests/integration \
../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_answer_projection.py backend/tests/unit/test_answer_coverage.py backend/tests/unit/test_answer_resolution_guards.py backend/tests/unit/test_atomic_question_answers.py backend/tests/unit/test_source_exception_closure.py backend/tests/unit/test_writer_question_delivery.py backend/tests/integration/test_final_question_receipts.py -q --tb=short
```

冻结 `/tmp/plan_a_v33_projection_freeze_v1.json` 后停写，做 SPEC → fresh QUALITY 与一次累计集成审查。若必须改接口，先证明必要性并同步生成类型与旧赋值兼容，不凭需求猜新增版本。

任务二复核：SPEC／QUALITY 发现方法或定义问题误入纯澄清，修复后通过；累计审查又发现复合问题吞掉独立子问、合法“移出组织”完整来源规则被覆盖。v4 仅修改 helper 与新增测试关闭两项发现，独立复跑 165 项通过。原 `test_source_span_binding.py` 与基线字节一致，9 参数旧回归保留。初次全后端 6438 通过／9 失败／1 跳过及所有 RED 留存；最终 v4 全后端 6452 通过／1 跳过。

## 根代理验证和真实复验

- [x] 全后端、变更范围 Ruff E9/F、空白检查、API／旧 TS、前端构建；全后端四项既有 F401 不混入本轮改动。保存失败与修复证据，不以受控支持 fixture 代替真实语义结果。
- [x] 新目录 `data/artifacts/answer-projection-2026-10-20/`，冻结源码、资料、运行及指标 helper；八题只传 id/product/question/sources(id,title,url)。先运行防漂移／金标泄漏离线预检。
- [x] Bitwarden → 1Password → Dropbox → Cloudflare 各首次顺序运行一次，原预算、无模型重试。Search／Fetch 请求和费用估计与生成 token 分账，来源失败与真实模型阶段区分。
- [x] fresh 只读内容审读按八题分别判正文、保存记录和全部发表主张；核完整原文在实际输入、每个绑定及条件，纯澄清无产品断言。独立标签不是新用户人审。仍失败如实计数，不能改 gold／删题凑通过。
- [x] 核 1332 历史文件及新冻结前后一致；扫描实际凭据字面量及常见密钥模式，覆盖新文件、构建和新产物，不输出密钥、不冒充完整 Git 历史审计。
- [x] 更新 README、Agent 执行说明、正式验收和新交付／结构化结果，保留未完成项。
- [ ] 提交前核扫描和历史／源码完整性，再按既有授权提交推送当前分支，核远端 SHA。此文件快照保存于提交前，最终 Git 结果另存本机 `verification/git-delivery.json`，以远端分支实际 SHA 为准。

本轮不预先宣称报告达标。上轮八题正文／记录均 3 正确、5 遗漏，6 条观察 5 条完整绑定、系统 0/4；本轮结果由冻结后的首次真实产物决定。两轮均已曝光、非盲、非受控 A/B，不据此宣称一般准确率或 token 效率改善。

本轮冻结后首次真实复验结论：正文／记录均 5 正确、0 错误、3 遗漏；7 条发表主张 5 条完整绑定。局部内容 2/4，内容与绑定同时 0/4，系统 0/4、6 阻断。新发现 BW 额外共享动作越过窄 span、1Password 模态强化、CF 规则未投影以及 Dropbox 正文失败均留作明确未完成项；不在首轮真实验收后改代码或改标签凑通过。
