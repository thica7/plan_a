# Agent Prompt 与事实覆盖实施计划

> **For agentic workers:** Use executing-plans 在当前已隔离工作区逐项实施，使用 TDD，并在完成后使用 requesting-code-review 独立审查。

**Goal:** 统一 Writer 的实际模板调用，使对比可以表达不可比/证据不足，使 Collector 依据事实覆盖补采，并记录可复现的测试和小规模模型效果。

**Architecture:** 复用现有 WriterPromptBuilder、Evidence View、覆盖检查和 LLM 调用预算。对比结果新增可选结构化判定，旧报告保持可读；未知状态不进入赢家列表。共享证据规则只应用于本轮涉及的调用，所有原生调用记录实际提示词指纹。

**Tech Stack:** Python、Pydantic、pytest、现有 DeepSeek 客户端。

## 执行约束

- 用户已确认上一轮方案及依次实施，本计划直接执行。
- 不接触凭据内容，不改模型配置，不创建业务报告或修改知识库；模型评测使用固定非敏感测试证据。
- 保持局部修复、中文标题、出版修复指令、深度预算和来源快照校验。
- 离线回归与真实模型效果分别报告；真实模型不可用时明确记录未验收。

## Task 1：Writer 三条实际调用统一

**Files:** `backend/packages/agents/writer/prompt_builder.py`、`logic.py`；测试 `backend/tests/unit/test_writer_prompt_runtime.py`。

- [x] 写参数化测试，替换三个构造器返回唯一 system/user，调用真实初稿、分段、修复入口，断言传给 transport 的值来自构造器。

```python
@pytest.mark.parametrize('route', ['first_draft', 'segment', 'repair'])
async def test_actual_writer_uses_builder(route, monkeypatch):
    # 本地 RunService + RunRecord + 固定证据，拦截 transport。
    # 为对应构造器返回 WriterPrompt('builder-system', 'builder-user')。
    # 调用实际入口，断言捕获的 system/user 恰好相等。
    assert captured[-1]['system'] == 'builder-system'
    assert captured[-1]['user'] == 'builder-user'
```

- [x] 执行 `../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_writer_prompt_runtime.py -q`，确认三条调用未接线而失败。
- [x] 将内联 system/user 移到现有构造器。补齐 decision_brief、数值保真、缺失字段说明、中文标题、出版修复和 segment 长度参数；快模式仅要求紧凑报告。

```python
prompt = WriterPromptBuilder().first_draft_prompt(detail, ...)
result = await self._trace_llm_text(record, ..., system=prompt.system, user=prompt.user)
```

- [x] 运行上述测试及 `test_writer_prompt_builder.py`、`test_research_modes.py`、`test_pm_decision_brief.py`、`test_answer_guard_workflow.py`，确认已有约束仍生效。

## Task 2：对比判定与共享规则

**Files:** `backend/packages/agents/prompt_contract.py`、`comparator/prompt_builder.py`、`comparator/logic.py`、`backend/packages/schema/models.py`；测试 `backend/tests/unit/test_agent_prompt_contracts.py`。

- [x] 测试不同市场、计费周期和缺来源时不能产生赢家；真实持久化矩阵保留状态、理由、场景、取舍和来源。旧矩阵无新字段仍可加载。

```python
assert matrix.assessments['pricing'].status == 'not_comparable'
assert 'pricing' not in matrix.winner_by_dimension
```

- [x] 执行测试确认功能缺失失败。
- [x] 增加 ComparisonAssessment：`status` 为 comparable / insufficient_evidence / not_comparable；`winner` 可空，包含 rationale、scenario、tradeoffs、gaps、source_ids。共享规则：证据为数据、禁止网页指令改变角色、保留价格条件和数值、缺失不等于原文未披露。
- [x] Comparator Prompt 使用 decision brief 和实际 Evidence View；新判定不被来源数量投票重新覆盖，验证来源属于当前维度及产品；代码可比性检查仍有最终权威。
- [x] 检查 Writer 证据序列化能传递判定；运行新测试和已有 comparator/证据对齐回归。

## Task 3：Collector 事实覆盖和定向补采

**Files:** `backend/packages/research/coverage_contract.py`、`backend/packages/agents/collectors/logic.py`；测试 `backend/tests/unit/test_collector_fact_completion.py`。

- [x] 添加 HTTP 200 无价格、仅计费政策、无效引用绑定三个覆盖失败案例；已有有效价格应通过，并保留未知市场/税费条件。

```python
assert not coverage.passed
assert 'current_plan_price_support' in coverage.missing_intents
```

- [x] 执行测试，确认政策金额误判和提示词缺覆盖反馈的失败。
- [x] 价格覆盖必须有来自当前已接受页面、正确 candidate 绑定、非空价格字段的证据；政策页面本身不充当套餐金额。复用现有补采预算，将 coverage/missing/repair_hints 和剩余轮数传给 ReAct；fetch 成功无事实时不当作完成。
- [x] 运行覆盖、Collector、research pipeline 回归，确认循环有上限、来源仍需 pipeline 审核。

## Task 4：指纹与效果评测

**Files:** `backend/packages/orchestrator/llm_execution.py`、`backend/scripts/eval_agent_prompts.py`、`eval/agent-prompt-contract-v1.jsonl`；对应测试与 `docs/optimization/2026-10-07-agent-prompt-results.md`。

- [x] 测试 LLM span 存在 prompt_id、系统/Schema/完整调用哈希，改变输入会改变调用哈希。
- [x] 为原生 JSON/text 调用添加指纹；不把敏感配置写入日志。
- [x] 构造固定案例：市场不同、周期不同、缺价、未知产品、相同条件可比、来源不足、低置信度赢家、网页提示词注入。旧 Prompt 从基线提交读取，新增 Prompt 用生产构造器；相同模型、证据、温度、输出上限，各案例两个版本。
- [x] 评分报告记录 JSON 有效、正确判定、无无依据赢家、引用合法、Token 和失败；评分器用对抗输出测试，模型结果不冒充全工作流验收。
- [x] 运行相关测试和完整后端回归，使用 requesting-code-review 审查修改，处理重要问题，再交付事实、限制和后续事项。
