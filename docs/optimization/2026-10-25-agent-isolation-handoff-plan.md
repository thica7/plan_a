# 子 Agent 隔离验收与实际交付实施计划

> 使用 subagent-driven-development，先规格、后质量审查。用户已批准上一轮提出的隔离验收、交付修复及固定资料对照方向，本轮直接执行。复用现有隔离工作树 `codex/pastoral-desktop`，基线 `4165b0418f12920bd1ef3eff7304d29f983838b1`。

**目标：** 区分各 Agent 的功能失败与交接失败，修复实验 Writer 缺少真实上游产物及共享题设的问题，用同模型、封存资料比较单 Agent 和流水线的内容及成本。

**架构：** 保留现有 LangGraph、模型适配器、规范证据与独立 QA。在实验任务入口显式传递已验证的上游建议和服务器恢复的原始请求上下文；建议不能成为产品事实，题设只能作为条件。隔离测试分为生产入口合同测试和实际模型请求重放，分别报告。完整流水线与单 Agent 比较单列共享采集成本及新增调用，固定原八题分母。

**技术栈：** Python、Pydantic、pytest、现有 RunService / DoubaoClient、封存官方页面和哈希锁。暂不训练、安装新框架、运行 Docker 或抓新网页。实验仍默认关闭。

## 选择与边界

采用现有框架内的明确交付合同；整体迁移研究框架会混入大量变量，单纯补提示无法证明产物真正送达。已完成只读定位：六次真实任务生成没有上游三字段；Trello内部下载／导出子问缺少同一原始请求的共享身份。离线基线相关97项通过，但未覆盖上述功能断点。

## 任务一：离线隔离复现与生产交付修复

**文件：**

- 修改 `backend/packages/agents/writer/task_execution.py`、`task_support_selection.py`：显式上游建议和父请求进入实际生成与任务审核，按实际发送记录依赖。
- 修改 `backend/packages/research/question_scope.py`：新增服务器派生父请求上下文 helper，保持现有问题文本、ID及返回格式不变。
- 必要修改 `backend/packages/agents/qa/question_context.py`、`independent_question_review.py` 与 Writer最终答复构造：重新核对父请求身份、完整题设和真实发送；旧收据保持可重放。
- 新建 `backend/tests/unit/test_task_context_handoff.py`；扩充 `test_writer_artifact_consumption.py`、`test_question_format_scope.py` 和实际QA重放测试。

- [x] 先写隔离入口红测：用既有 `writer_fixture` / `record_upstream` 给齐三个规范产物，捕获真实生成输入，断言包含分析、比较和反思；无实际transport时依赖必须为空。

```python
assert all(payload.get(key) for key in (
    "upstream_analysis", "comparison_assessment", "reflection_constraints"))
assert {d.kind for d in audit.upstream_dependencies} == {"analyst", "comparator", "reflector"}
```

- [x] 写共享前提红测：完整题设含身份、套餐、A/B设置，内部下载／导出问题只含代词；完整同一父请求应进入选择、生成、任务审核及最终问答/QA。不得借另一个原题或另一个产品的前提补齐。
- [x] 最小修复：从同产品的唯一原始请求恢复完整父文本及稳定身份，原问片段不改；歧义不得默选。上游建议仅使用既有经验证、限定产品／维度／快照的内容，发送前预留完整上下文空间，超界明确延期，不裁来源前提。
- [x] 核验实际消息及不可变绑定；过期producer／快照、手动篡改、跨产品、上下文超界、零transport不得留下虚假的消费依赖。新上下文有明确版本，旧收据不能因新构造规则失效；保持24次／80000 token和旧checkpoint。
- [x] 跑任务生成、原子主张、请求前提、逐题审核、旧收据和QA回放回归。规格通过后独立质量审查，修复确定问题。

## 任务二：隔离与单 Agent 对照工具

**文件：** 新建 `backend/scripts/eval_agent_isolation.py`、`backend/tests/unit/test_agent_isolation_eval.py`，复用已有官方回放及LLM适配器。

- [x] TDD验证预检不读凭据、不调模型，输入只包含问题／来源／官方正文／实际生产请求，禁止参考答案进入runtime。只有显式 `--live` 才运行，输出目录不得存在，输入和源码哈希变更拒绝。
- [x] 在受控回放中保存模型实际system/user/采样参数/输出上限及请求哈希，剔除headers和凭据。Planner仅验证既定产品／资料范围的生产规划提示与返回，单独标记未验证自动发现和目标网页搜索。对Planner、Collector、Analyst、Comparator、Reflector、Writer、QA各选一份请求，用相同模型和参数独立重放；结果必须标记为“模型请求隔离”，不能冒充全部工具/解析/持久化闭环验收。生产入口离线测试另列。
- [x] 单 Agent 接收同批已采规范证据和完整原始问题，直接形成带来源的报告；完整流水线跑Collector至QA。记录证据覆盖差异，不声称输入完全相同或因果证明多Agent优劣。单列采集共享成本、直接生成新增成本、流水线总成本、未知usage、超时与截断。
- [x] 原八题标签与答案仅由后续独立审计加载；保留每次失败、全部实际调用及原始结果，不覆盖历史文件。

## 任务三：固定资料实跑及交付

- [x] 新忽略目录 `data/artifacts/agent-isolation-handoff-2026-10-25/`，复用2026-10-21页面锁，封存此前144份六类原件SHA。
- [x] 最终全后端、变更Ruff和diff检查通过后冻结同版源码；使用当前配置的同一个模型别名及固定采样参数，执行四家流水线、单Agent对照、七类请求隔离。不得自动切换供应商或增加重试凑通过。
- [x] 逐题核对内容、完整所选引用、共享前提及交付链，固定原8分母。隔离成功不授予整份报告合格，合法JSON/引用身份不代替语义。
- [x] 更新README、Agent执行说明及交付MD／JSON，记录各Agent通过、失败或未验项。
- [ ] 按既有授权提交推送现有分支并精确核对远端SHA；此项以Git提交记录及交付回复中的远端核对为准。

## 验证命令

```sh
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_task_context_handoff.py backend/tests/unit/test_writer_artifact_consumption.py backend/tests/unit/test_question_task_execution.py backend/tests/unit/test_question_format_scope.py backend/tests/unit/test_subquestion_premises.py backend/tests/unit/test_task_delivery_replay.py -q --tb=short
```

新增回归应先观察预期失败再实现。最终运行同一离线环境下 `pytest backend/tests -q --tb=short`；诊断工具预检保持零模型调用，真实测试必须显式启用并保存所有结果。报告未达标时保留默认关闭和准确的失败归因。

## 首轮真实规模问题与必要补充

首轮4家73次实际调用完成后，发现小fixture未覆盖的交接规模问题：Trello的Comparator、Reflector有效产物因整体超过角色字节配额而未进入Writer，仅Analyst送达。另Bitwarden单Agent同批完整规范资料因重复字段超过保守80000预算而零transport阻断；1Password两个生成输入被现有合规脱敏成占位，保持未验，不关闭脱敏。

- [x] 在原角色配额和总预算内，对比较与反思选择完整条目，标注省略，校验当前producer身份；不让建议变为事实，不截条件或修改模型判断。
- [x] 单Agent输入仅做可回放证明等价的无损共享文本去重，保留全部规范事实、qualifier及原题；超界仍拒绝，不提高预算。
- [x] 再次规格/质量审查和全量验证后，在新目录追加四家同版最终回放、四个single与七类模型请求隔离；首轮原件和所有调用均保留，未靠重试凑通过。

## 真实容量回归的必要修复

第二版同版四家阶段回放已完成，55次实际调用／150679 provider token；四个单 Agent 和七类请求隔离均已执行。Trello 的11个任务在选证 transport 前全部被记为 `task_evidence_unavailable`，没有实际生成；这属于交付功能回归，不能误称官网缺证或模型拒答。保留第二版全部结果及24份六类原件哈希，先离线重建精确容量，再作最小修复。其他模型语义失败不在本轮无限重跑。

- [x] 分开候选选证与已选证据写作所需的上下文容量；真实完整父前提保留，上游建议在真实写作／审核送达并重验，不提高总额度或裁断原文。
- [x] 先以真实规模反例观察失败，再修复并经过规格、质量审查和必要回归；旧两版失败与成本全部记录。
- [x] 如源码因此变化，用追加目录完成最终四家同版回放及相应对照；明确上一版模型隔离的版本，不混成同版结论。

## 同行拆题的父前提绑定补正

两阶段源码在四家回放中已真正送达上游建议，但Trello的投票义务子问仍未绑定父请求：原行是“？请将……”，`research_questions`分组时构造为“？ 请将……”，唯一差异是服务器插入的ASCII空格。仅检查原文子串遗漏了这类服务器自身产物。它属于共享前提交付缺陷，不能据同批有父文本就宣称该子问已绑定。

- [x] 抽出并复用原有split/group纯逻辑，仅以同一原始行能精确产生的完整canonical子问补充唯一父匹配；保持公开子问全文／ID、原始父文本、同产品和歧义边界，不跨行或做任意空白模糊匹配。
- [x] 父上下文第2版使用固定SYSTEM代际，新生成绑定同代审核；旧无此标记的真实第1版按旧规则重建，保留旧unbound收据，不信JSON自述降级。
- [x] 红绿测试、独立规格／质量及全量回归后，使用 `-acceptance` 新目录进行同版对照。保留第三版四家67次实际调用／190700 token，以及前两版全部失败和成本。

## 最终验收结论

实现和固定资料诊断已完成，完整报告仍未达交付标准，实验默认关闭。最终7656通过／1跳过；流水线原八题3通过／5部分，single6通过／2部分。独立内容审计已完成，非盲、非全Graph、未训练。详见[交付记录](2026-10-25-agent-isolation-handoff.md)及[结构化结果](2026-10-25-agent-isolation-handoff-results.json)。
