# 三产品完整流程验收记录（2026-10-11）

## 结论

**本阶段采集、分析范围与审计回放修复已实施并测试。真实流程完成，但人工交付验收未通过。**

最后一轮耗时 212.76 秒，状态 `completed`，采集 7 个验证网页，报告 2501 字符，主内容 1548 字符，引用没有未知来源 ID。功能与定价 assessment 均为 `insufficient_evidence`；最终 QA 为 55 条警告。`completed` 仅表示当前工作流结束，不能作为产品分析可交付的证明。

[原始报告草稿](2026-10-11-complete-comparison-live-draft.md)逐字节保留真实工作流输出，没有人工补写缺失事实。[机器可读验收记录](2026-10-11-complete-comparison-results.json)保存版本指纹、采集价格、来源索引、预算和历轮结果。

## 已修复与验证的部分

- Coda 定价入口迁移至 Superhuman Docs；仅信任精确 Docs 和已登记帮助文档路径，同域 Mail、Go 内容不得进入 Coda 证据。
- 识别 Confluence Standard/Premium 定价卡片，以及 Coda Doc Maker 年付折月和单独月付金额。独立重解析的短 Free 价格行不再导致整个价格组被拒绝，未知币种和动态选择条件继续保留。
- 对已登记 Coda 公开文档的 HTTP 403，在额度内允许一次普通匿名浏览器获取；401、登录、验证码、robots 与 SSRF 限制仍有效。采集过程没有登录态或挑战绕过。
- 网页提取保留换行和标题结构，能力事实绑定对应小节及祖先限制；套餐、访问角色等全局约束跨小节保留。FAQ 问句不当作功能支持证据。
- 页面内 capability 序号只用于局部标识，避免不同来源的 capability_1 形成伪冲突；真正价格和语义冲突继续拒绝比较。
- 证据选择优先共同能力并保留完整观察、原文与条件；首次覆盖多个产品时优先能装入预算的观察，减少单一产品占满上下文。
- comparator/reflector 的事实集合来自合法分析分支实际消费事实的并集，范围与请求事实写入凭据并参与依赖哈希。只请求支持状态仍带入完整观察；冲突另一方缺失时保留 unknown。
- 汇总模型上下文保持 98304B 上限；本地 QA 恢复原始审计预算，修复其被模型上限截断而无法重放的问题。正文引用审计和完整上游依赖审计分别执行。
- 独立价格段保留计费单位和周期；逐条审核正文主张。报价不自动换算为完整账单，不把不同套餐名称直接映射为同档位。

## 人工交付验收

| 验收项 | 结果 | 依据与剩余问题 |
| --- | --- | --- |
| 固定三产品生产工作流 | 通过 | 实际运行规划、联网采集、各分析分支、比较、反思、分段写作和 QA；未替换为预写报告 |
| 正文引用存在性与产品归属 | 通过本例 | 引用均在本次来源集合内；仍不等于每条上游模型结论已由人工审核 |
| 功能正文内容 | 部分通过 | 有共享编辑、评论访问和页面锁定限制；无法形成三家在每个共同轴下的完整对照 |
| Confluence 定价 | 未通过 | 卡片金额已入库，但未证实币种、选中人数和计费周期；正文价格段为空 |
| 已采报价进入正文 | 未通过 | Coda 月付两条、Notion Business 和 Confluence Standard 未进入最终正文，短视图覆盖不足 |
| 上游矩阵真实性 | 未通过 | 摘要把最多29名队友写成最多29人；出现 Team 和重复 Pro 标签，正式事实与套餐身份未逐条绑定 |
| 派生上下文完整性 | 未通过 | 离线重放得到 38011B 证据 + 25296B 摘要 > 57344B；派生摘要被省略，不等于产品没有能力 |
| 十人团队完整采购比较 | 未通过 | 未核实付费角色构成、账期、地区、税费和功能所需套餐，不能给出总价或赢家 |
| 系统完成状态与交付状态 | 未通过 | 55条 warn 没有使需求缺口成为独立交付判定，机械通过不足以对外发布 |

这些缺口不是通过调低置信度或删除质量检查来解决。本轮结果也不能证明 RAG 已达到复杂检索或生产服务验收标准。

## 真实运行与预算

| 轮次 | 状态 | 秒 | 模型调用 / 修复调用 | 累计计费 token | 估算 USD |
| --- | --- | --- | --- | --- | --- |
| native | failed | 18.83 | 4 / 0 | 35234 | 0.012110 |
| fixed | completed_with_blockers | 205.68 | 43 / 11 | 182452 | 0.066989 |
| repaired | completed_with_blockers | 266.75 | 43 / 13 | 185467 | 0.064106 |
| public_docs | completed_with_blockers | 211.9 | 44 / 12 | 189857 | 0.062893 |
| final | completed_with_blockers | 181.42 | 43 / 11 | 183900 | 0.059125 |
| structured | completed | 285.38 | 41 / 9 | 173537 | 0.060558 |
| scoped | failed | 43.27 | 14 / 0 | 63898 | 0.019215 |
| delivered | completed | 212.76 | 33 / 0 | 148484 | 0.049165 |

最后一轮预算为 33 次调用、0 次修复调用，累计计费 148484 token，估算 0.049165 USD。各 span 最后一次 provider 用量合计 139854 token；这与累计计费预算的口径不同，不能混用。八轮总估算成本 0.394161 USD，不包含诊断探针，也不是供应商实际账单。

相较上一轮同一固定样本，最后运行的修复调用从9次降到0次、总调用从41次降到33次；单次结果受页面和模型变化影响，只能作为本例观察，不能据此声称稳定提升。

## 测试与审查

- 后端完整回归：**3386 passed，1 skipped，152 warnings，144.32秒**。现有警告包含依赖和 FastAPI 生命周期弃用提醒。
- 证据工作流专项：**77 passed**，包含大型本地单源预算回放、新旧凭据兼容、多分支生产者事实并集和比较/反思汇总。
- Webfetch 安全回归：**7 passed**，保留来源与网络边界检查。
- 前端 OpenAPI 和类型已同步，TypeScript 检查与 Vite 生产构建通过。
- 独立只读审查发现的角色限制遗漏、首次覆盖产品饥饿和本地 QA 预算问题均已复现并修复；最终限定增量审查未发现剩余可复现 P1/P2。审查结论不替代报告内容验收。

## 下一步顺序与验收目标

1. **先修正式事实到矩阵、正文的投影。** 用共同能力轴生成三方表格；套餐身份、价格和限制从已验证事实派生；摘要不得制造套餐或改变人数边界。模型负责解释差异，解释仍需核对引用。
2. **按意图分配上下文。** 价格优先覆盖套餐 × 账期，能力优先覆盖三方共同轴；压缩重复结构和引文引用，分别预算原始事实、派生分析和输出。溢出必须指出被省略的具体观察，不再泛化成产品缺证。
3. **定向补证。** 针对 Coda 共享编辑、三方权限条件和动态价格的实际人数、账期、地区、币种抓取对应官方页面。未知条件可展示采集金额及限制，仍禁止总成本排名。
4. **增加精简交付判定。** 单独检查用户要求的共同能力覆盖、报价条件覆盖、关键主张与引用的一致性，输出“可交付 / 有缺口草稿”。保持工作流结束与内容可交付两个状态的区别。
5. 用同一三产品样本验证：无空价格段或有具体原因与采集信息；已采年付/月付报价都展示；矩阵没有 Team、重复套餐或人数误读；所有剩余未知项都有下一步补证动作。

## 运行边界与本机服务

本例固定 Notion、Confluence、Coda，首轮自动发现未通过。验收脚本使用真实生产 LangGraph 和模型/搜索/网页工具，存储采用内存隔离；未验收 PostgreSQL、Temporal 或 Qdrant HTTP 生产依赖。不得把本例成功推广为这些服务全部可用。

本机 API 已重载，`/api/health` 与 `/openapi.json` 返回200，新证据消费字段已加载；健康响应的总体状态仍为 `error`，其中 `temporal_cutover=error`、`temporal_server=warn`。HTTP 可达不代表全部健康依赖通过，真实验收使用显式 LangGraph 配置。浏览器安装目录为 `/tmp/plan_a_playwright`，已配置 ignored `.env` 的 `PLAYWRIGHT_BROWSERS_PATH`。临时目录被清理后，在仓库根目录重新安装：

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/plan_a_playwright ../plan_a/.venv/bin/python -m playwright install chromium
```

运行验收的命令（在仓库根目录，`CASE_FILE` 为包含本记录固定请求的 JSONL 文件，使用现有本机凭据）：

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/plan_a_playwright PYTHONPATH=backend ../plan_a/.venv/bin/python backend/scripts/eval_live_products.py --cases "$CASE_FILE" --case notion-three-products --output /tmp/plan_a_complete_check --timeout 720 --live
```

代码仍在既有 `codex/pastoral-desktop` 工作区，保留所有原有未提交修改；本阶段没有提交或推送。`.env` 被 Git 忽略，交付记录不包含任何服务密钥。

## 原始报告引用索引

| 来源 ID | 产品 / 维度 | URL |
| --- | --- | --- |
| raw-source-b92f96c0c5e5d2643df7 | Notion / feature | [官方页面](https://www.notion.com/help/comments-mentions-and-reminders) |
| raw-source-f7a81bf787f1e9e932e7 | Notion / feature | [官方页面](https://www.notion.com/help/collaborate-with-people) |
| raw-source-a5a35d9a74b6bc0454f0 | Confluence / feature | [官方页面](https://support.atlassian.com/confluence-cloud/docs/create-edit-and-publish-a-page/) |
| raw-source-84d93774a937707e285a | Notion / pricing | [官方页面](https://www.notion.com/pricing) |
| raw-source-cfd5046889caadc3c3bd | Coda / feature | [官方页面](https://help.superhuman.com/hc/en-us/articles/46210367411469-Comment-on-docs) |
| raw-source-fc5559a8484790bb214f | Confluence / pricing | [官方页面](https://www.atlassian.com/software/confluence/pricing) |
| raw-source-2ee7fb10b23da736180d | Coda / pricing | [官方页面](https://superhuman.com/plans/docs) |
