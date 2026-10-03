# 共享证据快照实施与验收记录

日期：2026-10-03。用户已确认设计与实施计划。实施基线：`6b42b30`；分支：`codex/pastoral-desktop`。

状态：正在实施，尚未完成第二阶段验收。本文仅记录实际完成和核验的工作，不把设计目标视为可用能力。

## 实施环境与约束

- 复用已有 linked worktree：`plan_a_pm_modes`，未创建新工作区。
- Python 使用现有共享虚拟环境 `../plan_a/.venv/bin/python`；不新增依赖或下载模型。
- 测试禁用本地 `.env`、使用临时数据库；不调用付费模型、搜索服务或新增真实报告。
- 运行中的 8000 / 5173 服务保持当前已验收版本；完成第二阶段回归前不更新真实运行数据。
- 不部署 HTTP Qdrant，不迁移旧未知归属资料；语义质量和完整联网报告仍需后续验收。

## 基线核查

- 工作区开始时无未提交改动，基线已推送 GitHub。
- 独立运行 `test_run_journal.py`、`test_active_run_journal.py`、`test_graph_send.py`：**16 项通过，0.97 秒**。
- 第一阶段已有完整后端 / 前端验收；本阶段业务改动完成后重新执行必要定向与完整回归，不沿用旧结果宣称本阶段通过。

## 任务状态

| 任务 | 实现 | 规格审查 | 质量审查 |
| --- | --- | --- | --- |
| 1. 快照模型、确定性版本与持久化 | 完成，171 项独立回归通过 | 第二轮通过，98 项核验 | 第二轮通过，98 项核验 |
| 2. 可信引用解析与阶段视图 | 待执行 | 待执行 | 待执行 |
| 3. 图冻结时点与进程恢复 | 待执行 | 待执行 | 待执行 |
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

## 任务 1 定向验证

实现者提供了先失败后通过的记录：初始模块缺失 24 项失败，导入顺序 2 项失败，引用边界 4 项失败，摘要 / 市场 / 事实身份 / 版本类型补充 5 项失败。主代理独立运行以下最终命令，取得 **112 passed**；覆盖新增快照 / 导入测试及旧 journal / Writer EvidencePack 回归。

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_run_evidence_snapshot.py backend/tests/unit/test_evidence_imports.py backend/tests/unit/test_run_journal.py backend/tests/unit/test_active_run_journal.py backend/tests/unit/test_writer_evidence_pack.py -q
```

新审查代理因线程数量上限未能创建；复用未参与本任务实现的既有代理执行独立规格审查，保持实现与审查分离。

## 最终验收

尚未执行。完成后记录八项设计验收、实际 Agent 输入回放、缓存 / 重做调用计数、文档版本失效、完整回归、API 同步、运行数据核对及交付提交。
