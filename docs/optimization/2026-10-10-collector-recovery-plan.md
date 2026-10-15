# Collector 功能采集与预算衔接修复计划

> **For agentic workers:** 使用 executing-plans 顺序执行；修复遵循 test-driven-development；交付前使用 verification-before-completion 和 requesting-code-review。

**Goal:** 修复已授权下一阶段中的官方功能提取和无效补采，让 Collector 少漏采、少空转，同时保持事实准入。

**Architecture:** 沿用候选发现、抓取、字段提取、证据准入和覆盖检查。允许已确认官方文档中指向当前产品的无主语或第二人称功能句继承文档主体；保留原句与偏移，并在准入时重新校验。沿用现有分支预算，向 ReAct 显式传入余量并过滤耗尽工具。

**Tech Stack:** Python、pytest、现有 entity_resolver、ResearchBrief、RunService、DeepSeek 和 webfetch_v2。

## 授权与范围

用户已允许执行上一轮下一步（身份澄清、官方功能提取、定向补证）。本轮先完成其中有明确失败证据的 Collector 修复。沿用隔离工作区和未提交修改；不自动推送 GitHub。

已确认的问题：

- `extract_generic_capabilities` 要求每句动词前重复产品名，并拒绝主语中的任意连接词。官方文档的标题主体、正常并列功能因此可能丢失。
- 引文质量允许 18 字以上中文句，准入层却另设 24 字硬门槛，两层口径冲突。
- 现有官方来源注册表仅覆盖 AI 类产品；当前公开验收的 Notion、Figma、Coda、Confluence 没有固定官方入口。
- 极简分支的 1 次搜索、3 次抓取经前置采集消耗后仍启动 ReAct。2026-10-08 Notion 记录中 34 个搜索 span 有 23 个 error；其中含预算耗尽，不可全部当提供商错误或实际收费调用。

### 方案选择

1. **采用：修复确定性误拒 + 官方入口 + 剩余预算。** 无新增外部模型提取调用，故障可复现。
2. 全面移除提取、报价和覆盖限制：容易串产品或将政策金额当价格，不采用。
3. 立即改成 LLM 自由抽取：可能提高召回，但需另外评估主体错配和费用，暂缓。

### 边界

- 继承主体必须是注册表中的明确官方功能文档 URL、包含当前产品名的文档标题、非对比/客户案例/第三方评价页面；句子只接受直接动作或第二人称写法。显式其他产品、共同产品主语、`it` 等不明代词、引述和否定句仍不作为正向能力。中文标题与 API 等组件缩写保留；不要求与种子标题逐字匹配。
- 不把未知或否定事实写成 supported。本轮保留现有否定过滤；后续单独设计限制条件的结构化表示。
- 只取消重复长度门槛，仍执行统一引文质量规则；新通用功能字段必须绑定抓取正文原文、URL、偏移与提取字段，防止伪造继承主体。
- 保留现有源数量、价格条件、robots、网络和总预算规则。本轮不将有缺口的报告视作成功。

## Task 1：复现官方功能误拒

**Files:** `backend/tests/unit/test_collector_feature_scope.py`，`backend/packages/research/extraction/feature.py`，`backend/packages/research/evidence/admission.py`。

- [x] 用固定中文并列功能句和短中文句，验证“支持”事实不会因连接词或 18–23 字引文被误拒。
- [x] 官方文档的 `You can ...`、直接 `Supports ...` 句可继承产品；对比、案例、第三方、伪域名、跨产品句和否定仍拒绝。
- [x] 先运行测试观察预期 RED，再以最小辅助函数修复主体判定；不改遗留 AI 槽位提取器。
- [x] 准入重新提取并校验新功能字段/原文引用；错误 URL、偏移、字段值和不存在于正文的句子不能准入。

```bash
PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_collector_feature_scope.py backend/tests/unit/test_generic_product_extraction.py -q
```

## Task 2：补充本次验收产品官方入口

**Files:** `backend/packages/business_intel/entity_resolver.py`，`backend/tests/unit/test_collector_feature_scope.py`。

- [x] 使用官方网页确认 Notion、Figma、Coda、Confluence 的身份、功能文档和定价入口；注册表只存 URL 和身份，不缓存当前价格。
- [x] 测试每个产品的官方功能与价格候选存在、近似域名不受信任，且 Confluence 不把 Atlassian 的其他产品视为同一文档主体。
- [x] 对新增固定样本运行提取→准入→覆盖检查，记录正例与反例。

## Task 3：预算耗尽后停止无效补采

**Files:** `backend/packages/agents/collectors/logic.py`，`backend/tests/unit/test_collector_fact_completion.py`。

- [x] 测试搜索/抓取均耗尽时不启动 ReAct LLM；搜索耗尽但仍可抓取时保留抓取和本地官方发现，并告知余量。
- [x] 按每轮实际余量更新允许动作，避免耗尽后的搜索回退；不提高现有调用上限。
- [x] 无预算返回已取得候选和覆盖缺口；不伪造事实完成。

```bash
PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_collector_fact_completion.py backend/tests/unit/test_run_service.py backend/tests/unit/test_agent_prompt_contracts.py -q
```

## Task 4：验收、审查和交付

- [x] 使用公开官方资料做独立采集；完整原文仅保存在临时目录，交付文档保存必要指标。
- [x] 用内存存储重新跑 Notion 极简真实任务；记录完成状态、功能覆盖、来源、搜索错误原因、提供商 Token；未通过也完整披露。
- [x] 独立代码审查，必要修复后执行后端回归；真实流水线成功前不声明报告验收或费用收益通过。
- [x] 写本轮结果文档。身份歧义澄清和限制事实表示仍作为单独后续工作，避免将 Collector 恢复与 UI/HITL 重设计混成一次改动。

## 执行补充

- 实采复现 Notion HTML 标题中注释节点令 trafilatura 抛出 `AttributeError`。增加 `test_fetch_html_comments.py`，先观察失败，再在 `HTMLParser` 设置 `remove_comments=True`；公开文档重新采集恢复。
- 独立审查复现了共同产品主语、兄弟产品文档、否定写法、缓存误挡、中文标题与 API 缩写误拒。逐项增加反例/正例并修复，最终指定回归 102 passed，无开放 P1/P2。
- Task 1–3 的修复和测试已完成；Task 4 的真实采集、两次 Notion 流水线、独立复审及后端回归均已执行，结果见同日交付文档。完整报告仍失败，不作为功能验收通过。
- 本轮没有清除所有可选工具的预算耗尽空尝试；最终真实任务仍有 18 个此类搜索 span，实际提供商请求为 0。后续需统一可选分支调度与跳过原因。
