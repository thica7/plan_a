# 问题结论绑定与完整规则投影实施计划

> 执行方式：按 writing-plans / systematic-debugging / test-driven-development 执行；独立投影任务用 subagent-driven-development，变更后按 requesting-code-review 审查。用户已批准下一步，沿用现有工作树与分支。

**目标：** 阻断与问题操作无关的已发表主张被用来给出确定结论，让已采集的完整角色规则具备合法写作支持。

**架构：** 保留当前 v3 选择式回答和逐条审核。在共享回答验证入口增加有限的操作覆盖拒绝检查；这是明显不相关检测，不是通用语义蕴含证明。源规则修复只改变完整候选的可用性，不把请求条件当事实，不自动发表事实，不提升预算。

**技术：** Python、Pydantic、pytest，复用实际 trace/snapshot；本轮不训练模型，不执行 Docker。

## 已确认根因与范围

- Trello 下载/导出问题选择了只讲投票的已发表 claim，ID 和全文引文校验均通过；独立复审可把 unanswered 提升为 answered。
- 1Password canonical evidence_terms 内包含无 Private vault 的规则，但末尾 `Consider inviting:` 使完整段落失去 source span 候选。
- Cloudflare 具体角色原文已送到 Writer；`required_operations` 用于规划时将“角色/权限”扩展到全部操作，却也被用在正文绑定门禁。
- 不用品牌名硬编码结论；原审核仍负责否定、模态、角色、对象、条件与完整语义。新检查必须保留正例。

## 任务一：问题与已发表主张的操作覆盖

文件：新增 `backend/packages/agents/writer/answer_action_scope.py`、`backend/tests/unit/test_answer_action_scope.py`；接入 `answer_coverage.py`。

- [x] 先以真实 Trello、Cloudflare 已发表回答和匿名双操作问题写失败测试：无关操作、只覆盖一个子操作、仅原始事实相关而所选正文不相关均不能 answered。
- [x] 对直接/条件式完整回答，从显式问句识别有限的操作需求；只检查所选已发表全文。未知表达交语义复审，不伪称规则已证明正确。
- [x] 澄清、缺价与未核实回答保持原合同；partial 不制造确定 yes/no。正例包含两项操作均有支持、中文/英文表达、已给前提不作为待回答操作。
- [x] 同一个检查用于生成后、复审后与保存重放，不允许后续复审绕过。

验证：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_answer_action_scope.py backend/tests/unit/test_answer_selection_contract.py backend/tests/unit/test_answer_semantic_review.py -q`。

## 任务二：完整原始规则进入写作候选

文件：`source_spans.py`、`report_claims.py`、`dimension_writer.py` 及新的投影回归测试（按复现需要限定改动）。

- [x] 保存实际 1Password / Cloudflare 原始最小夹具和来源哈希，先证明完整规则不可引用/被误阻。
- [x] 有明确可选例子引导句时，允许选择其前面的完整原文规则；保留主语、否定、前提和精确坐标，条件引导列表不得截断。
- [x] 将规划关键词与正文实际操作区分；显式编辑/分享等操作仍需 operation binding，纯角色范围及未结构化操作规则仍须完整 source span 和语义审核。
- [x] 验证篡改/缺前提/操作绕过仍拒绝，原始事实与人审参考不改。

## 任务三：验收与交付

- [x] 新测试先红后绿；相关回归后跑全后端，变更 lint 和 git diff 检查。
- [x] 独立代码审查，修复重要问题。
- [x] 用保存输入、固定官方资料对关键 Writer/审核路径做限定真实模型诊断；记录调用/token/截断/缺证，首次结果不覆盖。若需要重新抓取，结果明确注明来源变化。
- [x] 分开汇报错绑拦截、事实进入正文、内容完整性，不能将测试全绿当交付合格；公开文档更新，原始证据保存在工作区忽略目录 `data/artifacts/question-conclusion-2026-10-23/`。

验收不包含生产 dense RAG、全 Graph 自动发现、全系统可交付性或未曝光泛化准确率。已曝光十二题用于回归，新的匿名反例用于工程边界。

## 执行结果

本计划限定工程任务已完成；业务报告未达标。后端6922通过／1跳过，格式整理AST等价且215项复跑通过。四组历史页面真实模型回放60调用／193790 token，严格问题与后续方向见[交付记录](2026-10-23-question-conclusion.md)。本次只跑旧六题与Trello两题，未重新运行Dropbox／Miro；不宣称旧八题＋新四题全部通过。
