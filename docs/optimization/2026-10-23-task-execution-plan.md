# 按任务 ID 执行与最终答复预算实施计划

> 用户已批准本轮方向，使用 subagent-driven-development：独立预算实现，主任务负责有依赖的 Writer 协议、接线和集成；每项先规格后质量审查。复用 `codex/pastoral-desktop` 隔离工作树，基线 `e57c9c01`。不再请求重复授权。

> 以下保留开工计划。2026-10-24复验后，原定默认启用已撤回：新机制默认关闭，正文交付目标未达成。实际执行状态见文末与[交付记录](2026-10-24-task-execution.md)，不能将计划要求当作已通过的结果。

**目标：** 每个子问／谓词具备服务器任务ID、实际证据包、独立生成和审核状态；最终回答及QA有受保护的预算，修复Trello漏答与Cloudflare已审核结论未发表，再按同八题验收。

**架构：** 小型请求规划只拆原问，不产生产品事实；服务器验证问题身份和原文片段，派生稳定任务ID。每次最多打包两项，每项最多一个原子并单独准入、审核、保存结果。任务合计上限12，沿用原初写8+修复4的累计上限，改为按任务分配；不提高每家24调用／80000 token或1600写作输出上限。最终候选由已审核任务构造，只执行一次独立完整问题语义复核，保留原v3绑定与子问合同；不能在预算耗尽后回用未经复核的候选。新的默认启用设置保留旧流程回滚及历史合同测试，无题／非功能报告及操作定向重做保持原路径。

**技术：** Python、Pydantic、pytest、现有真实模型与证据快照。记录使用现有trace工具，不改公有RunDetail／ReportClaim schema，不训练，不加前端、数据库或部署功能。

## 1. 基线与失败重放

- [ ] 确认工作树干净和已有隔离，运行allocation／budget／QA归属基线；资料与代码不重新下载。
- [ ] 保存上一轮CF最终审核预留18433+1600、已用66297却未入场，以及Trello两次QA拒绝、遗漏分支的实际轨迹。区分真实transport与零attempt拒绝。
- [ ] 用新匿名离线例检验任务隔离、独立审核、缺证与预算延期，不把旧八题当未曝光样本。

## 2. 通用任务协议与生成审核

创建 `backend/packages/agents/writer/task_protocol.py`、`task_execution.py`；必要的证据装窗／答复辅助保持单一职责。测试 `backend/tests/unit/test_question_task_execution.py`。

- [ ] 先写红测试：稳定ID、未知／重复ID拒绝、每项最多一原子、一个坏项不能吞掉其它项、完整原问保留、不同对象与动作独立、超额项明确deferred。
- [ ] 规划输入只有当前原问；返回严格 `question_id/question_quote/focus` 请求片段，不含答案或来源。片段必须来自原问，所有原问均有任务或明确延期。规划失效时保守记录，不将任务描述当事实。
- [ ] 每批最多2项；来源从当前选择／准入视图按任务重装完整fact、原文和条件，不截AND/OR或例外。实际总写作JSON仍14KB，候选支持仅来自本批实际派送规范目录。原问与task请求分开，源和原问都是数据。
- [ ] 结果仅能回当前task_id，每项最多一个fact/inference原子；合法候选经原parse、source span／operation、条件与全主张守卫，再独立审核。每项状态区分supported、rejected、insufficient_evidence、deferred及明确原因；不接受模型自行授权的来源或任务ID。
- [ ] 任务审核同时绑定task_id→claim_id→原问，验证同一谓词、完整条件与语义方向；未通过原子不进入最终答案，审核理由不补正文。

## 3. 最终回答与QA预算

修改 `backend/packages/llm/execution_budget.py`、`orchestrator/llm_execution.py`、`config/settings.py`；新增 `backend/tests/unit/test_task_delivery_budget.py`，保留旧profile测试。

- [ ] 红测试：任务已用额度但不能消耗最终answer和final_qa的token／调用预留；最终阶段可用自身额度；恢复／并发／未知usage保持全局硬上限。
- [ ] 新profile按名称路由task生成／审核、answer及finalQA；阶段最少调用数支持明确配额而非只保护首个调用，预算和已完成状态进入checkpoint，旧checkpoint不能凭空增加预算。
- [ ] `writer_task_execution_enabled` 默认true，旧路径可回滚；仅real、功能显式问题启用，旧测试明确验证旧profile，新增集成验证默认生产入口。
- [ ] 最终答复改为服务端从任务已审核claim／决策构造候选，使用紧凑语义payload：完整claim文本、实际选中支持和全部限制，去掉模型不需要的哈希／坐标重复，不减少可验证条件；完整身份仍保留服务器及持久化记录。
- [ ] 只一次独立 `dimension_answer_review` 决定最终原题覆盖、子问划分和引用，继续原v3解析。无预算／无效／缺证则partial或未核实，任务完成不等于整题已回答。服务端缺价与必要澄清保持原合同。

## 4. 生产入口与派送重放

修改 `dimension_writer.py` 和必要的 `qa/question_context.py`，测试实际Writer与保存／QA入口。

- [ ] 新流程接实际feature问题入口，旧无题／非feature／定向操作重做路径保留。原上游依赖、当前消费和source资格在每次调用后校验。
- [ ] 记录 `question_task_delivery`：原选择／快照、task IDs及每次真实generation span、完整请求hash和实际fact IDs；只成功真实transport关闭交付义务，零attempt不算送达。
- [ ] QA按当前packet与多次真实派送的完整原文并集重放。纯请求澄清仅豁免自身core缺口；事实、例外、未知、篡改继续阻断，不借模型task状态关闭证据义务。
- [ ] 初写已通过的task不因另一项失败被丢掉；不追加旧全局重写循环。最多有界局部修复，且不能花最终回答／QA预留；没有额度明确deferred。

## 5. 审查、真实模型与交付

- [ ] 先规格再质量独立审查，处理确定P1/P2；全部实现冻结后跑完整后端、Ruff、diff与提交范围凭据检查。
- [ ] 复用封存官方页面与原八题，每家24调用／80000 token，最多两家并发，真实执行Collector→Analyst→Comparator→Reflector→任务Writer→QA。目录 `data/artifacts/task-execution-2026-10-23/live-*-first` 不覆盖。参考答案不进模型；模型别名不冒称底层日期版本。
- [ ] 独立逐原题、逐可见主张审核，检查task实际状态与正文是否一致、完整前提、引用及QA处置。安全拒价单列、隐藏支持不补正文；未达标如实记录，不以测试数替代内容验收。
- [ ] 更新README、Agent入口说明、交付与结构化结果，按已有授权提交GitHub并核对远端SHA及干净工作树。

命令：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests -q`。

四家固定页面回放不验收新抓取、Planner发现、全Graph、发布、生产稠密RAG或Docker；不训练模型。

## 实际执行状态（2026-10-24）

| 计划项 | 状态与依据 |
| --- | --- |
| 基线、失败留存与匿名离线用例 | 已执行；旧八题明确按已曝光回归处理，首轮及最终轮产物分别保留 |
| 稳定任务ID、有限规划、逐项生成审核 | 已接真实入口并通过机制测试；语义原子化和任务覆盖仍失败 |
| 预算保护与历史checkpoint恢复 | 已实现并独立审查；最终四家核心12模块都实际调用，Trello仍有2次零transport预算拒绝 |
| 最终回答与QA实际执行 | 未完成内容目标；最终回答审核实际2次、最终QA模型重核0次，不能以预留存在代替执行 |
| 成功任务进入最终正文 | 未完成；仍有2条已支持主张隐藏，任务审核仅保存布尔完成状态，最终模型重判关系会丢失结论 |
| 多批实际派送与QA重放 | 已实现并通过篡改、身份、完整原文及真实transport用例；不能保证事实语义正确 |
| 四家真实模型内容验收 | 已测试但失败：旧4/8→首轮2/8→最终1/8；Trello与Cloudflare目标仍未解决 |
| 默认启用与发布 | 原计划撤回；`WRITER_TASK_EXECUTION_ENABLED=0`，保持实验入口，默认旧路径 |
| 工程验证与独立审查 | 最终后端7306通过／1跳过；变更范围静态检查与规格、质量、独立内容审查详见交付记录 |
| 交付文档与GitHub | 文档随本轮源码提交；精确提交号与远端状态在提交后核验 |

后续重点是任务审核决策到最终答案的结构化投影、失败任务的局部修复及实际输入大小下的任务预算分配；不通过放宽引用、删除QA问题或改分母制造通过率。本轮没有训练模型。
