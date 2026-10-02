# 脱敏 Agent 评测数据基础

`split_examples.json` 全部为手写合成数据，带 `synthetic=true`、`fixture_only=true`、
`execution_mode=synthetic`。它展示三个 split 和同一任务的重跑；不导入在线任务，不代表真实训练准确率。
本阶段不训练 RL，也不提供人工 truth label 入口；所有 `reward.correctness` 和 `reward.source` 都是 `null`。
QA、流程完成、人工接受/审批及 system feedback 不会转换为事实正确性奖励。

在项目根目录运行以下命令，替换为**已存在**的 SQLite 路径和准确 workspace ID：

```sh
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python \
  backend/scripts/export_agent_eval.py \
  --journal runs/run_journal.db --workspace ws-a \
  --feedback-db runs/preference_memory.db --output /tmp/agent_eval.json
```

`--feedback-db` 可省略。脚本通过 SQLite `mode=ro` 读取源库，不调用 store 初始化或迁移。
输出路径不能覆盖任一源库的主文件、-wal/-shm/-journal，也不能通过 symlink/hardlink 别名覆盖它们。
不存在的库、损坏 SQLite、缺少表/字段及非法 JSON 会以固定错误说明失败，不创建空库或回显原始异常。
只纳入原始 JSON 明确 `execution_mode=real` 的 run，并校验 JSON 的 id/workspace/project 与数据库列一致；
Demo、模拟和 fixture 标记会过滤，包括实际 survey producer 的 `source_type=survey_simulated`，
以及 source_type/source_role/community_source_type 中明确的模拟来源标记。
真实导入的 survey_response、community_forum 和正常工具调用会保留。
反馈必须显式关联导出 run，且 workspace/project 完全匹配。
`journal_explicit_real` 仅描述存储中的显式模式，不能证明已完成联网验收。

导出只保留 task scope、动作属性、输入/输出摘要、用量及关联反馈摘要。
摘要优先从存在的 full_input/full_output 完整脱敏后截断至 600 字，避免旧 producer 先截断 preview
导致密钥残片不能识别。完整文本只用于生成有界摘要，不导出 full_input/full_output 字段或原始完整载荷。
只有 preview 时，若末尾有省略号、原始字符计数显示已截断，或脱敏后仍有疑似密钥/邮箱残片，
则对应摘要置 `null`；summary_omitted_reason 明确标为 truncated_preview/unsafe_preview。
可用摘要的 summary_source 标明 full_text/preview；没有文本时标 missing_text，不声称旧 preview 一定安全。
所有其他外部字符串也先完整脱敏，再截断至 600 字；不输出整篇 report、user_id 或任意 metadata。
脱敏覆盖中文直接相邻的已知密钥、邮箱和电话；明确 credential assignment 的完整值在 URL 解码前处理，
并识别 quoted 值中的 escaped quote，避免编码分隔符或转义引号造成凭据后缀残留。
编码字段名、等号及重复编码会按原始参数边界识别，凭据值中的编码分隔符不会变成新参数边界。
原始未编码的 `&` 划定 query 参数边界；包含敏感 assignment 的 component 可连 URL 前缀一起省略，
其内部空白和其他 query 值字符不拆分参数，`&` 后的公开参数保留。
每个 run 最多 100 个动作、50 条反馈；scope 每个列表最多 20 项，并给出相应省略计数。
未知失败和取消动作不因缺少 usage 被过滤；超过动作上限的内容仍受同一省略规则约束。

用量与成本字段含义：

- `provider_usage`：数值 allowlist 中的 prompt/completion/total/cache hit/cache miss tokens。
  它只代表最后一次 attempt；缺 usage 或来源为 estimate 时各项为 `null`，`usage_source=estimate`。
- `token_estimates`：原始 input/output_tokens_estimate 字段，不补入 provider usage。
- `budget_charge`：span 的 llm_tokens_charged/llm_cost_charged_usd，包含重试和未知请求的保守预算扣费。
- `budget_checkpoint`：run 持久化的 calls/repairs/tokens_charged/cost_charged_usd，包含尚未结算的预留。
  它与 span budget_charge 独立展示，不能相加，也不累计出推断的账户账单。
- `cost_estimate_usd`、`price_basis`：原始价格估算及配置来源；官方价格估算不等于账户实际账单。

`sha256_task_group_v1` 的固定比例是 train/validation/holdout = 70/15/15。
任务身份由 workspace、完整 topic、target_product.name 和 decision_brief 的三个字段构成；
脱敏后归一空白及大小写，保留数字版本。哈希不含 run ID、时间、深度、发现的候选或 dimensions。
没有 target 时使用 topic 和人工 decision_brief；缺少更具体身份的通用 topic 会保守归入同组。
同组所有重跑保持同 split，小样例的占比不代表整体数据比例。

可复现本地验证（只用临时 SQLite 合成记录，不发网络或模型请求）：

```sh
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest \
  backend/tests/unit/test_agent_eval_export.py -q
```
