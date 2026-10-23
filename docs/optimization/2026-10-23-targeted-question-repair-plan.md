# 子问定向选证、局部重写与最终 QA 计划

> 使用 subagent-driven-development 按任务实现和独立审查；用户已批准本轮设计方向，复用隔离工作树 `codex/pastoral-desktop`，基线 `e0f6c5d`。

**目标：** 失败子问能从当前准入资料重新选择完整支持，重写受影响的原子并审核；逐项结论、计费前提和最终 QA 可重放。

**设计：** 在现有采集准入和 Writer 合同内修复。完整抓取页中的相关规则段只作为提案，经过相同来源、原文、条件与存储验证；Writer 仅使用当前证据消费视图。保留已通过主张及其绑定，对有具体缺口的问题执行最多一轮定向选证/重写，独立审核新增主张，重新审核受影响答案。真实缺证或预算不足仍局部交付。最终 QA 对原 Reflector 问题逐条复核并保存处置证据，不能因回答状态为 answered 就删除问题。

**技术：** Python/Pydantic/pytest；当前 DeepSeek 适配器。保持每组24调用/80000 token、Writer1600 cap及无重试。不训练、不运行 Docker、不向模型提供人审参考。

**实施边界补充：** 无可靠结构的原文仅接受不超过800字符的完整正文；标题结构可验证时接受不超过1600字符的完整小节。子标题中的例外与父规则保留在一起，跨出当前提取窗或过长则拒绝，不截取前半段。首轮真实测试另发现事实占满窗口后没有引用、审核目标被压成 `text_ref` 两处传递故障；追加最小修复和回归后，将使用同八题另建目录复测，首轮保留。

## A. 已抓正文的定向规则提案

文件：`backend/packages/research/extraction/structured_evidence.py`，新增 `test_question_rule_proposals.py`。

- [x] 失败测试：匿名权限页面中断行的管理员、逐板设置和可计费成员条款都进入完整原段提案；导航、未知条件、其它产品、不在当前窗口或超长段不被截断采纳。
- [x] 按真实问题的检索意图选择当前页完整规则段，遵循原窗口和预算。使用 `semantic_extraction` 和既有 admission，不直接改事实库或 Writer 白名单。
- [x] 运行提取/准入及问题补证回归，验证提案原文坐标、哈希和完整前提。

## B. Writer 单轮定向选证与局部重写

文件：新增 `backend/packages/agents/writer/question_repair.py`、测试 `test_targeted_question_repair.py`；必要入口接入 `dimension_writer.py`、答案合同/展示辅助模块。

- [x] 从真实失败选证建立红测试：单库/私人库不能引用邀请段，逐项 A/B 不能仅发表通用 depends，第二题不可因第一题已回答而消失。
- [x] 构造仅包含失败原问、缺失前提、已通过主张、具体拒绝原因和排序后的完整支持的有界输入；引用从实际派送候选还原。背景随请求保留，独立操作、对象与条件分别回答，不把用户情境当产品事实。
- [x] 一轮修复最多4个原子，替换失败草稿、保留原已支持主张；新主张经过现有规则及独立模型审核。复审所有受影响答案。超容量/无预算/格式坏/依赖变更不保留未经审核的结论。
- [x] 测试原问/来源/范围变更拒绝、未改成功答案、局部失败保留缺口、日志可追溯与预算上限。

## C. 计费引用合同

文件：`price_answers.py`、QA 重放入口及针对性测试，Writer 最终覆盖入口传入正式已审核主张。

- [x] 红测试复现 CPU 句有事实却 claims/spans 为空的旁路。
- [x] 让计费前提使用正式已审核主张及精确支持；缺价保持 partial/insufficient，实际用量不补算金额。最终 QA 按相同快照与已发表主张重算，伪造来源、跨套餐/单位、未审主张或缺条件继续拒绝。
- [x] 保留请求条件和产品事实的区别；没有合法计费支持时不得发表无引用产品断言。

## D. 最终 QA 重核过时问题

文件：新增 QA 重核辅助模块、`qa/logic.py` 的最终入口及新测试。

- [x] 红测试复现：同一域权限题的最后已审核 no 与 Reflector 早期 negative-inference blocker 冲突。
- [x] 逐条核对当前报告、精确支持、原问题和旧 issue。保留原 reflection 历史，记录 issue ID、问题 ID、主张、快照/产物身份及处置。
- [x] 无法映射、混合缺口、失败引用、来源/矩阵结构问题及模型不可用均保留；严格防止 answered/partial 标签自动消除 blocker。重核仍需现有预算及依赖检查。

## E. 验收与交付

- [x] 红绿、相关回归、规格与代码审查；完成后运行全量后端及变更 lint。公有模型变化则同步 OpenAPI 和前端构建。
- [x] 冻结源码后四家各一次固定原始8题、官方抓取页、真实 Collector→Analyst→Comparator→Reflector→Writer→QA，首次结果及哈希保存到本轮 artifacts，不覆盖旧轮。
- [x] 独立审核所有原题/子问、可见主张、服务器断言、引用、前提、状态和 QA，不以调用成功或零引用错误代替交付标准。
- [x] 更新 README、Agent 执行说明及统计，沿已有授权提交 GitHub。明确固定页面回放不验收新抓取、全 Graph、发布或生产 dense RAG。

基础命令：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests -q`。
