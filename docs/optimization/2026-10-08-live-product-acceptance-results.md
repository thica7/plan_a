# 真实产品验收与价格证据改造交付

日期：2026-10-08。执行计划：[真实产品验收计划](2026-10-07-live-product-acceptance-plan.md)。

## 结论

本轮完成价格采集、证据准入、比较条件和诊断工具的修复。真实报告流水线仍未验收通过：三组公开任务都没有产出报告；最后代码上的 Notion 复跑仍被采集质检阻塞。不能宣称产品分析质量合格或 Comparator 已节省实际 Token。

最值得继续优化的是 **搜索选源和结构化证据提取**。Notion 最后一次运行中，搜索占提供商返回 Token 的约 95%；任务在进入 Analyst、Comparator、Writer 之前结束。

## 已实施

1. 价格分支显式要求金额正文。基础页面长度达标但缺金额时，在现有预算内尝试临时浏览器；预算不足时保留可用计费政策，同时记录价格缺失。
2. 动态价格页保留可见套餐、席位和金额布局，避免文章正文提取丢掉卡片标题。
3. 修复公开页面导航里的登录链接被误判为登录墙。标题、明确的访问要求和首屏实际账号密码表单仍会被识别；验证码、403、robots 和私有网络限制继续生效。
4. 提取具名套餐和席位的价格卡。支持 Notion 的分行币种、套餐脚注、推荐标签和分行显示单位。显示的“每月金额”与实际账单周期独立存储；没有选中状态证据的计费开关保持未知。
5. 准入端对捕获正文重新解析，要求价格卡整行 canonical JSON 完全匹配。伪造席位、币种、周期、当前价格分类或验证时间均被拒绝；保持原始引用与正文相符。
6. 修复比较门禁把字符串 `unknown` 当作已知值的问题。税费、账单周期、币种单位或市场未知时，不能提交价格赢家。
7. Comparator 仅将当前 Evidence View 中完全重复且更长的值/引文替换为事实 ID。不同小数、来源和限定条件保持原样；包含限定条件的嵌套对象或列表不能整体压缩。提示词版本升级为 `comparator.assessment / 3`。
8. 新增显式 `--live` 的验收脚本。默认只列任务；使用全新内存存储和临时产物目录，分别统计原生模型与搜索用量。取消任务时先停止流水线再关闭检查点；逐字符串脱敏后保存合法 JSON。中英文证据目录不能算产品分析。

## 公开价格页验收

公开浏览器采集成功后，使用最终解析器重放同一份保存正文，验证提取、准入和覆盖检查。此处通过的是价格证据闭环，不能推导完整报告已通过。

| 页面 | 捕获正文 | 接受的价格卡 | 价格覆盖检查 | 保留的未知项 |
|---|---:|---:|---|---|
| Figma | 8,564 字符 | 9 | 通过 | Professional 开关的选中周期、各卡税费和适用市场 |
| Notion | 5,556 字符 | 3 | 通过 | 开关的选中周期、税费和适用市场 |

Figma 的记录对应 Professional、Organization、Enterprise 的 Full / Dev / Collab 席位。Notion 对应 Free、Plus、Business，金额与 `member` 显示单位分别保存。具体数值和条件见[结构化验收结果](2026-10-08-live-product-acceptance-results.json)，来源为 [Figma 官方价格页](https://www.figma.com/pricing/)和 [Notion 官方价格页](https://www.notion.com/pricing)。

采集过程中也遇到过浏览器错误和超时。成功样本不能证明网络抓取稳定性；本阶段没有实现周期切换的 DOM 选中状态取证或完整账单核算。

## 真实流水线结果

| 任务 | 自动发现结果 | 结果 | 主要阻塞 |
|---|---|---|---|
| Notion，最终代码复跑 | Confluence、Coda | `failed / collect_qa`，4 个可用来源，报告 0 字符 | Notion 功能证据不足；Coda 价格证据不足 |
| Figma，本轮中期完整运行 | Adobe XD、Zeplin | `failed / collect_qa`，0 个可用来源，报告 0 字符 | 功能和价格两个维度均未形成可用证据 |
| iphone duo，本轮身份歧义测试 | Motorola Razr Ultra | `failed / collect_qa`，报告 0 字符 | 没有先确认目标身份就开始寻找竞品；目标产品证据不足 |

Notion 最后复跑耗时 93.43 秒；Figma 完整运行耗时 279.93 秒；歧义任务耗时 41.66 秒。Figma 的最后完整运行发生在最终价格准入修复之前；其最终代码全流程复跑未验收。身份歧义阶段逻辑尚未改造。

Notion 官方功能页中，许多句子只描述能力，不重复产品名。现有通用能力提取要求产品名出现在局部句子中，会漏掉官方页面的功能事实。抓取成功不等于抽取成功，也不等于证据足够覆盖所有竞品。

## 用量与收益边界

| 运行 | 原生 Agent 提供商 Token | 搜索提供商 Token | 搜索 span / 成功 span | 保守预算 Token |
|---|---:|---:|---:|---:|
| Notion，最终代码 | 6,994 | 127,555 | 34 / 11 | 134,549 |
| Figma，中期完整运行 | 7,857 | 68,042 | 35 / 8 | 129,982 |

提供商 Token 是每个 span 的最后尝试返回值；预算还可能包括失败调用的估算收费。两者不能混为实际账单。搜索 span 包括预算拒绝等失败，不等于对外实际请求数；成功 span 单独列出。

这些运行未到达 Comparator，不能归因得到上下文压缩的模型质量、Token 或费用收益。不同搜索结果、网络状态和运行时点也不能构成严格 A/B 对照。上一阶段保存的 v2 合成诊断结果仍属于旧模板，不代表当前 v3 的真实产品表现。

## 验证与复现

- 完整后端回归：**3183 passed、1 skipped**（67.51 秒）。动态采集与真实模型调用不计入离线 pytest。
- 跳过项是实机 Postgres RLS 烟测：未配置 `ENTERPRISE_RLS_SMOKE_DATABASE_URL`，本轮不声明该外部服务通过。
- vendored WebFetch 安全回归：**7 passed**。
- 新增/主要改动文件 Ruff 检查通过，`git diff --check` 通过。
- 独立复审发现的价格准入、币种冲突、鉴权误判、未知条件赢家、取消泄漏和 JSON 脱敏问题均补充了失败测试并修复。
- 当前改动位于本地分支 `codex/pastoral-desktop`，Git HEAD 为 `40e0f520b7923959c791fb197b741cfdff713200`；未提交的代码哈希保存在结构化结果中。

在仓库根目录执行；浏览器运行时需按 vendored 项目的可选依赖安装，不使用持久登录配置：

```sh
PYTHONPATH=backend ../plan_a/.venv/bin/python backend/scripts/eval_live_products.py
PYTHONPATH=backend ../plan_a/.venv/bin/python backend/scripts/eval_live_products.py --case notion-workspace --live --output /tmp/plan_a_live_acceptance/recheck
PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests -q
PYTHONPATH=third_party/webfetch_v2 ../plan_a/.venv/bin/python -m pytest third_party/webfetch_v2/tests -q
```

本机已安装可选 Playwright 1.63.0；测试 Chromium 位于 `/tmp/plan_a_live_acceptance/playwright-browsers`，使用时设置 `PLAYWRIGHT_BROWSERS_PATH`。完整脱敏运行和捕获正文留在临时目录，未读取现有业务数据库或导出凭据。

## 下一阶段优先级

1. **产品身份先确认。** 在竞品发现前区分已确认、需要澄清、证据不足。歧义名称展示可操作的澄清入口，避免猜型号后继续花费搜索预算。
2. **打通 Collector 证据闭环。** 官方页面采用页面身份约束下的功能抽取；保留原句、边界、主体及否定条件，防止把其他产品或客户证言归给目标产品。按缺失产品/维度定向补证，继续验证 Notion/Coda 和 Figma 任务。
3. **先压搜索成本。** 实测比较候选链接发现与正文抓取分开的策略；复用同一来源在多个维度的捕获结果，结束预算已耗尽的无效搜索循环。用相同任务和来源检查证据覆盖、提供商 Token、耗时，不能只比较输出字数。
4. **改善阻塞时的展示。** 展示已确认事实、失败来源与待补证项；保持“未完成分析”的明确状态，避免空白页面。证据不足时不能补造结论或发布赢家。
5. 全流程到达 Comparator 后，再测量同输入压缩前后的质量与实际用量。当前证据闭环优先于微调、蒸馏或 Agent RL。
