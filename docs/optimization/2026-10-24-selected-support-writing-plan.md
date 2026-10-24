# 已采证据选用、原子写作与剩余QA调度计划

> 用户已批准继续实施；基线 `db0713ae`，复用现有工作树。使用 systematic-debugging、writing-plans、TDD 与 subagent-driven-development：Writer选证／写作和最终QA可以独立实施，再做规格与质量审查。暂不训练模型，实验默认关闭。

**目标：** 将已在真实窗口中的资料按任务选择并写成有完整支持的最小主张，减少错误引用和额外谓词；最终QA明确身份回显并有界推进剩余检查，最后按原八题验收四家。

**架构：** 保留来源准入、完整原题、精确span／operation绑定及独立审核。Writer先做有界的任务选证，再在该任务选中支持范围写作；选择仅为候选，不授予事实资格。QA保留当前整题资格，显式给出需要回显的整题claim IDs，局部task支持分开表达。剩余检查按实际载荷、已审核缓存与剩余预算分批派送，全部失败及未送留痕；全局24调用／80k上限不提高。

## 1. Writer选证与原子生成（独立实施）

文件：`backend/packages/agents/writer/task_execution.py`、必要时新增单一职责 `task_support_selection.py`，已有规范目录在 `readable_support.py`；测试新增 `backend/tests/unit/test_task_support_selection.py` 并回归任务执行／投影。

- [x] 从封存轨迹复现：同一任务窗有多个可用原句，但初稿／修复引用私人库原句又添加邀请／升级；角色规则使用s-reference导致operation_binding_required。写失败测试，不把产品名或参考答案写入功能。
- [x] 给每批任务增加有界引用选择；只允许选择实际派送规范目录的ref，逐任务记录选证输入／输出与ID。完整条件保留；非法／外国／遗漏引用不能变成事实。
- [x] 生成阶段按任务的所选完整支持和正确绑定形式写单一谓词，禁止从其余父句／兄弟原句附加解释。选择不合格或预算不足明确延期，不能将默认推荐ref当通过。
- [x] 沿原逐条解析与独立审核，修复仅使用同任务失败原因和实际支持；成功同行不丢失。附加选证调用遵守原阶段与全局预算，不增加总上限。
- [x] 离线红绿、真实Writer adapter、规范派送与QA投影重放回归；独立规格／质量审查。

## 2. QA回显与剩余调度（主任务）

文件：`backend/packages/agents/qa/independent_question_review.py`、`question_reconciliation.py`，必要接入 `backend/packages/orchestrator/llm_execution.py`；新增 `backend/tests/unit/test_remaining_question_review.py`，回归原独立QA及预算测试。

- [x] 先写失败测试：整题answer.claim_ids为空而局部task有claim，审核载荷缺明确待回显ID；两批后有可发剩余项却当前调用不再推进。
- [x] 增加显式 `expected_claim_ids`，仍严格等于当前answer.claim_ids；task支持身份独立展示。错ID、跨题引用、摘要不匹配不能通过；诊断不解除blocker，旧legacy入口不变。
- [x] 完整题目优先于历史问题；对尚未完成的窗口有界推进，跳过合法缓存，先覆盖未送再考虑失败重试，同一依据每项仍最多两次实际请求。预算或容量不足保留具体原因，不裁引文、不永久缓存为完成。
- [x] 保留真实transport／合法返回／超时／未送集合、未知usage保守扣账及checkpoint。阶段完成后再释放最终预留；必要调整预留只在全局24／80k之内，旧checkpoint不压缩。
- 预算细化：新运行最终QA按完整system＋6000B user＋256余量＋1600输出的真实上界保护（当前11000），取代不覆盖完整请求的10k估计；旧明确10k／18k checkpoint仍原样，answer12k与全局80k不变。新basis重审只撤销旧finished标记，不清零已有调用或用量。
- [x] 离线红绿与真实adapter故障／恢复／多窗测试，独立规格／质量审查。

## 3. 最终验证和交付

- [x] 全后端测试、变更Ruff与独立最终差异审查。
- [x] 冻结源码，复制既有锁定回放runner到新的Git忽略阶段目录；四家使用2026-10-21封存官方页和原八题，参考答案不进模型。不是新抓取、竞品发现、全Graph或生产RAG验收。
- [x] 独立审读实际正文、每条所选支持、前提／模态和全部任务。明确原八题分母，保留预算拒绝、模型失效、超时和未送；测试通过不能替代报告合格。
- [x] 更新README、Agent执行说明、结构化结果与交付文档；沿既有授权提交推送，核对远端SHA及干净工作区。只有真实证据支持才能改变实验默认状态。

实施与验证完成不等于报告通过：后端7469通过／1跳过；四家同版真实回放62调用／187976 token，原八题严格仍3/8。QA29项中28项合法，1P访客单题超6KB未送；可见主张完整支持8/8、单谓词3/8，保持默认关闭、未训练。交付与推送核对见[本轮交付记录](2026-10-24-selected-support-writing.md)。
