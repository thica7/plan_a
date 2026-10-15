# 写作预算与结构化操作证据实施计划

> 使用 executing-plans 按步骤实施；用户已批准此方向。沿用当前工作树，保留此前改动。

**目标：** 在既有 60 次 / 200000 token 额度内保护四家写作和逐条审核，完善原文绑定的操作对象与条件，再跑固定四家真实流程。

**架构：** 只有现有按维度写作路径启用交付预留；按产品与维度保护 writer/qa 调用，未启动的请求不收费，已启动但 usage 未知仍保守扣费。结构化操作由服务端从已准入原文及局部标题确定性生成，模型只选择完整原文，不用模型推断填补未知。

**技术栈：** Python、Pydantic、LangGraph、DeepSeek、pytest。

## 1. 预算调度

文件：`backend/packages/llm/execution_budget.py`、`orchestrator/llm_execution.py`、`orchestrator/search_execution.py`、`agents/analysts/logic.py`。

- [x] 写失败测试：`RunLLMBudget(..., delivery_reserves={'writer:A/feature':16000, 'qa:A/feature':16000})` 应阻止上游消费预留，允许 writer 使用自己的额度；并发结算、usage 未知、重试和恢复均不绕过总额。
- [x] 执行 `PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_delivery_budget.py -q`，确认新行为缺失。
- [x] 添加按阶段保护的 token/call/cost 额度和持久化状态。准入比较当前请求加其他阶段剩余预留，writer 完成释放自己的剩余预留，审核结束释放 qa。
- [x] 原生搜索在交付保护触发时返回空候选并记录原因；analyst 对同一保护原因使用现有确定性源证据回退，凭据错误仍抛出。
- [x] 再运行预算、搜索、agent 集成测试，确认总额与恢复规则不变。

## 2. 有界写作上下文

文件：`backend/packages/agents/writer/dimension_writer.py`。

- [x] 测试只发送当前允许的 feature evidence_terms，保留完整原文和前提，去掉重复 slot/status 及无关矩阵；超长完整观察留为缺口。
- [x] 生成最多 8 条完整证据观察的紧凑模型输入，审核仍绑定完整原始视图；分段完成后释放预留。
- [x] 测试四家均有写作和审核调用，未审核主张不发表。

## 3. 操作对象与前提

文件：`research/evidence/operations.py`、`research/extraction/semantic.py`、`research/models.py`、`research/evidence/normalization.py`。

- [x] 添加反例：编辑评论不能视为编辑文档；工作区角色不等于工作区操作对象；父级/分享前提不跨角色继承；缺套餐保留未知。
- [x] 从准入的完整 quote、局部标题和条件生成 operation/effect/object/role/plan/prerequisite 原文片段结构；经现有 admission 重算并严格相等核验后入库，再随 qualifiers 到 snapshot。
- [x] 检索缺口、矩阵和正文消费同一结构，旧快照继续支持现有正则回退。
- [x] 运行语义准入、操作比较、投影、写作测试。

## 4. 验收与文档

- [x] 后端完整回归；复用代码审查 agent 独立检查预算恢复及证据完整性。
- [x] 使用 `backend/scripts/eval_live_products.py --cases eval/operation-comparison-v1.jsonl --case operations-four-products --output /tmp/plan_a_delivery_budget_live_v1` 进行真实验收，不增加总额度。
- [x] 核对四家审核覆盖、六项同操作覆盖、引用、保留条件、预算保护及最终状态；区分流程完成、事实稿可用、完整比较交付，不将机械状态作为交付标准。
- [x] 保存脱敏结果与交付文档；扫描凭据、核对 diff。此前变更跨多轮，未经整体交付梳理不自动打包提交。

## 执行记录

已完成实施、独立审查、五次真实运行及最终全量回归。执行完成不等于六项同口径比较交付通过，详见本轮results文档。真实发现的单条审核格式异常已纳入严格逐条解析；已知表格行泛化有服务端约束。
