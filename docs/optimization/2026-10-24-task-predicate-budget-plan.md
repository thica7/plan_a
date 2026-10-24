# 任务谓词、实际载荷与绑定修复计划

> 使用 subagent-driven-development 逐项实施，先规格审查再质量审查。用户已批准本轮目标和上轮交付中的后续方向，无需重复确认。基线 `abb17685`，复用现有干净工作树与既有分支。暂不训练，实验默认关闭。

**目标：** 在原24调用／80000 token内减少复合稿和尾部预算拒绝，让已采数量与资源范围规则成为有精确支持的实际答案，再按原八题复验。

**架构：** 继续使用原稳定任务ID、完整原问、规范来源、选证、生成、独立审核及最终QA。选择只是提案；精简实际请求中的重复内容，不能缩短原文或必要前提。优先修复任务目标与完整支持的接口，不增加模型训练、搜索服务或通用NLI框架。

## 已确认的根因与选择

上轮四家固定回归仍3/8；引用完整8/8而单谓词3/8。单纯追加提示和增加资料未解决问题，扩大总预算也不能解决引用和复合稿。本轮采用有界载荷与任务谓词约束：

- 选证当前携带全套规范事实，Trello尾部三次输入预留10490–12113、用量46055、最终保护23000、余量3200，发送前被拒。选证只需要完整可选支持和任务，生成只需所选事实及必要依赖；无需每次重复无关目录。
- `source_rule`要求“完整规则”与“一个谓词”混用，数量题写成一般规则清单；选择完整span并不能阻止将其全部复述。应明确只写目标谓词，容量题允许基于明确同对象上限的条件推断，不把题设人数当产品事实。
- 清缓存属于现有非六类操作路线，可用精确span；上轮附加读取设置／未选分配规则才触发操作绑定错误。操作引用要按实际主断言分配，完整必要条件不得删去。资源范围题需要同源已准入的具体角色规则与范围约束共同进入任务窗。

## 任务一：有界选证与生成载荷

文件：`backend/packages/agents/writer/task_support_selection.py`、`task_execution.py`、`readable_support.py`（仅必要时），测试 `backend/tests/unit/test_task_support_selection.py` 与新增 `test_task_predicate_budget.py`。

- [x] 写失败回归：三任务共享长目录、无关事实占窗；最小完整选择载荷应严格小于旧请求且保留每项原文、条件和任务原问。调用真实adapter验证，不用假transport冒充预算改善。
- [x] 选证使用服务器已验证的ref目录派生紧凑请求；包括任务、完整原问、所有实际可选完整支持及其必要限制。系统提示与实际输入完整绑定，保留选择收据和源身份；失败不默认选择。
- [x] 生成只带选中事实及其已验证必要例外／依赖，保留完整规范行、操作、原文与条件；按实际事实重建问题包，ref不重编号。不得仅为了缩小载荷删除已需条件或绕过QA原文重放。
- [x] 用 `_question_replays`、真实adapter及篡改回归确认同一请求的派送、来源、支持及任务身份可重放；24／80k、旧checkpoint、输出上限不变。

## 任务二：目标谓词与绑定对齐

文件：`backend/packages/agents/writer/task_execution.py`、`task_protocol.py`、`question_allocation.py`、`task_projection.py`、`question_retrieval.py`；必要时新增单职责 `task_predicates.py`；对应测试 `test_task_predicate_budget.py`、`test_task_projection.py`、`test_question_task_execution.py`、`test_atomic_request_coverage.py`。

实施前补充定位：Cloudflare旧两次Writer消费各12个fact／4个请求fact，三条已准入scope规则均不在消费视图，单改后续排序无法修复。因此在 `question_retrieval.py` 的快照选择入口补同源范围依赖，消费创建后不得注入。新增范围任务只在新Writer执行规划后显式补入，`parse_tasks`默认重建不自动加行，保留旧任务ID和旧收据回放。

- [x] 泛化上轮复现为无产品名fixture：两个独立数量限制、私有对象与共享对象上限、费率与运行时限、权限层级与逐项设置、操作列表。先观察失败，不在功能中写入产品、原题或金标。
- [x] 澄清生成／局部修复合同：只写当前请求的主断言，完整选中支持中的兄弟性质不进入主张；数量不足可用同对象／单位的明确上限做条件推断。保留必要AND／OR、角色、套餐、对象与例外。
- [x] 为已明确识别的跨属性复合表述增加有限拒绝检查，实时与最终任务重放一致；未识别语言仍归独立审核，不声称通用蕴含。修复不得重复发表未改变的成功或部分稿。
- [x] 明确六类结构化操作与其余动作的合法引用路线；目标清缓存不能附加读取，角色改权不能借UI分享按钮当权限规则。资源范围相关完整已准入规则优先进入同题窗口，多个必要span仍受原例外／多事实准入约束，不放宽守卫。
- [x] 跑原子、选证、任务执行、投影、QA重放和预算相关回归；独立规格审查通过后做质量审查，修复确定问题再冻结。

审查中确认两项P2，须先红绿修正并复核：范围补项不得将 `request_not_planned` 等旧延期项重新激活，服务端展开超过48行不能被重新当成模型计划包络；容量推断中明确属于题设的“另外一名用户／one other user”不得被当作第二条产品人数上限。修前全后端7493通过／1跳过已单独归档，不作为最终源码验证。

质量审查另复现48条合法计划加范围项变49条、导致QA旧包络拒绝的问题；已用真实QA重放红绿回归修复，新增项按剩余48条总任务容量补入。原48条及既有超限服务端任务保持原对象、状态和ID，不放宽旧QA限制。独立规格与质量复核均通过。

## 任务三：同版四家与交付

- [x] 新忽略阶段目录 `data/artifacts/task-predicate-budget-2026-10-24/`，复制锁定runner，封存旧原件SHA；2026-10-21官方页面及原八题不变，参考答案只用于独立审计。
- [x] 先全后端与变更Ruff检查；冻结同一生产SHA，四家实际模型回放。只允许配置的completion端点，不抓新页、不读出凭证；保留全部失败、未送及未知usage。
- [x] 四家全部完成后独立审读原八题、可见每条完整支持／单谓词、任务结论与实际QA集合。不能以机械通过、合法回显或安全拒答替代完整报告。
- [x] 更新README、Agent执行说明、交付MD／JSON；沿既有授权提交推送并核对远端SHA和干净工作区。若报告未达标，明确剩余阶段归因，保持实验默认关闭。

## 验证入口

```sh
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_task_predicate_budget.py backend/tests/unit/test_task_support_selection.py backend/tests/unit/test_question_task_execution.py backend/tests/unit/test_task_delivery_replay.py backend/tests/unit/test_task_projection.py backend/tests/unit/test_task_delivery_budget.py -q --tb=short
```

新增测试应先失败，再最小实现转绿。全后端使用同样离线环境运行 `pytest backend/tests -q --tb=short`。真实回放使用新阶段runner的 `--live --output <新目录> --timeout 600`，预算仍24次／80000 token。

## 本轮结果

最终后端7521通过／1跳过，四家同版回放63调用／175187已知token；原八题仍3/8，全文所选支持6/7、单谓词2/7。已完成本轮实施及验收实验，报告交付门槛未通过，实验默认关闭，不将未解决的复合写作／尾部预算／CF场景漏答标记为完成。详见[交付记录](2026-10-24-task-predicate-budget.md)。
