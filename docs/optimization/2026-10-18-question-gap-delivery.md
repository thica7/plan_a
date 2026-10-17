# 问题缺口驱动补证交付

日期：2026-10-18。对应[实施计划](2026-10-18-question-gap-plan.md)、[结构化结果](2026-10-18-question-gap-results.json)与 [Agent 执行说明](../agent-execution.md)。

## 结论

通用问题补证已接入生产 Collector，工程回归通过。Miro Visitor 的规则和 GitBook Chat 的套餐证据已进入正文；最后一次 GitBook 运行也保留了授权后端限制及正确的请求报价日期。

**仍不能宣称三份完整报告达到交付标准。** 最新选择的八题正文为 **7 正确、1 遗漏**，但三份都有未解决的发布阻断，**0/3 完整报告可交付**。正文核对由只读代理在生成后对照用户已审核、已曝光的参考完成，不是项目用户对新报告的人审，也不是盲测准确率。

Miro、Basecamp 使用首轮版本；只有 GitBook 用最终版本完整重跑。Basecamp 在最终版本上的验证是旧模型响应的离线解析重放，不能冒充新生成报告。

## 1. 实现内容

- **问题合同**：把显式功能问题按产品分配到 `ResearchBrief.questions`，保留原问和稳定 ID；Collector 与 Writer 使用同一作用域。问题、角色、预算和输出要求只作为检索请求。
- **问题证据评估**：只检查同产品、同维度、已准入完整观察。严格验证问题 ID 与 evidence ID；拒绝、跨产品、重复或未知 ID 不能关闭缺口。`candidate` 只是候选证据，不是已回答。
- **通用补证**：先按缺口 focus 重用现有正文，再使用原 brief 剩余的候选、搜索和抓取额度；最多一轮、两次评估。未带显式问题的分支保留既有补证流程。预算在没有 `research_depth` 时仍生效。
- **选择与身份**：按问题排序页面，选择不超过 12000 字符的完整连续窗口。多个问题且全文可容纳时保留全文。缓存与提取版本绑定问题、正文和窗口；字段身份绑定原文位置和上下文，修复不同套餐同句被去重。
- **完整条件**：支持明确可用性与否定规则、被动角色、任意显式套餐名；外层权限设置与括号内限制分别绑定。完整非货币句可以保留邻近费用上下文，不生成结构报价。注入、价格 quote、错误位置和未经验证的来源继续拒绝。
- **消费链**：新增观察重新准入，合格来源在抓取预算内保留后进入 RawSource、知识库、快照及正常下游 Agent。Writer 和 QA 不绕过快照补证。
- **容量和停止**：评估输入最多 12000 bytes、输出最多 700 token，完整记录装不下时保留省略计数和 `unverified`；无进展、容量、预算与权威问题分别追踪。证据依赖拒绝继续抛出。
- **回答边界**：支持“看不到／不会”等中文否定答复；明确中文报价日期不再被运行日期替换。套餐包含关系不能升级成排他结论或强制升级建议；有限规则要求被引用主张中存在相同套餐集合的明确限制，未知范围保守保留。它不是通用语义蕴含证明。

固定官方来源诊断入口已启用实际补证；重复 URL 不再增加独立来源数量要求。没有加入产品专用固定答案。

## 2. 工程验证

- 最终完整后端：**4934 passed、1 skipped、212 warnings**，178.39 秒。
- 首轮完整后端：4907 passed、1 skipped，另一个进程归属测试因沙箱禁止 `ps` 失败；该项在允许进程检查后单独通过，再执行上述最终完整回归。没有删掉归属检查。
- 前端：**279 tests / 55 files**，构建成功；本轮没有修改前端源码。
- OpenAPI 导出与既有 JSON 逐字一致；公开 API 合同未改变。
- 变更 Python 的 Ruff `E9,F`、`git diff --check` 通过；不宣称仓库全部风格规则通过。
- 新增匿名回归覆盖问题分配、容量、ID/位置绑定、拒绝证据、补证上界、无 depth 预算、原文重用、响应式重复、邻近费用、角色套餐、回答否定、套餐排他集合和中文日期。规格与质量独立审查发现的问题均已修复并复核。
- 当前配置凭据原值扫描覆盖 1301 个文本文件（含前端构建和本轮诊断），0 命中；1280 个版本库及非忽略候选文件的密钥模式扫描也为 0。未跟踪真实 `.env`；本轮扫描不涵盖 Git 历史。

测试命令：

```bash
PYTHONPATH=backend:backend/tests/unit .venv/bin/python -m pytest backend/tests -q --tb=short
pnpm --dir frontend test
pnpm --dir frontend build
```

本机沿用相邻 checkout 的虚拟环境，Python 路径为 `../plan_a/.venv/bin/python`。

## 3. 真实运行与开销

每组仍为 **24 次调用 / 80000 token**，通用输出 2048、Writer/审核 1600、问题评估 700，重试 0。实际返回模型标识 `deepseek-flash`。四次尝试全部保留，没有第五次运行。

| 尝试 | 调用 | provider token | 正文字符 | QA blocker | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| Miro | 10 | 32069 | 1001 | 1 | Visitor 题正确；Guest 来源安全校验失败 |
| Basecamp | 10 | 34244 | 2016 | 1 | 正文含三题结论，前两题状态表误标未核实 |
| GitBook 首轮 | 10 | 33574 | 2014 | 2 | Chat 证据找到，但新增“仅 Enterprise”错误；授权遗漏、日期漂移 |
| GitBook 定向重跑 | 10 | 36318 | 1687 | 2 | 三题正确内容进入正文，引用覆盖和金额门禁仍阻断 |

合计 **40 次调用 / 136205 provider token**，本轮无缺 usage 的调用。该统计不等于供应商金额账单。搜索与外部 embedding 调用为 0。

Analyst、Comparator、Reflector 在四次尝试都实际使用模型，Writer 及审核也均执行，Writer producer 验证通过。固定来源没有执行 Planner 自动发现、完整 Graph 调度或生产稠密索引验收：canonical 仍为 sparse，Writer 的问题选证独立使用本机 E5，未使用精排。

### 版本与复现

- 三组首轮 production SHA256：`4dd878c38be9d86b6c010b8e53339764bf992d8739655a755857dd455e91f781`。
- GitBook 最终 production SHA256：`150bc173b74967d3be836585c1726e03ab84816e30b54d2d4222bae62fb4da19`，运行后核对未变化。
- Miro 输入 SHA256：`f6d0dacb30703e4c92164306783b4c06c01af4abf67aeabb6d7fea88b3182279`。
- Basecamp/GitBook 输入 SHA256：`1925b319a40380486fede510fe704c6507c12029ec36689c440b0987723e6ea9`。
- 官方登记 SHA256：`0b4da106478510ea008356db516eb7e699bb88e00866747720f92b64b3b2af16`。

忽略目录 `data/artifacts/question-gap-2026-10-18/` 保存四组 manifest、runtime inputs、run、trace、snapshot、summary、report、canonical 数据库及 source probes。入口 `backend/scripts/eval_answer_official.py` 先预览并锁定输入、登记及 manifest 哈希，再执行 `--run`；只有问题与来源身份进入 Agent，不传参考答案或验收结论。

## 4. 正文与正式验收分别判断

| 最新报告中的题目 | 正文核对 | 剩余问题 |
| --- | --- | --- |
| Miro Free Visitor 编辑/评论 | 正确但回答绑定不足 | 正式 Visitor 页面成功；覆盖所绑 claim/span 是工具栏及无限邀请，未直接支撑套餐限制，不能靠同页引用放行 |
| Miro Guest 登录与 A/B | 遗漏 | 正式 Guests 页面 403 / 安全验证，未取得合格当前正文 |
| Basecamp 私密消息 X | 正确 | “看不到”旧校验漏识别；最终版本仅离线重放通过 |
| Basecamp 项目 A/B | 正确但论据需精确绑定 | 正文引用同页来源；推理应直接绑定获邀项目规则，不能仅靠用户类型跨项目一致推出 |
| Basecamp Outside Collaborator/Admin | 正确 | 保留账号日期例外与澄清；未用最终版本完整重跑 |
| GitBook Essential/Chat | 正确 | 最终正文保留完整套餐范围；覆盖响应引用两个 claim ID，却只给一条 span |
| GitBook 后端授权 | 正确 | 最终正文明确未授权不能查看；覆盖响应引用三个 claim ID，却只给两条 span |
| GitBook 中国含税人民币月费 | 正确的不足答复 | 指定日期保留；不代表当前报价已获得 |

首轮三份正文核对为 **4 正确、1 局部、2 遗漏、1 错误**。最终替换 GitBook 后为 **7 正确、1 遗漏**，不能把不同版本样本拼成最终版本的端到端准确率。

初次只读核对 `/private/tmp/plan_a_v23_semantic_review.json` 的 SHA256 为 `7dc2bc28731a259a6464a3ae8f7de8530f841e878c67baa2e708d819359f41bd`；最新核对另存 `/private/tmp/plan_a_v23_final_semantic_review.json`，SHA256 为 `1a352443c8e7f79e2c554a17dea9902a8f9571626a39df4a031f0dbaa71725c7`。原始核对文件及旧报告没有改写。

GitBook 的另一个金额 blocker 来自 AI credits 赠送额度被金额边界检查归入采购现价范围。原文有该额度，不代表它就是 Enterprise 中国含税报价；目前两者的结构分类不足，不能用关闭金额门禁解决。

## 5. 下一步

1. 把问题回答、所需 claim IDs 与逐项 span 做成一致的生成合同；当前正文正确但状态表显示未核实，应定位缺片段的主张，不能静默删除缺证引用来放行。
2. 区分功能使用量、赠送 credits 额度和具体采购报价，逐条绑定对应金融口径；减少无关金额进入正文。
3. 给问题评估做完整上下文的去重与分配。本轮 GitBook 最后评估 32 条候选，省略 24 条，仍触发容量不足；不能靠截断条件或无限补抓处理。
4. 完善推理到具体事实的绑定，再对最终版本重跑三家；Miro Guest 抓取限制要单独处理，不以旧正文冒充当前成功。
5. 已曝光回归通过后准备新的独立人审题，并由项目用户验收最终正文。

本机没有运行 Docker。Qdrant HTTP、Redis 集成、多 worker、Temporal 与实机 Postgres 维持未验收状态。运行原始资料、数据库、模型权重和本机凭据不提交 Git。
