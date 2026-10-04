# 离线双语关键词召回交付

日期：2026-10-04；工作分支：`codex/pastoral-desktop`；比较基线：`7527bd2`。代码交付提交：`e9c9600`（含本轮前序提交），已推送并核对远端 HEAD 一致。交付文档的最终提交与远端核对见本轮最终回复。

## 完成的改动

1. 保留原严格关键词查询，结果不足时增加 23 类通用概念的中英别名匹配。概念之间、未知词和数字限制仍须同时满足；只剥除完全由固定问法构成的中文片段，保留“智能”“性能”等真实限制。超过 8 个概念或 12 个未知词时关闭补召回。
2. 补召回只搜索正文；正文与标题命中分别评分。SQL 在截取结果之前应用 workspace、project、product、market、role、时间过滤。来源正文、原元数据、分块和索引版本没有写回或迁移。
3. 增加 `tuning-diagnostic`，只纳入 tuning 样本；原 evaluation、候选诊断与正式人审门槛保持分离。支持 `lexical_policy=strict|bounded`，记录原问题、查询表达式、实现版本及源码 SHA256。
4. 文档召回指标之外，分别记录支持原文片段覆盖和按来源去重的非 gold 来源数。标题命中文档不能证明已检索到支持片段。逐命中 `strict_body` / `fallback_body` / `title` 路径仅由 bounded 提供；strict 基线的该诊断为 null。

设计和实施清单见 [召回设计](2026-10-04-lexical-recall-design.md)、[实施计划](2026-10-04-lexical-recall-plan.md)。本轮不增加依赖、下载权重或调用外部模型。

## 实际对照结果

冻结实现后，先跑独立合成资料，再对原 13 条候选问题各执行一次 strict / bounded 对照；同一组内 corpus、原问题、标签及源码 hash 均保持不变。没有根据原候选结果修改词典或标签。

完整逐题来源、查询计划、片段、指标、运行耗时和输入 hash 已保存在 [召回对照 JSON](2026-10-04-lexical-policy-comparison.json)。

| 固定资料 / 指标 | strict | bounded |
| --- | ---: | ---: |
| 合成资料：9 道 answer，Recall@5 / MRR / nDCG@5 | 0 / 0 / 0 | 1 / 1 / 1 |
| 合成资料：平均支持片段覆盖 | 0 | 1 |
| 合成资料：5 道 insufficient 的空结果数 | 5 | 5 |
| 原候选资料：5 道 answer，Recall@5 / MRR / nDCG@5 | 0 / 0 / 0 | 0 / 0 / 0 |
| 原候选资料：平均支持片段覆盖 | 0 | 0 |
| 原候选资料：7 道 insufficient + 1 道 clarify 的空结果数 | 8 | 8 |
| 两组 answer：平均非 gold 来源数 | 0 | 0 |
| 外部模型调用数 | 0 | 0 |

合成集共 13 个虚构来源、14 道 tuning 问题，验证的是匹配与隔离合同。原资料有 50 道问题，只有 13 道具备候选标签，37 道没有标签，人工审核为 0；未标注题没有进入指标。两组标签均不能替代正式人审。空结果和零非 gold 来源数也不代表回答事实正确或真实误报率为零。

### 尚未解决的实际问题

- 原候选 008 / 023 / 026 / 030 包含大量未覆盖的自然语言限制，触发 `too_many_literals`。没有为了提高数字而去掉这些限制。
- 028 混合了事实检索和“输出中文并保留出处”的格式要求。目前词法计划仍把后者作为检索条件，其中“保留”还对应 retention，造成过度约束；这说明检索意图与输出要求需要明确分离。
- 常用双语术语匹配改善了，但复杂中文问句到英文证据的语义匹配仍未得到验证。不能据此宣称当前 RAG 已合格。

## 验证与审查

| 验证 | 本轮实际结果 |
| --- | --- |
| 隔离临时 cwd / DB 的完整后端回归 | **2728 passed，1 skipped，152 warnings，61.21s** |
| 父独立执行的五组定向测试 | **70 passed，2.41s** |
| fresh QUALITY 五组 / scope 与缓存验证 | **70 passed / 56 passed** |
| 与 `7527bd2` 对比的增量 Ruff | 6 个 Python 文件，新增诊断 0，各文件当前诊断 0 |
| SPEC、QUALITY、产品集成审查 | 通过；没有未解决的 Critical / Important |
| 原 evaluation 三份 JSONL | 没有改动；对照期间输入文件 hash 不变 |

完整回归没有读取本地环境文件，清除了宿主付费模型与数据库凭据，运行数据落在临时目录。进程管理测试只管理测试创建的临时进程。唯一跳过项是缺少 `ENTERPRISE_RLS_SMOKE_DATABASE_URL` 的真实 Postgres RLS 测试；152 条警告来自既有 FastAPI `on_event` 用法，本轮没有扩大修改范围。

提交前对 Git 跟踪文件及本轮新增交付文件执行密钥模式扫描和 diff check。扫描结果仅说明所检查文件未匹配已知凭据模式，不能证明外部账户或未扫描历史没有泄露。

## 复跑入口

使用项目已有 Python 环境，从仓库根目录执行；每次将输出写到不同文件，以保存两政策记录：

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python \
  -m packages.knowledge.product_benchmark \
  --mode tuning-diagnostic --lexical-policy bounded \
  --corpus eval/product-research-tuning-corpus.jsonl \
  --queries eval/product-research-tuning-queries.jsonl \
  --labels eval/product-research-tuning-labels.jsonl \
  --output /tmp/plan-a-tuning-bounded.json
```

将 `--lexical-policy` 改为 `strict` 并使用不同输出路径可复跑严格基线。原候选资料使用 `--mode candidate-diagnostic` 与原三份文件；正式 `--mode formal` 仍要求真实 reviewed 标签，不应把候选改成 reviewed 来运行。

## 下一步的优先级

1. **先确认真实评测资料。** 已准备 [5 条代表样本审核单](2026-10-04-product-research-review-sheet.md)，逐项确认完整回答、市场、日期及引用范围。008 的更新年限不等于绝对截止日；价格题要确认币种和计费周期；Slack 可见历史与删除期限需要分别核实。审核者和审核时间仍未登记。
2. **分离检索意图与输出指令。** 在 workflow 中使用明确的事实子问题、产品 / 市场 / 时间限制和输出格式字段；格式要求不进入事实查询。复杂问题需拆成可核对的子问题，保留原问题与拆分记录，避免无依据地删限制。
3. **比较真实多语 embedding 与 reranker。** 在具备人审资料后，比较 dense、sparse 和融合结果；验证语义召回、引用片段与噪声，再决定模型。当前没有执行真实双塔、精排、微调、蒸馏或 Ragas；本轮未下载任何权重。

Qdrant HTTP、完整联网调研、真实模型生成与答案事实评测的既有未验收状态保持不变。这次结果不评估报告质量、token 费用或 agent 的澄清行为。
