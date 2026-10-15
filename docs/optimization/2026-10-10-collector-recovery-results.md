# Collector 采集修复与真实验收结果

日期：2026-10-10。分支：`codex/pastoral-desktop`。本轮修改未提交或推送；保留此前工作区修改。

## 判断

Collector 的确存在不合理的约束：将产品名逐句重复、特定连接词和引文字符数当成事实质量；确定性采集耗尽预算后又启动模型补采；官方来源表仅覆盖 AI 类产品。与此同时，原文绑定、产品归属、价格条件、访问权限和总预算仍应保留。

当前通过修复提高了固定官方资料的可用性，尚未形成足够通用的语义采集器。不要将字段数量或已有单元测试通过解释成 RAG/报告业务质量认证。

## 已实施

1. 功能提取保留正常并列组件及 18–23 字的有效中文引文，统一准入和引文质量口径。
2. 注册官方功能文档中的直接动作、第二人称功能句可以继承产品主体。引用保持原文和偏移，准入重新提取验证字段值、URL、原文和偏移。
3. 跨产品共同主语、已知兄弟产品、不明代词、客户引述和否定句继续拒绝作为正向能力。中文标题与 `API` 等组件缩写纳入正例。
4. 增加 Notion、Figma、Coda、Confluence 的官方身份与功能/定价入口；只登记入口，不写死套餐价格。新增身份不以名称前缀自动匹配兄弟产品。
5. 向 ReAct 传入每轮剩余搜索、抓取和高级抓取预算，过滤耗尽工具；搜索和抓取均耗尽时跳过模型补采。新鲜的同任务原生搜索缓存仍可免费读取；过期和刷新场景不可复用。
6. 修复 Notion 官方 HTML 标题注释引发 trafilatura 异常：解析前移除 HTML 注释。没有修改访问权限或网络保护。

## 固定官方资料采集

使用真实公开官方网页，HTTP 路径、不调用模型提取，共 8 个入口；完整原文保存在临时目录。基线是 HEAD 版本提取器处理**同一批最终捕获的正文**；基线字段数没有套用本轮新增准入规则，不能作为准入率或召回率。

| 产品 | 基线字段数 | 当前提取字段数 | 当前通过准入字段数 | 可用独立来源 | 现有功能覆盖检查 |
|---|---:|---:|---:|---:|---|
| Notion | 1 | 6 | 5 | 2 | 通过 |
| Figma | 1 | 6 | 6 | 1 | 未通过，要求 2 个来源 |
| Coda | 2 | 6 | 6 | 1 | 未通过，要求 2 个来源 |
| Confluence | 9 | 10 | 9 | 2 | 通过 |

- Notion 两篇官方帮助文档：2249 / 8371 字符；原先标题注释导致解析异常，修复后成功采集。
- Figma Dev Mode 指南：11463 字符；分类目录页仅 46 字符，不能当事实来源。
- Coda 更新页：33645 字符；表格帮助页返回 403，保留失败，没有绕过。
- Confluence 两个官方入口：8021 / 7686 字符。
- 短节选和关键词尚不能充分区分具体功能与泛化的营销表达，也没有完整编码所有套餐/权限前提；本轮没有做语义质量通过判定。

入口可直接复核：[Notion 协作文档](https://www.notion.com/help/collaborate-with-people)、[Notion 评论与提及](https://www.notion.com/help/comments-mentions-and-reminders)、[Figma Dev Mode](https://help.figma.com/hc/en-us/articles/15023124644247-Guide-to-Dev-Mode-in-Figma)、[Coda 更新](https://coda.io/product/whats-new)、[Confluence 功能](https://www.atlassian.com/software/confluence/features)。

## 完整 Notion 任务：仍未通过

通过现有验收脚本、新建内存存储，执行极简真实任务；没有读取现有业务数据库、浏览器登录资料或导出密钥。使用既有 DeepSeek 原生模型与搜索配置；单次预算沿用 60 次原生 LLM 上限、200000 Token。

| 指标 | 第一次复跑 | 最终代码复跑 |
|---|---:|---:|
| 耗时 | 64.60 秒 | 69.92 秒 |
| 最终阶段 | collect_qa / failed | collect_qa / failed |
| 通过准入的来源 | 5 | 5 |
| 原生 LLM span | 6 | 6 |
| 搜索 span / 成功 span | 28 / 10 | 28 / 10 |
| 提供商最后尝试 Token 合计 | 103407 | 121791 |
| 其中搜索 Token | 98510 | 117173 |
| 保守预算金额估算，USD | 0.03830532 | 0.038735244 |
| 报告正文字符 | 0 | 0 |

第一次复跑在最后的中文标题/组件缩写修复前启动；第二次使用最终代码。Token 是每个 span 最后尝试的提供商记录，预算金额是配置口径估算，不是实际账单。

两次均解决 Notion 功能缺失，取得 Notion 官方功能与价格、Confluence 官方功能和 Coda 官方更新来源。两次剩余阻塞均为：

- `No pricing source covers Confluence.`
- `No pricing source covers Coda.`

最终任务跳过了 3 次已无工具预算的 ReAct 补采。仍有 18 个 `collector_search_budget_exhausted` 搜索 span，相关提供商请求数为 0；来自其他可选/回退路径，未全面清理。搜索仍占最终提供商 Token 的约 96.2%。没有进入 Comparator/Writer，完整报告质量及压缩收益仍未验收；前后网络结果和模型输出不同，不能从单次数字推导受控节省比例。

## 验证与审查

- 功能主体、报价事实完成、原生搜索缓存、HTML 注释、通用提取定向回归：**102 passed**。
- 独立只读审查：共同主语、兄弟产品、否定、缓存、中文标题与缩写反例均复验；最终没有开放 P1/P2。
- 最终后端回归：**3231 passed、1 skipped、152 warnings，67.35 秒**。
- 首次普通沙箱回归只有进程归属测试因 `ps` 被系统禁止而失败：3230 passed、1 failed、1 skipped。未改测试或进程所有权校验；在允许进程查询的环境完整复跑后通过。
- 唯一跳过项是未配置 `ENTERPRISE_RLS_SMOKE_DATABASE_URL` 的 PostgreSQL RLS 烟测，仍未验收 HTTP Qdrant/真实 PostgreSQL 环境。
- `git diff --check` 通过。没有前端修改；此次没有重跑 UI 测试。

命令：

```bash
PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests -q --tb=short
PYTHONPATH=backend PLAYWRIGHT_BROWSERS_PATH=/tmp/plan_a_live_acceptance/playwright-browsers ../plan_a/.venv/bin/python backend/scripts/eval_live_products.py --case notion-workspace --live --output /tmp/plan_a_collector_recovery/live-current --timeout 600
```

指标及最终代码 SHA256 保存在同名 JSON。完整公开诊断在 `/tmp/plan_a_collector_recovery`，临时目录不可视作持久交付或业务运行记录。

## 下一步建议

1. **优先处理 Collector 的语义提取和局部缺口。** 在规则提取无结果时，用有界结构化模型提取事实、所属产品、原文位置及前提条件，再由程序校验原文绑定。保留未采纳候选和拒绝原因，使用当前共享证据快照供各 Agent 对齐。比较规则与模型路线的有效事实、错配、延迟和 Token。
2. **将报告门禁细化到事实/维度。** 功能事实可展示；缺价时暂停价格比较、列出缺口并支持定向补证。当前整份报告会因局部缺价保持空白，需另行设计带缺口报告的发布状态，不能直接当成功报告。
3. 为修复保留预算并统一调度可选搜索，减少零结果回退与社区搜索；保留跨任务历史复用的实时核验边界。
4. 对未知产品名称先澄清身份；本轮固定注册表不能解决 `iPhone duo` 这类不明确名称。否定事实/能力限制的结构化表示仍需后续工作。

本轮不需要用户提供新的密钥或安装服务。上述后续涉及报告发布语义和模型提取路线，应作为下一阶段方案实施并单独验收。
