# 分析依赖与四家六项操作覆盖实施计划

> 使用 executing-plans 按步骤执行。用户已批准“先修回退依赖，再缺口补证、均衡写作并完整验收”。保留当前工作树中的此前改动。

**Goal:** 消除有效分析产物被上下文容量误判为失效，让采集、补证与报告围绕四家六项操作，重跑真实流程核对交付标准。

**Architecture:** 对相同条件使用当前消费视图内的无损引用，保持原始依赖hash与凭据校验。采集先读已登记官方文档，剩余搜索预算用于缺口；写作每项操作优先一条完整观察并限制重复评论。所有事实仍须通过原文准入及逐条审核。

**Tech Stack:** Python、Pydantic、LangGraph、DeepSeek、pytest。

## 1. 分析依赖根因与回归

文件：`backend/packages/research/evidence/snapshot_models.py`、`backend/packages/orchestrator/evidence_context.py`；测试新增 `backend/tests/unit/test_operation_coverage.py`。

- [x] 用上一轮v5脱敏产物离线重放，逐项检查payload hash、producer credential及比较视图子集。
- [x] 写失败测试：四个有效producer的操作conditions在三个fact字段中重复，比较视图仍应覆盖全部实际producer事实；真正修改payload/hash继续拒绝。
- [x] `PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_operation_coverage.py -q`，观察正确失败。
- [x] 比较/反思阶段复用现有`qualifier_sets`协议去掉相同条件重复；按view内refs还原完整对象，不扩大模型总额度或放松生产凭据校验。若仍有容量遗漏，报告为context遗漏并不复用不可见分析，而非要求错误重分析。
- [x] 复跑依赖/阶段视图/集成测试，验证真实篡改仍拒绝。

## 2. 按缺口采集

文件：`research/pipeline.py`、`research/discovery/planner.py`、`research/capture/selection.py`、`agents/collectors/logic.py`、`orchestrator/llm_execution.py`、`business_intel/entity_resolver.py`。

- [x] 测试已知官方文档先捕获、操作缺口成为repair依据；搜索仍不超过原max_search_queries，fetch不超过原max_fetches。
- [x] 给每家功能语义提取预留额度，沿用writer/qa保护，总200000 token不增加。阶段完成释放预留。
- [x] 根据请求操作优先角色/权限、分享、创建等文档；核验官方URL并扩充角色、权限与分享文档入口。保留非本任务的普通采集流程。
- [x] 对长官方文档选择包含角色、否定和权限的原文窗口；模型选择与admission用同一服务端窗口，quote仍以原文位置精确验证，不能跨角色拼接。
- [x] 运行预算、collector、pipeline、semantic准入测试。

## 3. 均衡写作

文件：`agents/writer/dimension_writer.py`、`research/evidence/operations.py`；测试 `test_operation_coverage.py`。

- [x] 写失败样本：多条评论菜单操作+一条编辑和一条分享，报告输入不应被评论填满。
- [x] 每项请求操作优先一个完整对象与条件观察；缺少的操作明确保留缺口，不用评论或按钮填充。
- [x] 模型根据操作目标写原子主张，服务端排除同操作重复和UI步骤对文档编辑/分享的冒充。引用和条件审核不放宽。
- [x] 复跑writer/audit/操作投影测试。

## 4. 完整验收

- [x] 独立代码审查与后端全量回归。
- [x] `backend/scripts/eval_live_products.py --cases eval/operation-comparison-v1.jsonl --case operations-four-products --output /tmp/plan_a_operation_coverage_live_v1 --live`，不提高单任务额度。
- [x] 核对24个产品×操作单元的来源、正文观察、角色/套餐/对象/前提、审核状态，以及分析依赖和预算。completed状态不代替交付判定。
- [x] 保存脱敏原始草稿、交付结果与SHA；检查凭据未进入文档、diff无空白错误。

## 真实复验发现及修正

首轮 completed 未达交付标准。增加红绿回归并修复 `won’t` 否定识别、中文引用角色标签被当操作、中文带限定语的阅读匹配。显式操作写作优先肯定观察并绑定服务端 fact_targets；操作表每格仅展示一条优先观察，取消重复旧能力表。保持缺口及逐条引用审核。最终v4完整验收结束：3548项后端测试通过，24格来源观察18格、正文观察14格、完整条件0格。完整比较未达交付标准；结果与剩余缺口见同日operation-coverage-results.md。
