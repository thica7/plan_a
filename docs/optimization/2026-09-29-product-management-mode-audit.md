# 产品经理视角与运行模式审计

日期：2026-09-29。基线提交：`2036e74`。本文件记录现状、实测结果及待确认的改进方向；尚未改变运行模式代码。

## 1. 产品经理所需的分析层面

现有七个采集维度为 `feature`、`pricing`、`persona`、`review`、`market`、`integrations`、`security`。报告已有竞品矩阵、SWOT、决策摘要、引用与 QA。这能回答“有什么、多少钱、公开评价如何”。

| 产品决策问题 | 现状 | 建议补足 |
| --- | --- | --- |
| 要为哪个用户、场景和地区做什么决策？ | 产品画像含受众、场景、市场；`topic` 自由文本 | 增加明确的决策问题、目标用户和评估权重，避免报告只罗列事实 |
| 用户为什么会换产品？ | `persona` 有使用场景与切换触发；评论有抱怨主题 | 结构化记录用户任务、痛点、期望收益、替代行为及来源；参考 [Strategyzer 价值主张画布](https://www.strategyzer.com/library/the-value-proposition-canvas) |
| 相同任务下哪个体验更好？ | 功能与评论是间接信号 | 增加同任务的实际操作评分、完成率、耗时、失败原因；公开页面不能替代用户测试。方法可参照 [NN/g 竞品可用性评估](https://www.nngroup.com/articles/competitive-usability-evaluations/) |
| 购买与使用的总成本是什么？ | 结构化价格、方案与周期 | 扩展到迁移、培训、集成、维护、退出成本；无公开证据时标未知 |
| 产品如何获客并留住用户？ | `market` 和 `review` 可提供零散线索 | 明确渠道、分发、激活、留存与转化信号；私有指标需用户导入，不能由网页推断。指标设计可参考 [Google HEART 原始论文](https://research.google/pubs/measuring-the-user-experience-on-a-large-scale-user-centered-metrics-for-web-applications/) |
| 我们下一步该做什么？ | 有结论、SWOT 和待核验任务 | 输出按影响、信心、工作量排序的机会清单、验证实验与放弃理由；每项连接证据和未证实假设 |

优先补“决策问题 → 用户任务与价值差异 → 可验证行动”，再扩展成本、体验和增长。市场规模、份额等数字应要求可靠口径与日期，不用模型编造。

## 2. 当前三组开关的真实含义

| 现有字段／界面 | 实际作用 | 缺口 |
| --- | --- | --- |
| `competitor_layer=L1/L2/L3`，界面称“深度” | L1 直接战报，L2 相邻工作流，L3 市场全景；改变章节视角和场景规则 | 没有独立的“极简／适中／详细”资源预算；界面“越深采集越广”的说明与同输入实测不符 |
| `execution_mode=demo/real/auto` | 确定性演示资料／真实模型与搜索；`auto` 缺凭据时退到 demo | 这是数据来源模式，不等于“全 AI／半人工” |
| `hitl_enabled` | 一次计划审核、一次最终 QA 审核；可改计划、接受、强制放行或重做 | 只有布尔值，不能选择证据中途审核；默认值受是否手动填写竞品影响，用户难以预测 |
| `auto_redo_warn_enabled` | 无人工暂停时，扩大自动重做范围到 warning | 人工模式下自动重做被关闭；前端会清除该选项，但 API 仍可传两者为 true |

同一产品、一个竞品、`feature+pricing` 的实测：

| L 层 | 演示采集任务 | 演示来源 | 演示报告字符 | 实时计划每维来源目标 | 重做上限 |
| --- | ---: | ---: | ---: | ---: | ---: |
| L1 | 8 | 4 | 9120 | 5 | 2 |
| L2 | 8 | 4 | 9126 | 5 | 2 |
| L3 | 8 | 4 | 9122 | 5 | 2 |

三档产品场景 ID 相同，初始 `complexity=medium`，实时写作提示均要求 16,000–20,000 字符。差别主要是“战报／工作流／市场格局”章节。上述数字来自同输入的内存计划与确定性演示运行，不是线上成本或时延估计。

## 3. 运行与交互测试

| 检查 | 结果 |
| --- | --- |
| 后端完整回归 | 1489 passed、1 skipped；98 条 FastAPI `on_event` 弃用告警 |
| 前端完整回归 | 129 passed；TypeScript 与 Vite 构建成功 |
| WebFetch 独立安全测试 | 7 passed |
| HITL、产品契约、目标研究、报告质量等定向测试 | 93 passed |
| 前端交互审计 | 98 文件，0 errors、86 条已列入允许列表的警告 |
| 最小运行与 Temporal 薄壳烟测 | 均完成 |
| 全七维产品演示运行 | 完成；目标与竞品共 14 个矩阵单元、22 个演示来源、报告 9985 字符、0 条 QA 发现 |
| 自动模式演示运行 | 无人工暂停，直接完成；0 次 interrupt |
| 人工模式演示运行 | 依次在计划与 QA 暂停；两次 `accept` 后完成；2 次 interrupt |
| 实时运行创建 | 手动竞品默认 `hitl=false`，自动发现默认 `hitl=true`；显式设置可覆盖 |
| 无模型凭据 | `real` 创建被模型策略阻止；`auto` 创建为 demo |
| 密钥扫描 | 通过 |

人工运行首次短轮询中观察到 `interrupted/writer` 中间态；延长观察并保持原始运行对象后，确认后台按预期抵达 `qa_hitl` 并完成。这是测试观察窗口不足，不是已复现的产品缺陷。

**未覆盖的真实环境：** 未使用付费模型或真实搜索密钥执行全流程，未测真实网页的召回、成本与运行耗时；演示来源和 0 条 QA 问题不能证明线上报告准确。Chromium 浏览器在当前环境中也未安装。上线前仍需要多品类真实样本和人工判定金集。

## 4. 待确认的最小方案

| 方案 | 好处 | 代价／风险 |
| --- | --- | --- |
| **推荐：视角、深度、协作三轴分开** | 名称与预算一致，可独立测试；现有 L1／L2／L3 语义保留 | API、前端与任务预算需联动调整 |
| 继续把 L1／L2／L3 当深度 | 改动较少 | 会混淆直接竞品与市场全景，难定义稳定的成本和验收标准 |
| 完全按问题自动分配预算 | 对复杂问题灵活 | 成本不易预测，当前缺真实运行数据校准；适合后续迭代 |

将三个概念拆成独立轴：

1. **研究视角**保留 L1／L2／L3，明确叫“直接对比／相邻替代／市场全景”。
2. **研究深度**新增极简／适中／详细，真实控制竞品上限、维度、检索与抓取次数、独立来源目标、修复轮次、报告长度和成本上限。价格、事实时效和引文准入底线在三档一致；证据不足时缩小结论，不填补想象事实。
3. **协作方式**新增全 AI／半人工。全 AI 无等待点，QA 阻断仍保留；半人工先保留计划与最终 QA 审核，再加“证据归属与冲突”中途关口。人工强制放行需要保留原 QA 问题和理由供审计。

初始预算可从当前 `每维 5 个目标来源、最多 2 次重做` 向下／向上分档，但应以真实运行的质量、耗时和费用数据校准，不在界面先承诺分钟数。下一轮验收要覆盖三深度 × 两协作方式 × demo/real 的组合，以及暂停恢复、预算边界、报告章节和证据门禁。

## 5. 回归复现命令

从仓库根目录运行：

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m pytest backend/tests/unit/test_hitl_runtime_commands.py backend/tests/unit/test_product_research_contract.py backend/tests/unit/test_target_product_research.py backend/tests/unit/test_report_quality.py backend/tests/unit/test_writer_structured_report.py -q
PYTHONPATH=third_party/webfetch_v2 .venv/bin/python -m pytest third_party/webfetch_v2/tests -q
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend audit:interactions
.venv/bin/python backend/scripts/smoke_minimal_run.py
.venv/bin/python backend/scripts/smoke_temporal_thin_shell.py
.venv/bin/python backend/scripts/scan_secrets.py
```

完整后端测试包含自身进程检查，在受限执行环境下可能需要允许该项进程检查。模式矩阵的数值来自相同输入创建的内存运行计划，以及确定性 demo 完整运行；这些脚本未调用真实模型或搜索服务。
