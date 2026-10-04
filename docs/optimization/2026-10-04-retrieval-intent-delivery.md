# 检索意图分离与真实样本补核交付

日期：2026-10-04。工作分支：`codex/pastoral-desktop`。本轮基线：`b1cb4d2`。

## 结论

本轮补齐了可传入结构化事实查询的生产入口、保守的输出格式分离及可复现的政策对照。它解决部分词法查询被格式指令干扰的问题，**尚未解决复杂自然语言检索，不能宣称 RAG 已合格**。

5 条真实候选已重新核查官方资料，但这只是 AI 核查，人工审核数仍为 0。原候选的 5 道答案题在本轮 raw / structured 回放中召回率仍为 0。真实多语 embedding、精排、答案生成和 Ragas 均未执行；本轮外部模型调用为 0。

## 已实现

- 新增 `RetrievalIntent`：最多 5 条事实查询、明确需要保留的词、输出语言和引用要求。它不能携带工作区、产品、市场、角色或时效授权字段。
- 自动分离分句边界后的完整已知格式后缀，例如“输出中文并保留出处”。正文中的“中文支持”“消息保留”“引用功能”和未知格式保留。原始问题始终保留。
- 显式事实查询由调用者声明；保留 `required_terms` 和原问题中非完整产品名内部的阿拉伯数字字符串。这个检查不是数值事实验证，不能保证单位、否定条件或复杂原意完整。
- 每条事实查询沿用原请求的授权、市场、来源角色和时效过滤；多列表 RRF 去重、精排使用事实查询；变更计划绕过 LLM rewrite。缓存区分意图并继续 canonical 回查。
- API 和 RAG tool 可接收意图；返回真实 `query_plan` 和最终保留命中的事实分组。没有改造所有 agent 的自动拆题流程，也没有重构共享证据快照。
- Benchmark 默认 `raw` 保留基线，支持 `structured` 和显式 JSONL 意图文件。拒绝额外答案字段、非法/重复/非选中 ID 及 raw 与意图文件并用；记录输入 hash、每条实际词法表达式及原问题。旧 `lexical_plan` 标为 `legacy_original`。

## 冻结回放结果

完整记录：[意图对照 JSON](2026-10-04-retrieval-intent-comparison.json)。`top_k=5`，词法政策均为 `bounded`，临时 SQLite，共享固定 corpus；每题清空响应缓存，不运行外部模型。

### 独立虚构调参样本

9 题：4 道答案题、5 道资料不足题。新查询、标签和意图文件与原 evaluation 分开，全部为 candidate / tuning，不是人审 gold。

| 策略 | 答案题平均文档召回率 | 支持节选覆盖率 | 资料不足题返回空 | 非 gold 来源均值 |
| --- | ---: | ---: | ---: | ---: |
| raw 原始查询 | 25% | 25% | 5/5 | 0 |
| structured，仅自动格式分离 | 75% | 75% | 5/5 | 0 |
| structured，自动格式分离加显式事实计划 | 100% | 100% | 5/5 | 0 |

最后一行使用调用方提供的意图，不是模型自动理解问题后的成绩。查询/标签没有从这些成绩获得正式审核身份；这些指标也不代表答案正确、拒答行为正确或语义模型质量。

### 原有真实候选

原查询共 50 题，其中 13 题有 candidate 标签、37 题未标注；13 题包含 5 道答案题、1 道澄清题、7 道资料不足题，reviewed 为 0，来源发布日期仍有未知。

| 策略 | 5 道答案题召回率 | 支持节选覆盖率 | 澄清题返回空 | 资料不足题返回空 |
| --- | ---: | ---: | ---: | ---: |
| raw | 0% | 0% | 1/1 | 7/7 |
| structured，仅自动格式分离 | 0% | 0% | 1/1 | 7/7 |

本轮未为原真实候选提供人工量身事实计划。代码经 SPEC、QUALITY 审查后冻结，每个政策回放一次；对照记录包含输入及代码 SHA256，检查运行前后不变。原 corpus、query、label 文件和旧词法词典未修改。

具体诊断：

- 008、023、026、030 的完整自然语言正文没有可安全删除的完整格式后缀，仍产生过多必须匹配的词，词法 fallback 记录为 `too_many_literals`。
- 028 已成功移出中文和引用要求，但实际查询仍包含 `Find original evidence ... capabilities` 等检索指令和泛化词，词法匹配未命中支持来源。
- 所有澄清/不足题返回空，只能说明检索为空；没有生成回答，不能当作澄清或拒答能力通过。

## 真实资料核查

细节与官方链接见：[5 条产品调研证据补核](2026-10-04-product-source-audit.md)。

| 样本 | 补核要点 | 下一步审核事项 |
| --- | --- | --- |
| 008 Pixel | 支持期限起点、上市月份 | 2030 年 10 月是月份推算，精确日未知 |
| 023 Notion | 周期、一般年付差异、席位计费 | 若需金额，补套餐、币种和地区 |
| 026 Figma | 套餐和席位拆分 | 价格周期开关和税费未验证 |
| 028 Figma | Dev Mode 功能和 Full / Dev 席位资格 | 原节选缺少席位条件 |
| 030 Slack | 历史可见、可选留存、付费默认 | 可见范围与保存期限分开审核 |

核查日不是来源发布/更新日；未知日期不填造。没有填写真实 `reviewed_by` / `reviewed_at`，不把 AI 核查转换成人审。补证资料应成为新版本，旧 corpus 保留作回放基线。

## 验证证据

- 最终代码完整隔离后端回归：**2776 passed，1 skipped，152 warnings，61.02s**，退出码 0。跳过项为未配置真实 Postgres 的 RLS smoke；既有 FastAPI `on_event` 弃用警告未在本轮扩大处理。
- Task1 父独立定向验证：114 passed；Task2 初版父独立定向验证：116 passed。随后修正报告生成开销混入检索耗时，新增确定性回归；最终完整回归包含该修复与测试。
- Task1、Task2 均先 RED 后 GREEN，分别经 fresh SPEC 和 QUALITY；Task2 的耗时统计 Minor 已关闭。
- 相对 `b1cb4d2` 的 8 个 Python 文件 Ruff：当前诊断 0，新增诊断 0。
- 对照不使用真实运行数据库或运行报告；环境文件加载关闭，模型凭据不进入评测。真实 Qdrant HTTP、完整联网调研、真实模型和 Ragas 的未验收状态保留。
- 提交前执行密钥模式扫描和 `git diff --check`；推送后核对现有分支的本地与远端 HEAD。

## 复现对照

在仓库根目录，用项目 Python 环境运行；将 `<python>` 替换为实际 Python 路径。命令禁用环境文件加载，评测使用自己创建的临时 SQLite。

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend <python> -m packages.knowledge.product_benchmark --mode tuning-diagnostic --corpus eval/product-research-tuning-corpus.jsonl --queries eval/product-research-intent-tuning-queries.jsonl --labels eval/product-research-intent-tuning-labels.jsonl --intent-policy raw --output /private/tmp/intent-raw.json
```

仅自动格式分离：使用相同命令，改为 `--intent-policy structured`，输出到另一个文件。

加显式事实计划：在 structured 命令中增加 `--intent-plan eval/product-research-intent-tuning-plans.jsonl`。真实候选回放使用原三文件和 `--mode candidate-diagnostic`，不提供意图文件；不要据候选标签调参后报告为正式分数。

## 模型比较与下一步

当前项目虚拟环境缺少 `torch`、`sentence-transformers`、`FlagEmbedding`、`transformers`，默认 Hugging Face 模型缓存不存在。本轮没有安装、下载权重或调用模型。模型下载范围的异步问题尚未收到回复，继续沿用“评测离线、可采集官方资料”的已确认边界。

下一阶段优先顺序：

1. 人工审定以上 5 条候选的结论范围与证据完整性；补证、标签和审核记录发布为新数据版本，继续隔离调参集与评价集。
2. 比较调用方事实计划的完整性，再让 workflow 的规划节点生成有界意图；评测遗漏限制、无关扩展及原问题保持，不能只统计命中数量。
3. 下载范围确认后，在固定审核集上比较真实多语 dense、稀疏加 dense 的融合及融合后精排。现有 BGE-M3 / bge-reranker-v2-m3 适配器只是待验证配置；必须报告实际 provider、模型版本、设备、延迟、内存和检索指标，加载失败应使比较失败，不能以 hash fallback 代替成绩。
4. 召回和证据覆盖达到明确门槛后再生成答案，结合人工检查与 Ragas 验证事实支持、限制和时效。微调、蒸馏和 RL 继续留在真实基线之后。

设计与执行记录：[设计](2026-10-04-retrieval-intent-design.md)、[实施计划](2026-10-04-retrieval-intent-plan.md)。
