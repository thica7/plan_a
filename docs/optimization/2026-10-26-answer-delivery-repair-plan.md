# 已采证据到最终答案的交付修复计划

> 按用户确认的优先级执行；使用 subagent-driven-development 逐项实施，先规格审查，再代码质量审查。沿用当前隔离工作树，不训练模型，不改生产实验开关默认值。

**目标：** 修复上一轮真实失败，直接验收最终正文的逐项回答、合理推论及 QA 状态一致性。

**基线：** `9334bacdd500204cc4962be45a2e2a7cf620c82f`，八题2完整通过，四报告0达标。旧原件、审核标准和评分不变。

**架构：** 保留现有逐题生成、逐主张审核和最终 QA 三个入口。只在已有完整原文、明确任务与真实审核之内修复交付；格式恢复不能替代语义支持，题设不能变成产品事实，失败保持局部并可重放。

**技术：** Python、pytest、现有生产 evidence snapshot / Writer / QA，固定官方资料与已配置模型。

## Task 1：选证和原文见证的可靠交付

文件范围：`backend/packages/agents/writer/atomic_claim_review.py`、`readable_support.py`、`question_atomic_delivery.py`，必要时新增小型支持恢复模块；对应单元与真实记录回归测试。

- [x] 先增加失败测试：同一原文的多引用、同文不同条件、操作与非操作引用、NBSP/普通空白见证、不完整原句、跨来源和错引均有独立反例。
- [x] 在固定旧记录复现 Trello 双引用和见证丢失，记录拒绝发生层；使用现有完整绑定，不能把同文视为同条件。
- [x] 最小实现：只恢复可以唯一定位到已选完整原文的无语义空白差异；合法支持身份不变化。无法证明等价的多引用应局部给生成端明确修复反馈，而不是静默合并。
- [x] 提示与协议行为变更须隔离版本，旧请求按旧版本回放；不能事后改签模型原始请求或响应。
- [x] 执行相关测试并做规格、质量双审。

测试命令：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_atomic_claim_review.py backend/tests/unit/test_atomic_question_projection.py backend/tests/unit/test_question_atomic_delivery.py -q`。

## Task 2：规则、题设与场景结论的实际发表

文件范围：`backend/packages/agents/writer/atomic_question_projection.py`、`subquestion_premises.py`、`answer_resolution.py`、`answer_coverage.py` 和最小调用接线；对应任务、回答和最终渲染测试。

- [x] 先增加失败测试：数字上限与实际需求、A/B独立权限、许可不推出义务；验证正文明确回答当前场景，且保留共同前提。
- [x] 追踪已支持 claim 到 ANSWER、guard、render 的丢失；不得把格式校验放宽当作事实正确。
- [x] 让逐任务生成明确区分来源规则和条件推论，保留引用及 task ID；任务失败局部修复，已支持分支保留，不全篇重写。
- [x] 对有限且可核的推论保留来源规则和题设关系；未知作用域、单位、对象或例外不能输出肯定/否定场景结论。
- [x] 正文、回答状态和子问记录使用同一已审核结论；未知分支明确标缺口。
- [x] 执行最终正文断言及规格、质量双审。

测试要求示例：`assert required_branch_text in report_md`；同时断言 `coverage_resolution_reasons(...) == ()`，并用条件缺失/对象更换反例证明不会误放。

## Task 3：最终 QA 的问题归属与澄清一致性

文件范围：`backend/packages/agents/qa/independent_question_review.py`、`question_context.py` 和最小共用问答合同；对应独立 QA / clarification / reconciliation 测试。

- [x] 先增加失败测试：必要澄清已完整发表但仍待用户输入、价格题串到权限题、许可不代表义务、已知规则与未知报价同时存在。
- [x] 修复问题级输入与判定指导；当前题的理由不能借兄弟题，合法 wire 不等于语义通过。
- [x] 必要澄清可记为合理局部交付，保持 partial，不假装问题事实已回答；非必要澄清或遗漏真实分支继续阻断。
- [x] 新行为用独立协议/缓存身份，保持历史回放和未知限制失败关闭。
- [x] 执行规格、质量双审。

实施边界：新版独立 QA 每批只包含同一 `question_id`，未映射历史问题独立成组。采用直接可读的完整 JSON，不再要求模型展开递归表引用；旧 v5 编解码与历史请求保持只读。新协议及缓存身份分离，先按 8192 字节完整上下文上限测量（仍受实际 EvidenceUse 限额约束），保留六批、两次尝试、整项未送审记录。预留预算随真实 SYS 和请求上限重新计算。必要澄清只按服务端已有严格合同标明类型，不能由一个新增标签证明事实正确；真实模型仍可保留阻断。若完整上下文无法装入，不裁条件或借兄弟题。

预算接线：`llm_execution.py` 现有 final_qa 新建预留的 15% 截断在 80000 配置下仅给12000，小于完整新请求13685。仅修新建阶段的所需预留值，已有持久化阶段和旧额度不抬高、不重置；用真实请求准入与旧checkpoint反例核验。

同题多 finding 若重复完整上下文，会把原可送审的项目挤出六批额度；可采用单层、明确命名的同题上下文与独立 finding 列表。模型直接读取完整上下文，不展开递归索引。仍逐项绑定实际请求、当前正文及独立审核结果，不借不同题的内容，不用上下文共享宣称语义正确。

## Task 4：冻结验证与如实交付

- [x] 运行相关回归、Ruff 与完整后端；新增测试需看到修复前失败，记录红绿证据。
- [x] 保存本轮独立目录及源码冻结、固定资料与旧原件锁；不覆盖历史原件或改历史评分。
- [x] 在冻结代码上重跑四家真实阶段与隔离诊断，检查最终正文每个必要分支。若底层输入被脱敏则标未验，不凭重建哈希补验。
- [x] 独立审核正文与引用；分别报告完整题、必要分支、主张支持、QA状态和执行范围。不以单元测试通过替代文本验收。
- [x] 更新 README、Agent 执行说明与本轮交付文档。仅在确认的范围提交推送，报告仍不合格时如实说明。

提交说明：本计划中的工程、测试和文档步骤已完成。报告内容验收仍未通过，见交付文档；Git 提交推送结果另存本机 release-verification.json，不把内容不合格记为完成用户目标。
