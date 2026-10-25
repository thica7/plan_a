# Collector 原文入库、逐子问选证与联合预算实施计划

> 使用 subagent-driven-development：逐任务实现，先规格后质量审查。用户已批准三个修复方向及隔离／四家复验，直接执行，不另设确认。复用现有 linked worktree `codex/pastoral-desktop`，基线 `73a8cb199663162da765e74ff08df7a505e121ba`。

**目标：** 让已捕获且相关的原文经可验证定位进入规范事实，使各子问收到匹配资料、支持合理条件推论，并保证写作与最终QA共同获得有界资源。以同版固定模型及资料检查真实交付，不训练模型。

**架构：** 保留现有模型、LangGraph及来源准入。优先修原文位置映射与模型选择合同，不放宽为模糊语义匹配、不迁框架；证据始终回到原始正文精确坐标。保留总24调用／80000 token、实际派送检查、未知usage保守记账及历史收据重放。按任务实际完整输入安排预算，不靠增加额度或丢掉条件、例外凑成功。

**技术栈：** Python、现有ResearchBrief/CapturedPage、semantic_extraction、逐任务Writer与独立QA、pytest、封存官方资料及真实DeepSeek完成接口。实验入口继续默认关闭。

## 已知反例与设计边界

- 上轮Collector隔离返回6条语义对应正文，HTML精确定位只有1条准入；5条因排版/格式差异为not_original。设计必须恢复唯一、完整、未改词的原始片段及offset，不允许近似改词、跨窗口、歧义或拼接条件。
- Cloudflare实际selector已有角色范围和CPU规则仍拒选；另有Trello任务分派到不含相应规则的窗口。题设角色/套餐是待判假设，不要求官方证明；产品结论仍绑定所选规范证据。
- Trello已选事实后的生成被总预算保护拒绝；最终QA27项只送23项。预算需要结合实际输入与剩余任务调度，不能仅预留名字或把零transport算消费。
- 上游内容是建议，不是产品证据。single诊断CLI尚非生产轻量路由。本轮不新增自动路由，不训练、不Docker、不抓新网页。

## 任务一：Collector定位与入库

**文件：** `backend/packages/research/extraction/semantic.py`，必要时现有语义提取输入构造／准入文件；新增 `backend/tests/unit/test_collector_quote_mapping.py`。

- [x] 从封存Collector实际输入/返回离线复现1/6，并逐项记录原文差异；构建不依赖本机原件的最小真实形态fixture。
- [x] 先写失败测试：安全排版恢复后`quote.text == body[start:end]`，并通过真实admission进入RawSource；改词、否定、数字、角色、不同标点语义、重复片段、跨窗口和跨段拼接拒绝。
- [x] 最小实现唯一原文映射，保留原始quote诊断及恢复后的精确原文；来源重新验证必须可重放，不因普通metadata自述可信。
- [x] 运行语义提取／原文准入／入库／历史回放相关回归，规格与质量分别审查。用隔离原件离线重验实际准入数，不以文本相似代替。

## 任务二：逐子问选证与合理推论

**文件：** `backend/packages/agents/writer/task_execution.py`、`task_support_selection.py`、`question_allocation.py`，必要时`task_projection.py`及QA提示；新增 `backend/tests/unit/test_task_selection_reasoning.py`。

- [x] 离线重建Cloudflare和Trello失败的任务、完整父题设、catalog及实际选证输入，区分窗口错配和模型判断。
- [x] 红测覆盖任务与完整证据包绑定；共享父前提保持，子问检索主意图不被其他操作覆盖。
- [x] 选证／写作／审核明确支持条件推论和合理澄清：许可不推出义务；特定资源授权不推出另一资源授权；角色标签不足确定费用。不得自动生成产品否定或绕过所选支持。
- [x] 同次输入保留原始规则、AND/OR、例外及来源坐标；超界明确延期。历史已存提示/收据按其原版本重放。
- [x] 专项回归和两阶段审查后封存实现。

## 任务三：Writer与QA联合预算

**文件：** `backend/packages/orchestrator/llm_execution.py`及现有预算类、`backend/packages/agents/writer/task_execution.py`、`backend/packages/agents/qa/independent_question_review.py`、`question_reconciliation.py`、`backend/packages/agents/writer/dimension_writer.py`；新增或扩充`backend/tests/unit/test_joint_task_delivery_budget.py`。

- [x] 复现已选证据却生成0transport及最后QA未送；按实际请求输入/输出预留定位保护额度与消耗归属。
- [x] 红测覆盖写作、任务审核、最终回答和最终QA共享有界分配；用量未知、超时、checkpoint恢复不能释放已消耗额度。
- [x] 在原24／80000内减少重复包与无进展派送，按完整实际请求计费，未送保留状态；不能靠截断原文或提高预算通过。
- [x] 回归旧checkpoint、超界、失败settle与独立最终QA入口；规格后质量审查。

## 任务四：冻结同版、隔离与四家流程

- [x] 全后端7724通过、1项因沙箱ps限制受阻，必要权限单项复验1通过；1跳过。19文件变更Ruff相对新增0、diff检查通过，冻结源码/包/脚本哈希。
- [x] 新忽略目录 `data/artifacts/collector-task-delivery-2026-10-25/`；保存旧原件哈希，沿用2026-10-21官方页面锁、原八题及固定`deepseek-flash`/温度0/无重试配置。
- [x] 一轮四家阶段回放及七类真实请求隔离；没有真实请求则标未验。仅完成接口网络，不采集新页面。若确定代码回归需修复，保留首轮失败和全部成本，最终不同源码不得混用。
- [x] 独立审读固定原八题的所有必要分支、额外断言、逐条完整支持、原子性、实际上游/前提消费及QA未送项；原八题已曝光，不宣称泛化准确率。
- [x] 更新README、Agent执行说明及交付MD/JSON，保留1/8退化、四报告未达标和未验边界。
- [ ] 按既有授权提交推送并核对远端SHA；以Git记录及最终回复为准，不在提交前预称已推送。

## 验证命令与判定

```sh
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_collector_quote_mapping.py backend/tests/unit/test_task_selection_reasoning.py backend/tests/unit/test_joint_task_delivery_budget.py backend/tests/unit/test_task_context_handoff.py backend/tests/unit/test_task_predicate_budget.py -q --tb=short
```

最终运行同一离线环境的 `pytest backend/tests -q --tb=short`。功能合同通过不授予报告合格；仍缺答、越引用、复合主张或未审时，明确未达标并保持默认关闭。无外部权重训练。

## 离线定位补充（实施中）

Collector原件布局问题已复现并恢复6条精确原文；独立规格审查发现同版本重放会改变旧提案结果，已补显式v1/v2策略和真实旧capsule回归。未改变旧收据，未知版本拒绝。

选证确认三个通用断点：`task_predicates`未进入selector与任务QA；许可义务任务动作取自完整父题而非局部request；多任务混批只保证fact并集，没有保证每个任务候选实际入窗。只修这些入口，不使用产品名规则。

预算确认Trello历史两次零派送分别为 `45682+18185+23000=86867`、`49213+16890+23000=89103`，记账本身正确。尾答重建11683 bytes超原10000，请求未发送但12000保护闲置；QA共享上下文字段漏了request_context，按完整题聚合并无损共享可在同6000/MAX6内将9/8提升至9/9（离线装包，不是模型审核通过）。实现须按完整题分窗、实际请求构造及联合预检；未知usage时同80000不保证所有窗口都可送，保留未送与恢复状态。

## 封存复验结论

源码冻结后仅一轮四家回放及七请求隔离，77次实际调用／220508已知token，未知0；无新single、无训练。正文严格1/8（上一轮3/8），四份报告均不可完整交付；22个必要分支仅5个通过。Collector新返回恢复及准入6/6，最终QA28/28项全部实际送达且身份合法，均不替代内容完成。Trello上游逐题检索仍漏已入库规则，Writer仍复合生成并越出所选支持，9次生成和1次尾答被预算拒绝。下一阶段建议收敛逐题证据池及结构化原子结论交付，避免继续堆Prompt或增加预算；本计划不额外实施该新阶段。详见[交付记录](2026-10-25-collector-task-delivery.md)。
