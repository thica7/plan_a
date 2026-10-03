# 共享证据快照实施与验收记录

日期：2026-10-03。用户已确认设计与实施计划。实施基线：`6b42b30`；分支：`codex/pastoral-desktop`。

状态：正在实施，尚未完成第二阶段验收。本文仅记录实际完成和核验的工作，不把设计目标视为可用能力。

## 实施环境与约束

- 复用已有 linked worktree：`plan_a_pm_modes`，未创建新工作区。
- Python 使用现有共享虚拟环境 `../plan_a/.venv/bin/python`；不新增依赖或下载模型。
- 测试禁用本地 `.env`、使用临时数据库；不调用付费模型、搜索服务或新增真实报告。
- 真实服务与运行数据升级安排在第二阶段完整回归后执行；本轮尚未执行服务重启或真实数据库变更。
- 不部署 HTTP Qdrant，不迁移旧未知归属资料；语义质量和完整联网报告仍需后续验收。

## 基线核查

- 工作区开始时无未提交改动，基线已推送 GitHub。
- 独立运行 `test_run_journal.py`、`test_active_run_journal.py`、`test_graph_send.py`：**16 项通过，0.97 秒**。
- 第一阶段已有完整后端 / 前端验收；本阶段业务改动完成后重新执行必要定向与完整回归，不沿用旧结果宣称本阶段通过。

## 任务状态

| 任务 | 实现 | 规格审查 | 质量审查 |
| --- | --- | --- | --- |
| 1. 快照模型、确定性版本与持久化 | 完成，171 项独立回归通过 | 第二轮通过，98 项核验 | 第二轮通过，98 项核验 |
| 2. 可信引用解析与阶段视图 | 完成，402 项独立回归通过 | 第三轮通过，207 项核验 | 第二轮通过，207 项核验 |
| 3. 图冻结时点与进程恢复 | 完成，616 项独立回归通过 | 第二轮通过，38 项核验 | 首轮通过，575 项核验 |
| 4. Agent 输入与产物依赖 | 待执行 | 待执行 | 待执行 |
| 5. 更正、缓存与依赖失效 | 待执行 | 待执行 | 待执行 |
| 6. 完整验收与交付 | 待执行 | 待执行 | 待执行 |

## 实际问题与处理

1. 任务 1 接入 typed DTO 时复现循环导入：`api_dto → evidence.__init__ → admission → business_intel / rag / enterprise / memory / compliance → api_dto`。主代理通过独立 Python 进程复现相同 ImportError，确认模型文件自身没有 RunDetail 依赖；批准仅将 evidence 包原 exports 改为延迟加载，并追加导入顺序回归。主代理复跑三种独立导入顺序均通过，完整定向回归 **112 项通过，4.19 秒**；六个代码 / 测试文件 Ruff 和 `git diff --check` 通过，等待独立规格与质量审查。
2. 独立规格审查找到三项未覆盖输入，主代理均已复现：canonical 摘要被提升为 `supported`；显式含税 / 未税 `qualifiers` 丢失并形成错误冲突；仅有 KB 版本或内容 hash、没有文档 ID 的候选绕过 canonical 校验。实现者补测取得 **36 failed、37 passed**，修复后快照测试 **73 passed**；主代理复跑全部定向集合取得 **149 passed，4.43 秒**。独立规格复审通过，执行 **76 passed** 并确认原隔离与时效边界未回退；继续独立质量审查，尚未进入后续 Agent 接线。
3. 独立质量审查发现四项 P2，主代理均已复现：同原证据 IDs 的不同观察产生相同 fact ID；限定条件 JSON 接受非对象 / 非规范字符串；非 KB 来源漏读实际采集路径的原 `fetched_at`；原 quote 超过 400 字时永久截断，尾部口径变化不升版。已退回实现者补失败测试并修复，保留稳定 semantic ID、完整原引用和 canonical KB 日期优先规则。
4. 主代理补查并由实现者确认完整型号缺口：canonical 文档仅属于 Product A，RawSource 却可通过 `covered_competitors` 与行内字段把它投影成 Product B 的事实。canonical 模型没有 typed 多产品名单；本轮补失败测试并保守拒绝候选声明覆盖 canonical 身份，非 KB 的已准入多产品来源契约保持兼容。
5. 上述四项质量问题与型号边界已补测试：有效 RED **18 failed、77 passed**，修复后快照文件 **95 passed**。主代理独立复跑同一定向集合取得 **171 passed，4.30 秒**，六文件 Ruff 和差异空白检查通过。继续按规格复审、质量复审的顺序验收。
6. 第二轮独立规格与质量复审分别执行 **98 passed**，原探针及新增完整型号规则通过。两轮修复后 Task 1 没有剩余规格 / 质量阻断，允许进入 Task 2。

## 任务提交

- `1f0bb1a feat: seal immutable shared evidence snapshots`：Task 1 已保存本地提交；父代理核验六文件 Ruff、差异检查和九个变更文本文件凭据模式扫描（0 命中）。后续任务及最终完整验收完成后统一推送本分支。
- `68e81b4 feat: validate scoped evidence references and stage views`：Task 2 已保存本地提交，提交后工作区干净；402 项独立定向回归、规格 / 质量审查各 207 项通过。进入 Task3，完整第二阶段验收后统一推送。

## 任务 2 接线决策

为封存服务器解析出的逐来源 / chunk 拒绝项，批准公开 `seal_snapshot` 原签名不变、共用单一私有封存 helper 的必要内部接线。拒绝项随 gaps 参与内容摘要，不通过修改候选 metadata 或事后改冻结快照实现。按 scope 回读不可得的文档统一标记 `canonical_document_unavailable`，不额外越权探测其是否存在。

实现收尾发现并复现两项：多个明确 chunk 字段只校验其中一个（新增 RED 6 failed），兼容来源投影合并不同单位 / 市场的观察（新增 RED 1 failed）；均以最小修复转绿。强化了原候选 JSON 保持不变、不变分支跨版本验证、同正文 hash 价格更改拒绝、被拒凭据不可复用的行为断言。继承实现的原 RED 无可追溯记录，不补写为已发生。

主代理独立执行新视图 / 范围测试、Task1、第一阶段 scope storage / retrieval / reference / currentness、journal / active journal / Writer EvidencePack 合计 **335 passed，7.21 秒**；1 条既有本地 Qdrant 精确搜索提示。六个代码 / 测试文件 Ruff 与差异空白检查通过；service 仅 mixin 接线，未新增既有 Ruff 诊断。尚待两级独立审查。

首轮规格审查另复现文档引用别名矛盾：有效 `kb_document_id` / 版本 / hash 与相互矛盾的 `document_id` / `document_version` / `kb_content_hash` 同时出现时，候选仍被接受且无缺口。主代理用临时真实 SQLite 复现全部三项，等待本轮完整审查结论后修复；相同值别名继续兼容。

首轮规格结论为未通过（2 项 P2）：除上述矛盾别名外，历史 / 摘要来源因 advisory 提前返回而漏掉缺失 / 未来 / 陈旧日期缺口。主代理用固定时钟复现全部三种角色日期场景；已退回实现者按失败测试、最小修复流程处理。

修复记录：身份别名新增 RED **30 failed、8 passed**，advisory 日期新增 RED **9 failed**；共用身份 helper 检查两个入口所有明确别名，同值兼容、矛盾 / 非法拒绝且不探测其他引用 ID。多原因资格同时保留 advisory 和日期缺口，事实仍为 signal。主代理再次独立执行同一定向集合，取得 **382 passed，8.53 秒**，1 条既有 Qdrant 提示；继续规格复审与质量审查。

独立规格复审：**187 passed，2.47 秒**，原探针通过，确认拒绝项改变摘要且持久化、候选与历史不变、矛盾 ID 不触发仓库读取。规格通过，继续独立质量审查。

质量审查补查到同一授权文档的合法 `chunk-a` / `chunk-b` 分别写入两个单值别名时仍被接受；只投影第一个 ID 导致快照 ID 不变、旧消费仍 validated。主代理用临时真实 SQLite 独立复现，待本轮完整审查结论后修复单值别名一致性；合法 `kb_chunk_ids` 多分块列表继续支持。

主代理沿同一缺口补查：仅使用合法 `chunk_id` 别名时从 a 改为 b、或合法 `kb_chunk_ids` 从 [a] 改为 [a,b]，原封存均丢失这些身份且 ID 不变。批准必要的深不可变分块引用投影（保留既有单值接口，所有已授权引用规范化进入摘要与依赖），与单值别名矛盾一起补测修复；多值到达顺序不应触发升版。

本轮分块修复取得真实 RED **11 failed、62 deselected，1.32 秒**：覆盖两个入口的矛盾单值别名、引用变更不升版及合法组合未完整封存。实现中，尚未再次宣称通过。

分块修复完成：全部有效引用规范去重排序，以深不可变 `chunk_ids` 封存，进入安全来源投影、语义身份、视图与依赖摘要；保留旧 `chunk_id` 并支持单值别名。主代理独立复跑指定集合 **393 passed，8.46 秒**，1 条既有 Qdrant 提示；六文件 Ruff、差异空白检查通过。继续规格复审、质量复审，未接线 Graph / Agent。

本轮规格复审取得 **198 passed**，但用 Task1 提交的旧模型在内存封存合法 v1 后，发现新增默认 `chunk_ids=()` 改变回读内容摘要，旧冻结快照校验失败（1 项 P2）。已退回最小兼容修复，要求保留旧 ID / hash / 历史、无分块引用相同输入不无谓升版、非空分块引用仍完整参与校验。Task2 尚未完成。

主代理独立使用 `git show 1f0bb1a` 的模型和封存代码在内存生成旧快照，原校验通过且来源不含新字段；当前模型回读后确实发生 `evidence snapshot content hash mismatch`。复现未读取真实运行数据库或凭据。

旧版兼容新增真实 RED：**8 failed、1 passed、73 deselected，0.45 秒**。测试使用由原提交实际生成并通过原校验的三类固定 JSON，不依赖验收机器存在 Git 历史；覆盖普通来源 / 无分块知识文档 / 单分块知识文档的 journal 回读、空引用重复冻结及非空引用篡改。正在修复，尚未复审通过。

兼容修复以三处空引用条件完成，新增 **9 passed**；主代理独立复跑定向集合 **402 passed，7.80 秒**，1 条既有 Qdrant 提示，六文件 Ruff、差异检查通过。主代理重跑原提交内存探针，旧快照读入、相同输入重复封存保持原 ID / hash / 单条历史，注入非空引用仍被明确拒绝。继续第三轮规格复审与质量复审。

第三轮独立规格复审通过：**207 passed，2.41 秒**。使用原提交代码重生成三类旧快照，并核对固定 fixture、journal 和非空引用篡改，原兼容 P2 已解决；Task2 引用、日期、预算、依赖和历史合同无剩余具体规格阻断。质量复审进行中。主代理扫描本轮十个变更文本文件，凭据模式 0 命中。

后续 Graph / HITL 测试基线：移除宿主模型凭据、禁用 `.env` 并使用临时知识库，独立执行 graph_send / evidence_hitl / hitl_runtime_commands，**34 passed，1.97 秒**。

## 任务 3 接线决策

真实 Analyst 在函数内部直接合并知识、生成卡片与缓存；Graph 在调用返回后检查会过晚。批准最小跨文件接线：通过既有 runner 显式传 `expected_snapshot_id`，分支本地创建消费凭据，在三个实际合并 / 缓存入口验证，拒绝异常单独重抛；demo 同合同。旧 direct-call 可选参数保持兼容，任务 4 再全面替换实际提示与其他 Agent 输入。使用显式参数，不新增共享 latest-use 状态、不替换共享 RunDetail。

首轮实现者回放 RED：**13 failed，1.65 秒**，覆盖三类图冻结、问卷 / HITL 补采、固定 Send 身份、重复调用与 journal、旧 Send 拒绝、旧完成报告只读、恢复指针 / 摘要损坏、真实异步旧价格结果在合并前拒绝。初始功能转绿后扩展旧 fake 的明确合同及其他分支回放；尚未独立验收。

主代理补查阶段边界：在临时 journal 中封存 analysis、创建 Analyst 凭据，再以相同证据封存 collect；新 ID 已产生，但原凭据仍被验证为 `validated`。批准增加合并前阶段检查与真实等待回放，阻止旧分析进入补采待确认阶段；同一 analysis phase 内未变分支跨版本验证仍须保留。

阶段切换新增真实 RED **4 failed，1.29 秒**（one-shot / timeout / ReAct / cache，事实不变但 analysis → collect）。修复在既有消费验证中要求四类下游 Agent 当前 phase 为 analysis，拒绝沿用原持久化路径；本轮初步定向 **282 passed，4.97 秒**，另 **10 passed、302 deselected，2.04 秒**，仍待实现冻结、主代理独立验证及两级审查。

实现者全 RunService / 执行限制回归 **326 passed，16.10 秒**，差异 Ruff 新诊断为零。自查发现无快照的任意恢复 Command 会提前创建空 analysis，正在收紧到真正下游安全恢复入口；Planner / Evidence HITL 恢复仍由 collect / analyst_dispatch 正常冻结。另记录既有缓存键不含 normalized 事实值：本任务仅保护进行中的旧分支，缓存身份由任务 5 修复，不能把当前中间实现宣称为已完成更正缓存能力。

恢复入口收紧增加实际 Planner 提前封存 RED **1 failed**，修复后新增图回放共 31 个；实际 demo planner 恢复首次为 collect，旧 final QA 经 SQLite graph checkpoint 与 journal 重开后在下游安全入口建立首份 analysis，未知恢复入口明确拒绝。实现者最终定向 **611 passed，15.15 秒**，实现冻结。

主代理最终扩展独立回归 **614 passed，16.42 秒**（增加三项独立进程导入验证），禁用 `.env`、移除宿主凭据、使用临时知识库。七个受控文件 Ruff、差异检查通过；三个既有大文件与 `68e81b4` 的诊断代码 / 消息 / 原行内容比对，新增诊断为零。首轮父运行漏传子进程所需 PYTHONPATH 造成一个导入失败，修正测试环境后完整重跑取得上述通过结果。规格审查进行中。

规格补查注意到 scoped writer / comparator 入口复用现 collect 快照而未要求 analysis；主代理用临时 journal 和真实 scoped graph 独立复现两种路由均开始了 phase 为 collect 的下游调用。合同要求在入口明确拒绝、等待证据确认，不能强制升级绕过 HITL；等待本轮完整规格结论后统一补测修复。未知恢复入口拒绝的范围明确为无快照旧运行的首次安全入口，有合法快照的恢复仍沿原 Graph 中断协议。

首轮规格结论为未通过，仅上述 **1 项 P1**。独立审查 **36 passed**，包含 SQLite scoped checkpoint / journal 重开与四类下游 phase 拒绝，未发现第二个 Task3 范围内问题；已退回单一实现者补两种路由 RED 与最小入口检查，未进入质量审查。

入口修复真实 RED **2 failed、31 deselected，1.14 秒**；仅增加 phase 检查后定向 **7 passed、26 deselected，1.33 秒**，节点调用为空、快照 ID / hash / 历史与 journal 保持。实现者完整定向 **616 passed，16.69 秒**，含独立进程导入；实现重新冻结，父代理复跑及规格复审进行中。

主代理最终独立复跑 **616 passed，17.19 秒**，八个受控文件 Ruff、差异检查通过。继续规格复审，原 P1 通过后再启动独立质量审查；尚未更新真实服务。

独立规格复审通过：**38 passed，1.76 秒**；原动态 scoped bypass 探针拒绝 collect，完整快照 / journal 保持，无历史首封与已有 analysis 复用正常。没有剩余 Task3 规格阻断，已开始独立质量审查。

Task2 独立质量复审通过：**207 passed，2.52 秒**；真实临时数据库验证矛盾单值别名拒绝、合法单引用 / 多引用变更升版与旧消费拒绝、列表逆序复用、拒绝状态持久化及旧历史保持。原提交生成的三类旧快照兼容 / 篡改探针通过，六文件 Ruff 和差异检查通过；没有剩余规格或质量阻断，进入 Task3。

Task3 独立质量审查通过：**575 passed，15.19 秒**；额外探针核验四角色采集阶段拒绝及持久化、真实 Analyst 等待后未变依赖跨新 analysis ID 允许、两类 completed 状态只读及显式 writer redo 可达。固定 Send / 合并前检查 / ReAct 拒绝 / 恢复路径没有剩余具体质量问题。八文件受控 Ruff 和差异检查通过，本轮十二个变更文本凭据模式 0 命中；进入 Task4。

## 用户请求的密钥核查

2026-10-03 更新 origin 引用后，仓库元数据确认其为公开仓库。只在内存中读取本地配置里的 LLM 密钥并做精确匹配，未输出或写入密钥；扫描当前可达的 19 个 Git 引用、5,654 个历史 blob，精确密钥与长凭据模式均为 0 命中，本地前端构建产物亦为 0 命中。实际密钥位于被 Git 忽略的本地 `.env`；Git 跟踪的环境文件只有 `.env.example`。运行配置接口仅返回凭据是否存在的布尔值，不返回凭据内容。

结论限于本次检查到的可达提交与本地前端产物，不包含其他人的副本、删除后的 GitHub 缓存或第三方平台日志。用户此前在对话中发送过明文密钥，已建议更换并仅保存在本地配置；本阶段未主动撤销凭据或改写 Git 历史。

## 任务 1 定向验证

实现者提供了先失败后通过的记录：初始模块缺失 24 项失败，导入顺序 2 项失败，引用边界 4 项失败，摘要 / 市场 / 事实身份 / 版本类型补充 5 项失败。主代理独立运行以下最终命令，取得 **112 passed**；覆盖新增快照 / 导入测试及旧 journal / Writer EvidencePack 回归。

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_run_evidence_snapshot.py backend/tests/unit/test_evidence_imports.py backend/tests/unit/test_run_journal.py backend/tests/unit/test_active_run_journal.py backend/tests/unit/test_writer_evidence_pack.py -q
```

新审查代理因线程数量上限未能创建；复用未参与本任务实现的既有代理执行独立规格审查，保持实现与审查分离。

## 最终验收

尚未执行。完成后记录八项设计验收、实际 Agent 输入回放、缓存 / 重做调用计数、文档版本失效、完整回归、API 同步、运行数据核对及交付提交。
