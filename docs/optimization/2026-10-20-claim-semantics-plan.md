# 完整主张审核与问题结论投影实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。每项代码任务仅一位新实施者，顺序执行，SPEC 通过后再做 fresh QUALITY；根代理完成累计审查、正式工程验证与冻结后的真实复验。用户已确认上一条设计及本轮执行，无需重复确认。

**Goal:** 拒绝 Bitwarden 额外未绑定断言与 1Password 的模态强化，使 Cloudflare 已通过独立复审的否定结论进入正文与保存记录，再以旧八题和冻结新候选判断交付质量。

**Architecture:** 复用 v3、现有精确 source span／operation binding、独立支持及答案复审、结论 renderer 与最终 QA。主张通用守卫同时用于实时及最终重放，支持只来自本条选定原文和完整条件。闭合范围断言只补表达识别，不推导事实或自动设置答案。用户条件、来源事实与问题结论分别保留。

**Tech Stack:** Python、Pydantic、pytest、现有 Writer／QA 与 DeepSeek 适配器；本轮不新增模型、存储或公共接口版本。

## 执行前基线和边界

- 复用 Git linked worktree `plan_a_pm_modes`、分支 `codex/pastoral-desktop`；基线 `6798ba80c8692f576c978c3f514e8370af073457`，工作区开始为 clean。
- 281 项本轮相关基线通过，日志 `/tmp/plan_a_v34_baseline.log`。
- `/tmp/plan_a_v34_previous_artifact_sha.json` 固定保护 1531 份旧产物／金标／上一轮交付文件；新目录为 `data/artifacts/claim-semantics-2026-10-20/`。旧题、原产物和标签不改。
- 现有旧八题为已曝光开发回归。另由独立资料准备者先冻结新候选，不给实施者参考答案，不据此自称盲测；未经用户确认的新题只计 candidate diagnostic。
- 不改真实 `.env`，不训练、不赋奖励、不下载权重、不执行 Docker，不新增 Kafka／Redis 功能、不合并 main、不创建 PR。
- 原 24 调用／80000 token／2048 输出／模型重试 0 的每组限制不扩大。代码守卫不新增模型轮次。新产品测试同样受原限制。
- 不把“所有自然语言蕴含均可确定性证明”作为本轮承诺。明确的结构／模态冲突由服务器拒绝，未知表达继续独立语义审核并如实评测。

## 任务一：完整主张的支持范围和语义强度

**Files:**
- Modify: `backend/packages/research/evidence/report_claims.py`
- Modify: `backend/packages/research/evidence/operation_claim_checks.py`（仅复用／窄化现有动作检查所需）
- Modify: `backend/packages/agents/writer/dimension_writer.py`（原子写作及独立审核提示，保持协议和额度）
- Create if needed: `backend/packages/research/evidence/claim_semantics.py`（仅有界的主张／选定支持检查，不建立新推理框架）
- Create: `backend/tests/unit/test_claim_semantics.py`
- Create: `backend/tests/unit/fixtures/claim_semantics_v33.json`（精确两个原失败的最小、无密钥、可提交夹具）

- [x] 读取只读根因报告 `/tmp/plan_a_v34_claim_diagnosis.md`，先保留原失败 probe；从当前 v33 run/trace 抽取原始 claim/review/fact，用真实 `audit_report_claims(..., review_version=3)` 复现模型 supported 仍错误发表。
- [x] 新失败回归必须覆盖原 BW 无 operation_binding 的额外共享动作和 1P 所选 can promote 被写成必要升级。验证真实 writer 提案／窄支持输入及最终 QA，不只测新 helper。

```python
rows = audit_report_claims([original_claim], [original_supported_review],
                          view, (), review_version=3)
assert rows[0].status == 'rejected'
assert rows[0].rule_reasons
```

- [x] 对匿名反例验证同类冲突：未绑定的独立动作、同一有界动作的 can/must 强度变化、必要条件被写为充分条件；不得用父宽 quote、另一条主张或不相关动作的 must 背书。
- [x] 最小接入同一 v3 实时和最终回放。必须先校验原绑定身份，再只使用精确选定 span／operation quote 与完整实际条件。保持 v2、无显式问题和旧来源身份／日期／例外语义；不修改旧审读标签来通过。
- [x] 保留匿名合法对照：单动作完整 EN/ZH 翻译、选定完整共享规则没有 operation 候选、管理权限仅为前提、完整 AND／OR 条件、否定、必要限制原本就在原文。同词不同对象或未知表达不得被宣称已通用解决。
- [x] 更新写作和逐条支持审核提示，明确独立谓词分别出 atom，原文许可不可强化为义务；不按逗号机械拆事实、不增加响应 schema 字段或模型重试。
- [x] 先 RED 后实现，跑新文件与既有来源／操作／原子主张回归；保留每轮日志和冻结后停写，SPEC → fresh QUALITY 全部通过后才进入任务二。

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=backend:backend/tests/unit:backend/tests/integration \
../plan_a/.venv/bin/python -m pytest \
backend/tests/unit/test_claim_semantics.py \
backend/tests/unit/test_bound_claim_support.py \
backend/tests/unit/test_atomic_question_answers.py \
backend/tests/unit/test_source_span_binding.py \
backend/tests/unit/test_report_claim_audit.py -q --tb=short -p no:cacheprovider
```

## 任务二：闭合范围规则进入问题结论

**Files:**
- Modify: `backend/packages/agents/writer/answer_resolution.py`
- Modify only if needed: `backend/packages/agents/writer/answer_coverage.py`、`dimension_writer.py`（已经有独立复审和结论 renderer，不新增自由答案链）
- Create: `backend/tests/unit/test_scope_rule_projection.py`
- Create: `backend/tests/unit/fixtures/scope_rule_projection_v33.json`（精确原 CF 问题／提案／独立复审／已发表主张和支持，最小可提交夹具）

- [x] 原样保留 coverage span-56 的错误澄清提案及 span-57 已纠正的 answered/direct/no 复审。证明最终仅因“仅适用于”不被认作断言而拒绝；不要把首轮模型误解与末端机械误拒混成一个原因。
- [x] 测试原复审在服务器拼接完整已发表主张、维持 v3 引用后可成为正式 answered/no；正文出现结论否、保存／重载和最终 QA 重放一致，所有原始主张及来源绑定不变。
- [x] 只补完整闭合“主体＋仅／只适用于＋范围”的断言形式识别。反问、引述、例子、建议、假设、未完成条件、未给范围及相反极性不自动获得正式答案；不通过 reason 提供产品答案。
- [x] 匿名资源／角色范围对照必须保留请求条件与来源原文身份：两个用户对象无需在官网逐字出现；缺“无其他权限”时不能给出个人全部权限的绝对结论；独立答案二审仍必需。解析器不自行推导 yes/no。
- [x] 原 Bitwarden 数量投影、纯澄清、来源条件及例外回归保持。URL 小数点等旁支若不是本次原因则记录限制，不作无关重构。

```python
record = parse_answer_coverage(original_review_json, [question], published_ids,
    claims=published_claims, required_binding_version=3, facts=facts)[0]
assert record.status == 'answered' and record.conclusion == 'no'
assert record.answer == published_claims[0]['text']
assert record.evidence_spans[0].quote == published_claims[0]['text']
```

- [x] 保存 RED／GREEN 后冻结。顺序 SPEC → fresh QUALITY，最后独立累计审查两项代码和旧回归；有问题由原实施者修复并保留冻结版本。

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=backend:backend/tests/unit:backend/tests/integration \
../plan_a/.venv/bin/python -m pytest \
backend/tests/unit/test_scope_rule_projection.py \
backend/tests/unit/test_answer_resolution_guards.py \
backend/tests/unit/test_answer_projection.py \
backend/tests/unit/test_source_span_binding.py \
backend/tests/unit/test_writer_question_delivery.py \
backend/tests/integration/test_final_question_receipts.py -q --tb=short -p no:cacheprovider
```

## 根代理工程验收与真实样本

- [x] 独立采样者核官方正文后先冻结新四题及参考依据；只把审核单给用户，运行只收 id/product/question/sources(id,title,url)。没有人审回复也能进行明确标为 candidate 的诊断，不能冒充正式人审。
- [x] 最终源码冻结前完成全后端、变更 Ruff E9/F、diff、OpenAPI 与旧 TS 兼容、前端构建；保存失败及修复，非源修改不无故扩大重复测试。
- [x] 新启动 wrapper 和 metrics helper 另存 v34，保护旧 v33 helper；冻结实际源码／vendor／测试夹具／schema／评测、运行输入、采样参考和 helper。禁网启动预检验证漂移、金标污染与 runtime 字段裁剪。
- [x] 同一最终冻结代码下 Bitwarden → 1Password → Dropbox → Cloudflare 各首次顺序一次；再 Trello／Miro 新题各一次。沿用官方阶段 runner，固定 URL、sparse、非自动发现／全 Graph／生产稠密 RAG，失败不隐藏、不改题重跑。
- [x] 另做 fresh 只读内容审读，正文、保存记录、全部发表主张完整支持及原子性分别计数。题目结论正确不掩盖额外主张；合理澄清／不足不是金额正例，空报告不算拒答成功。旧八题与新候选分表，不混成一般准确率。
- [x] 验收分开记录逐题内容／全部主张绑定、最终 QA 阻断和 Graph 发布终态。现有 `eval_official_writer.py` 的阶段 runner 固定写 `deliverable=False` 且不走 Graph 终态；原始值保留，但不将其作为正文失败的评分依据。未覆盖的系统验收标记未验收，不伪造发布通过或以固定值制造零分。
- [x] 最终报告以实读决定是否达标；已知未解决的抓取、核心上下文和比较门禁不得因本轮局部修复自动关闭。
- [x] 验证 1531 份历史文件、金标、运行冻结前后不变；安全扫描当前凭据字面量与密钥模式，不输出值、不冒充 Git 全历史审计。
- [x] 更新 README、Agent 执行说明、正式验收与新交付／结构化结果。本机产物继续 ignored，不合并主分支。
- [ ] 按既有授权提交推送当前分支并核远端 SHA。此计划是提交前快照，实际完成收据在 ignored 的 `data/artifacts/claim-semantics-2026-10-20/verification/git-delivery.json`，不提前写成功。

## 执行结果（2026-10-21）

工程实现与六组首次复验完成，报告整体未达标。旧八题4正确/4遗漏，新四题4遗漏；局部内容＋claim ID绑定旧组1/4、新组0/2，实际QA阻断分别10、2。完整Graph/发布未测。下一阶段优先修capture→抽取输入/准入事实丢失和Writer length，而非继续追加守卫。[完整交付](2026-10-20-claim-semantics.md)。
