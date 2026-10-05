# 共享事实核验实施计划

> 执行技能：subagent-driven-development；每项先写失败测试，完成后依次审核规格与质量。已有独立工作树与现有codex/pastoral-desktop分支继续使用。用户已同意本设计对应的下一阶段，不再重复请求执行许可。

**目标：** Writer和QA共享证据完整性结果，离线验证部分回答、缺项和澄清。

**架构：** 纯函数检查StageEvidenceView，不取网络或数据库。新增可选计划要求和报告边界记录接入现有Writer/QA，不重构采集器或重训模型。

**技术：** Python、Pydantic、现有EvidenceSnapshot与RunService、隔离pytest。

## Task 1：共享核验内核与数据模型

创建：`backend/packages/research/evidence/answer_models.py`、`answer_guard.py`、`backend/tests/unit/test_answer_guard.py`。

接口约定：

```python
evaluate_answer_boundary(view: StageEvidenceView, requirement: AnswerRequirement) -> AnswerBoundary
```

AnswerRequirement包含competitor、dimension、intent（默认facts）、market、as_of（必填date）、context_json（默认对象字符串）。AnswerBoundary包含snapshot_id、requirement、status、allowed_fact_ids、withheld_fact_ids、missing_fields、clarification_fields、fact_decisions；所有结果不可变，JSON可序列化，JSON对象字段使用canonical_json。

- [x] 首先在测试中动态导入新模块，先观察缺功能的断言失败，而不是收集导入错误。
- [x] 写价格机制部分回答、旧发布价、错误市场/日期、完整结构化价及零金额、比较条件缺项、合规澄清、账单缺项、signal/冲突和范围错配的行为测试。
- [x] 实现上述纯函数，遵守设计中的价格字段、日期来源及每条事实/来源配对；请求context不会自动补成证据。
- [x] 通过隔离助手运行 `backend/tests/unit/test_answer_guard.py`，记录RED/GREEN。首次61项行为断言失败；比较规则追加9项失败、优惠条件1项失败、异常元数据15项失败；修复后独立111项通过。
- [x] 依次进行SPEC与QUALITY审查，修复明确问题后交付，不自行提交或推送。规格审查发现优惠条件遗漏，质量审查发现价格类型容器、布尔条件及窗口精度遗漏，已修复并复审通过。

## Task 2：Writer/QA接点与离线回放

修改：`backend/packages/schema/models.py`、`api_dto.py`；`backend/packages/agents/writer/evidence_alignment.py`、`backend/packages/agents/qa/evidence_alignment.py`；`backend/packages/orchestrator/evidence_context.py`。

创建：`backend/packages/orchestrator/answer_context.py`、`backend/tests/unit/test_answer_guard_workflow.py`。必要时在既有Writer提示构造中补充共享边界指令，避免字段出现在面向用户的正文。

- [x] 先写失败测试，证明实际Writer分段收到边界、边界纳入预算且超预算不丢条件，新报告记录边界并与producer一致，QA按同一快照及要求审计。
- [x] AnalysisPlan增加可选answer_requirements；RunDetail增加默认空的report_answer_boundaries。旧序列化可加载，新记录进入producer payload；仅在存在边界时添加该payload键，保持旧producer兼容。
- [x] answer_context按显式要求和维度创建保守默认范围，使用同一纯函数。Writer在本地投影上添加边界，纳入原预算；持久化生成边界。QA发现禁用金额或已声明的禁用事实/不完整结论时产生具体QCIssue，同时允许不带金额的方法/澄清/缺项说明。
- [x] 用固定本地证据和替代生成器回放四条审核的边界，不称作真实LLM答案准确率；运行新增测试与现有snapshot/Writer/QA相关测试。
- [x] 依次完成SPEC与QUALITY审查，修复问题；不读取真实.env、runs、知识库或客户账单。补齐币种前负号、币种登记、卡片金额与卡片单独引用撤源检查；48项工作流用例通过。

完整后端新增暴露2个引用规范化旧正例缺价格条件；仅在该集成测试内补结构化报价，保留原断言、全局fixture和生产守卫，62项集成用例通过。

## Task 3：验证与交付

- [x] 运行完整隔离后端，仅在测试需要临时子进程时使用已授权的权限；不与模型性能回放并行。2984通过、1项独立Postgres RLS未配置跳过。
- [x] 增量lint、冻结输入哈希、密钥扫描及Git差异检查，记录实际跳过项与限制。
- [x] 写同日交付文档，说明默认维度策略、显式要求的接入方式、已覆盖输出审计和剩余语义验证限制。

提交步骤：按既有授权提交并推送当前分支，核对远端SHA；不merge或操作main。此步骤在保存本交付commit后执行，具体提交与远端核对结果以会话最终回执为准。
