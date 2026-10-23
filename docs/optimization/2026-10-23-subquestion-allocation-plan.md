# 子问证据分配、独立主张与 QA 归属实施计划

> 用户已批准本轮方向。按 subagent-driven-development 执行独立任务并复核；复用 `codex/pastoral-desktop` 工作树，基线 `62d97d6`。实现前写失败测试，所有首次真实输出保留。

**目标：** 已准入资料按问题与独立动作分配，完整 CPU 计费行能进入实际消费；必要澄清不被其它问题的旧缺口误阻；复合主张在发表前拆成分别审核的原子。

**设计：** 保持原完整 fact、引用目录、条件、例外和依赖验证。先减少修复诊断的重复长评语，再将元数据与原文放进同一个实际压缩窗口，按子问分配完整支持和有限原子任务；被拒草稿及失败检查保留，评语仅作检索提示。表格检索优先完整同模式 CPU 行，不增加事实权威。QA 从已验证选择/派送身份恢复问题归属，仅允许精确必要澄清关闭自身的资料遗漏，事实和例外缺口继续阻断。共享调用/token预算、14KB上下文及Writer1600输出cap不增加，无自动重试，无训练。

**技术：** Python、Pydantic、pytest，现有真实模型适配器；不改前端或公有API。

## 1. 重放并锁定根因

- [x] 保存 Trello 全资料+修复诊断16544B装窗反例，核对诊断评语和原文各自成本，禁止截原文挤空间。
- [x] 从上一轮四家原始八题生成离线探针，记录 CPU 完整行、Trello scope/billing 与按对象回答的实际进入/遗漏身份。
- [x] 建立每问的成功条件：答案完整、可见整条断言受精确支持、独立动作分别审核、QA与最终问题结论一致。

## 2. 按子问分配与独立原子任务

文件：新增 `backend/packages/agents/writer/question_allocation.py` 与 `backend/tests/unit/test_question_allocation.py`；修改 `question_repair.py` 和必要的 `dimension_writer.py` 入口。

- [x] 红测试：两个子问分别需要独立动作和scope原文时，诊断长评语不能挤掉后者；失败草稿只带原文与失败检查，完整审核历史不删除。
- [x] 由原问识别有限动作/命名对象任务，分配真实派送支持引用；一任务一谓词，条件与例外完整保留。未识别表达仍由语义审核决定，不通过词项命中证明答案。
- [x] 初次至多8原子、局部修复至多4原子；按未覆盖任务优先级安排，不要求模型为超过容量的每个分支都写原子。超界保守拒绝并单列原因，不能静默取前4或绕过审核。
- [x] 保护 `can`/`must`、对象和投票条件；资料单句的沉默不能支持“整页没有义务”等全域缺席断言。新增原子逐条过原引用/条件/独立审核，原成功项不重写。

最小反例：
```python
tasks = question_atom_tasks([{"question_id": "q", "question": "他能下载附件并导出看板吗？"}])
assert {task["focus"] for task in tasks} == {"download", "export"}
assert len(tasks) == 2
```

命令：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_question_allocation.py backend/tests/unit/test_targeted_question_repair.py -q`；先观察功能缺失失败，再实现到绿。

## 3. CPU 行进入同一实际消费链

文件：`backend/packages/agents/writer/question_retrieval.py`；测试放 `test_question_allocation.py` 或新的单一职责测试文件。

- [x] 红测试：Standard完整CPU行与其它模式/免费/缺表头干扰混放，准确账单问题召回同模式完整行；仅CPU脚注不能替代该行。
- [x] 重用已有计费适用性与表头/脚注校验，将匹配行加入原问题core候选，经过原产品/维度/时效/快照资格筛选和容量选择；所有Agent仍消费同一packet身份。
- [x] 实际Writer与局部修复catalog必须含该行合法span，正式CPU主张独立审核后才进入不足账单答复。缺用量继续要求补充，不计算总价。

## 4. QA 按问题归属重放

文件：`backend/packages/agents/qa/evidence_alignment.py`、必要的新辅助模块及 `backend/tests/unit/test_question_context_qa.py`。

- [x] 红测试：已验证packet将资料遗漏归属到精确必要澄清问题，其它完整答案不得因此被添加假coverage blocker。
- [x] 反例：遗漏属于事实问题、例外问题、身份不明或回执被改，继续阻断；已回答标签不能清除真实缺口。
- [x] 复用选择身份与当前快照校验，保留原采集/派送缺口记录，改变的只是最终答案资格判断。正文被改或澄清内容不等于服务端结果继续拒绝。

## 5. 验证、审查、真实流程与交付

- [x] 每个组件先规格后代码审查，修复确定问题；全量后端、相关Ruff、diff和提交范围凭据检查。
- [x] 冻结代码后四家同八题各一次真实Collector→Analyst→Comparator→Reflector→Writer→QA，源码和输入哈希前后相同；新目录 `data/artifacts/subquestion-allocation-2026-10-23/live-*-first`，不覆盖上一轮。
- [x] 独立核所有可见事实/推断、服务器断言、精确支持、每个子问、实际回退及QA处置；安全拒价不充当完整题通过，仍按原始八题计分。
- [x] 更新README、Agent执行说明及交付/结果JSON，按已有授权提交GitHub。明确固定页面回放未验收新抓取、全Graph、生产dense RAG或部署。

全量命令：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests -q`。

## 实际执行补充

- 分开估算元数据与资料再回填仍有非线性超窗反例，改为同一窗口内一次装入完整元数据、原文和合法支持；可选排序提示只花剩余空间。元数据单独超窗由实际14KB派送门拒绝，原文和诊断不静默裁短。
- 独立审查发现并修复来源缺席守卫释义漏拦、产品文档排除规则误拒，以及32KB消费视图与14KB实际派送门不一致。旧无question_id的内部compactor调用保持兼容。
- 首两家真实诊断：初写主张审核未拿到精确原问场景、CPU补写误抄账单缺项到计划澄清字段。新增仅由服务端parse计划绑定的inference场景上下文；支持池不变，事实不能借题设。单独提供严格question_plan_missing_fields，仍由原parser验证。
- 冻结代码全量7193通过／1跳过（较基线新增68），独立限定质量257项通过。最终四家独立内容验收4/8，16/18完整支持、12/18单谓词；报告仍未达标。实施及本轮评估完成，不将剩余语义问题标记已修。
