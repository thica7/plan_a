# 表格证据、选证提示与 QA 逐条交付补修

基线：`d8c9bb63bd819b4180f49c4a37bbe7db2f3d07e8`。沿用用户已确认的“已采证据到最终答案、合理推论和 QA 一致性”优先级。使用 systematic-debugging、writing-plans、subagent-driven-development、TDD 与独立双审，串行修改，共享工作树复用。原八题与评分冻结，不训练、不 Docker、不改前端、不改生产实验开关默认值。

## 诊断证据与设计

- Cloudflare 已采角色描述行已入库、进入事实 payload，但 `semantic._table_context` 只认角色作列的权限矩阵；角色作行的原表格表头未保留，Writer 因单行无表头拒绝生成 s-reference。应恢复同一连续原表格的真实上下文，不放开无表头表格。
- Cloudflare 完整 CPU 计费行与表头已经进入模型请求，任务 Top-3 提示却选通用介绍；`support_ref_options` 的文字像封闭选项。保留原协议，新版本明确排序提示仅供参考，完整合法目录均可选；审核仍单条完整支持、拒任意拼接。
- Bitwarden QA 的一条 digest 格式错误使四条结果整体解析失败。新协议逐条严格校验，合法同行保留；坏项保持 pending，受原两次尝试/六批限制。不把 keep 改成通过，不增加未发生的审查。

## Task 1：原表格表头到 Writer 合法支持

范围：`backend/packages/research/extraction/semantic.py`、必要的小型原表格 helper、对应 extraction / projection 测试；仅必要版本接线。

- [x] 从冻结 Cloudflare 原文复现“row 入库但无 s-reference”，增加独立合成表格正反例后先运行失败测试。
- [x] 只从同一个连续 Markdown 表格恢复原 header、separator 和相邻原注释；要求列数一致、正规 separator、选中行完整落于该表格。不得跨空行、标题、代码块、另一表格拼接；无头/错列/含糊定位继续拒绝。已有角色列、billing 专用合同不变。若改变提取身份，用新版本且保留旧显式版本行为。
- [x] 使用原页→semantic extraction→规范化入库→Writer projection 的测试断言角色行拥有真实可选支持，核原文/身份/条件未改；不只测 helper 或手写 metadata。
- [x] 相关回归、规格审查、代码质量审查。

核心断言：`assert original_row in [choice['quote'] for choice in dispatched_support_choices(...).values() if 'quote' in choice]`，并用无表头与错列反例证明仍失败关闭。

## Task 2：建议引用与完整目录分离

范围：`backend/packages/agents/writer/atomic_question_projection.py`、`question_atomic_delivery.py`、`readable_support.py`、最小 protocol 配对/回放接线与测试。

- [x] 冻结旧 v1/v2/v3 SYS/投影行为。新增生成 v4，独立审核仍 v3，默认只迁移新请求；旧记录按其真实版本回放，拒混配/降级。
- [x] 在新 v4 payload 与 SYS 中明确任务排序引用只是 advisory。生成可选择本题已实际发送且可独立重建的完整目录成员，不局限 Top-3。不扩展 fact 范围、不自动接受错引、不任意组合普通引用。
- [x] 保留 v3 dangling-modal 过滤、数量/计费多原子容量、元数据在实际字节计量前接线；允许选择 hint 外的完整引用，同时外题/未发送/歧义/跨条件引用仍拒。
- [x] 离线通过完整 GEN→REVIEW→ANSWER→render→replay 回归，至少一个任务 hint 外关键计费/角色证据被发表；真实语义效果由模型重跑另验。
- [x] 规格审查、代码质量审查。

## Task 3：QA 单条格式失败隔离

范围：`backend/packages/agents/qa/independent_question_review.py`、新小型 QA response helper（如需）、对应 transport/cache/batch 测试。旧 reconciliation._review_response 与 v5/v6 的原件身份保留。

- [x] 从旧实际响应确认坏行和合法同行身份，新增两合法+一坏 digest、重复 ID、外批 ID、重键、未知字段、错 basis/version/非列表等正反例。
- [x] 新协议 v7 单行 Pydantic 严格验证；envelope、重复/外批身份等全局失真仍整批拒绝。某行 schema 不合法则仅该行 pending，合法同行保留其真实输出；不修写模型字段，不覆盖负面意见。
- [x] 执行与重放共用同一 parser，缓存绑定新 SYS/版本和完整真实输入输出；旧缓存不复用。错误/缺席行按原尝试额度续审，已合法行不重复调用。
- [x] 续审只使用本轮剩余六批窗口：先完成所有初次已排队项，再重试已真实发送且成功返回响应、但格式/身份无效或合法 envelope 缺席的项目，每项累计最多两次；有效 keep 也不重试。未发送的预算/上下文失败不在同轮空转；timeout/transport failure 保留现有可恢复行为，不在同轮额外重发，取消立即停止。每个真实批次及有效/无效项目独立保留并回放。
- [x] Receipt 明确 invalid/valid 项，不把原始意见与合法结果混为一谈；无原文、未送审仍未验。
- [x] 新 v7 提示明确区分“题设背景日期”与“被询问/被来源限定的日期政策”：前者不能自动变成额外待证明的产品规则；明确上限仅支持该上限与题设下的有界否定，不证明更广运行时行为。保留真实日期例外/缺前提/未答分支和 structural diagnostic_only 的阻断。必要澄清可合格 partial，但不能因此清除独立结构问题；禁止由服务器覆盖模型 keep。
- [x] 规格审查、代码质量审查。

## Task 4：最终正文验收

- [x] 冻结新代码、旧原件 lock 与固定资料；跑相关回归及必要完整后端，不覆盖上一轮评分或原件。
- [x] 同原八题、同固定官网页和同模型配置跑四家真实阶段回放。不是新抓取、不是完整 Graph/发布、不是盲测，不假称锁定供应商权重版本。
- [x] 独立逐题检查 report.md：规则、场景推论、每个子问、准确引用、缺项是否如实。分别计全文题/必要分支/主张完整支持/原子性/QA。必要澄清保持 partial。
- [ ] 保留真实失败；若报告仍不合格，明确阻断层与下一步，不修改评分迎合结果。更新交付文档与 Agent 执行说明后精确提交现有分支。

## 复验后追加 Task 5：已审核答案被服务端守卫误拒

本轮四家原件已保存，初步定位到实际响应而非推测：Trello 的许可不推出义务已生成并审核，却以 `answer_subquestion_negative_unproven` 拒绝；Bitwarden 明确容量结论遭同类拒绝；1Password 完整规则已发表，但尾答的合法上限推论被标为 `explicit_negative`，分段引文另遗漏一个逗号，整题被拒。Trello 部分已答分支也因错误选择不适用的澄清字段而全部降为未核实。原始失败须保留。

- [ ] 先只读原件重建 GEN→REVIEW→ANSWER→guard→正文，分别确认模型错误、有限规则识别和整项回退的位置；不得把模型自报supported当作服务端有效审核。
- [ ] 对已证明的通用有限语言形态补先红后绿回归，不硬编码产品/题目。仅允许可验证的同单位上限、许可不推出义务以及原题片段之间纯分隔标点的完整恢复；未知条件、对象错位、外层否定、文本遗漏、歧义、跨题拼接继续拒绝。禁止把错误关系标签自动当成任意合理推论。
- [ ] 保留合法局部结果的身份，不能因一个不适用澄清字段抹掉已审核、已绑定分支；未完成分支仍明确partial，不能升级整题answered。历史回放须按其真实身份保持原行为，必要时新增显式协议，不用改旧原件补验。
- [ ] 实现前冻结本轮原件与评分；独立规格审查和代码质量审查后，先离线完整生产重放核对最终正文，再决定最小必要的真实模型复验。不能只测regex/helper或放宽评分。已知CPU计费和公开报价遗漏仍另列未完成，不借本修复宣称报告整体合格。

验证命令模板（具体文件随任务 handoff 明列）：
```sh
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest <任务测试文件> -q
```
