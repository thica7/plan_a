# 引用、金额与 Agentic RL 数据准备实施计划

> 按用户刚确认的方案继续实施。使用 systematic-debugging、writing-plans、TDD、dispatching-parallel-agents 和独立代码审查；复用 `codex/pastoral-desktop` 隔离工作区。不训练、不下载权重、不运行 Docker。新候选参考与实现隔离，用户确认前不作正式验收。

**Goal:** 修复回答与已审核主张的绑定、区分赠送 credits 与实际报价，输出可审计的成功/失败/合理拒答轨迹候选及独立人审题。

**Architecture:** 复用已发表主张、生成消费凭据、准入快照及现有金额边界。新回答选择合同由服务器投影完整正文与引用，历史旧合同只保留兼容读取，新 live 合同强制 v2。额度允许范围只来自已引用且已放行原文，不进入采购现价事实。轨迹为诊断数据，候选标签与真实性奖励分开。

**Tech Stack:** Python / Pydantic / pytest、现有 Research/Writer/QA、脱敏 artifact、官方来源候选；不新增运行服务。

## 1. 回答选择与引用绑定

文件：`agents/writer/answer_coverage.py`、`dimension_writer.py`、必要 `answer_resolution.py`；新增匿名测试。

- [x] 匿名 RED：并行 ID/span 漏项仍拒绝；新合同多主张不丢条件；重复/未知 ID、600 字片段和 1200 字答复超限保留未核实。
- [x] 新模型响应为 `{"version":2,"answers":[{"question_id":"q","status":"answered","claim_ids":["c1"],"resolution":"direct","conclusion":"no","missing_fields":[],"reason":"selection rationale"}]}`。不接受模型另写 `answer`、`evidence_spans`、问题或快照身份。
- [x] 每个 ID 必须对应本次已审核发表主张，服务器生成 `answer = "\n".join(claim.text)` 与每 ID 的完整 `evidence_spans`，不删除引用、不截句、不拼新事实。未知或超限整行未核实。legacy envelope 只给历史读取；新模型入口拒绝降级。
- [x] Writer 对显式问题优先生成直接或条件主张；操作逐条选合法 observation_id，保留角色、套餐和访问前提。禁止为减少漏填而猜测操作绑定。
- [x] 增加通用中文/英文否定包含断言识别，保留对象、角色、套餐、日期与消费重放检查。
- [x] 生产入口与最终 QA 重放都执行相同合同。既有 Miro 工具栏引用不能继续替代套餐规则。

## 2. 金额语义分类

文件：`orchestrator/answer_context.py`，新窄范围 `research/evidence` helper，必要 claim 审核接线；新增匿名测试。

- [x] 匿名 RED：完整赠送额度原文已准入且被引仍误拦；同一文档不同套餐金额不能串用。
- [x] 区分 `credit_allowance / purchase_price / unknown`，按具体金额、原文语法、套餐、周期和 credits 单位绑定，不凭文中出现 credits 豁免所有金额。
- [x] 只有当前生成视图中已放行、已引用的完整来源观察可支持额度表述；无引用、拒绝/过期来源、换套餐/周期/币种、把额度写成费用继续拒绝。
- [x] `Pro costs $20/month and includes credits` 的 $20 仍是价格；真实采购价缺市场、税费、周期等条件仍需澄清或不足答复。不要扩大 `_is_money` / `_money_value` 把额度充作采购价。
- [x] 逐主张审核和最终 QA 使用可重放规则；不关闭金额门禁，不增加产品特判。

## 3. 脱敏轨迹候选

文件：新 `backend/scripts/prepare_agent_readiness.py` 与 `tests/unit/test_agent_readiness_export.py`；新 `eval/agent-readiness-trajectory-review-v1-candidate.json`。

- [x] 匿名 RED：Demo/跨工作区拒绝；密钥/个人信息脱敏；缺标签保持 unlabelled；截断明确标记；同产品/文档/重跑不跨 development 与 holdout。
- [x] API `prepare_readiness(artifact_dirs, *, workspace, annotations=()) -> dict` 只读已保存 run/trace/summary/manifest，登记输入哈希，不调用模型、不迁移数据库。动作复用现有 `export_agent_eval` 的脱敏逻辑。
- [x] 每个记录标明 `unit=question_episode`、run/project/问题/消费身份、候选类别、绑定与 QA 状态、轨迹摘要及省略计数、源码版本和来源身份。任务整体通过与单题成功分开。
- [x] 三类 `success / failure / reasonable_abstention` 由显式审核候选给出；候选标签不能自动变成人审标签，QA pass、run complete、代理点评不能生成真实性奖励。`reward.correctness=null`、`training_ready=false`。
- [x] 旧已曝光产品、所有重跑与当前调试资料只进入 development。CLI 输出 manifest 和按候选类别分组的 JSONL；原数据不改写，输出目录已存在则拒绝覆盖。

## 4. 独立候选及用户审核

专属文件：`eval/agent-readiness-holdout-v1-candidate.jsonl`、candidate manifest、runtime JSON；`docs/optimization/2026-10-18-agent-readiness-human-review.md`。

- [x] 独立构造者准备 4 个新产品共 8 题，覆盖可回答、条件限制、合理拒答和需澄清；仅采官方一手资料，保留时间、哈希、必要短节选。
- [x] 实现代理不读取新参考。修复冻结后才由 root 查看人审单；不根据候选答案修改代码。评测 runtime 只含问题与来源身份，剥离参考答案、节选及审核结论。
- [x] 用户未审核的题目维持 candidate，不能作为正式留出评测结果。当前旧样本全部已曝光；独立来源/产品隔离不等于可宣称未曝光盲测。
- [x] 人审单列出 8 道事实边界，以及旧轨迹中的成功、失败、合理拒答候选标签，请用户分别确认；不要求其准备 GPU。

## 5. 验证与交付

- [x] 各模块先 RED→GREEN、再相邻回归与独立规格/质量审查，最后完整后端与前端、API/类型核验。
- [x] 已曝光旧产物只读重放，保留原报告及失败。最终版本最多两次真实阶段诊断（优先 GitBook 和 Miro），每组 24 calls / 80000 token、输出 2048、Writer/审核 1600、问题评估 700、retry 0；不以工程通过代替正文验收。
- [x] 不在新未审核候选上生成正式模型报告，不运行训练或参数更新。独立题审核结果可异步到达，其余已授权工作继续。
- [x] 更新 README、Agent 执行说明和交付结果，扫描凭据；按既有授权提交推送当前开发分支，保留工作区。

关键复测：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests -q --tb=short`；前端 `pnpm --dir frontend test` 和 `pnpm --dir frontend build`。新增脚本先用匿名 fixture 验证只读、作用域、脱敏与候选标签，再整理真实 artifact。
