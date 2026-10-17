# 引用、金额与 Agentic RL 数据准备交付

日期：2026-10-18。实施范围来自用户“先修引用绑定和金额分类，再整理成功、失败、合理拒答轨迹，建立独立评测集；暂时不训练”的授权。

## 已实施

### 回答与引用绑定

新 live 回答采用 v2 选择合同：模型只选本次已审核发表的主张 ID；服务器按原顺序投影完整正文和每条主张的完整片段。未知或重复 ID、缺条件、容量超限均保留未核实，不过滤错误 ID 后冒充成功。新入口拒绝旧模型 envelope，历史存量只保留兼容读取。

内外层绑定版本进入审计与产物依赖。最终 QA 重放完整主张、回答和引用顺序；只剥离内层标记不能降级为旧规则。它不是通用自然语言语义证明，原始主张审核与来源资格仍必须通过。

### 金额分类

新增逐金额 `credit_allowance / purchase_price / unknown`。额度须由本段引用且被当前生成视图放行的原文，完整匹配金额、币种、套餐、周期、授予动作及 credit 单位。逗号／分号后的“仅限新用户”、试用期和首 N 月条件不能被切掉；不能完整证明时 unknown。

额度不进入采购现价结构，不替代企业报价，也不会因为同一文档出现 credits 就豁免其他金额。Writer 主张审核与最终 QA 复用该规则；真实采购价的市场、币种、税费等条件继续单独核对。

### 脱敏轨迹和独立候选

新增 `backend/scripts/prepare_agent_readiness.py`：只读 run、trace、summary、manifest、snapshot 和 report，校验作用域、哈希、报告一致性及实际 usage 类型，再导出单题 episode 和共享运行轨迹。模型动作与 token 每个 run 只计一次。已曝光产品／文档完整身份参与隔离，不依赖被截断的题文，也不遗漏没有回答审计的运行。

脱敏摘要有明确截断标记，不是无损训练语料。标签维持 candidate；QA、任务 completed 和代理评价都不会生成正确性奖励。当前所有 `reward.correctness=null`、`training_ready=false`；没有训练、参数更新、权重下载或 Docker 执行。

新独立构造候选：Bitwarden、1Password、Dropbox、Cloudflare，共 8 题、9 个选用官方文档；两题明确回答、两题条件回答、两题需澄清、两题合理拒答。实现冻结前没有把新参考交给实现代理；冻结后 root 查看审核单。独立构造不等于未曝光盲测。runtime 仅含问题与来源身份，参考边界和标签留在评测侧。

结构化结果见 [冻结记录](2026-10-18-agent-readiness-results.json)。

人审入口：[8 题与 T1–T3 审核单](2026-10-18-agent-readiness-human-review.md)。当前尚未收到该批确认，不能计为正式人审或正式验收；用户确认的是参考边界／标签，不是自动接受新报告。

## 验证结果

匿名 RED→GREEN 与独立规格、质量审查已执行：

- 回答选择专项 37 项；相邻回归 182 项。
- 金额专项 43 项；相邻回归 291 项，另独立审查复现并关闭条件尾句遗漏。
- 导出专项最终 29 项：含工作区、真实／合成、只读、秘密脱敏、截断、成本共享、运行身份别名、全量产品／文档隔离及候选不提升。
- 独立规格相关合跑 401 项；随后新增运行身份别名修复由独立质量审查复验 29 项。
- 前端 279 项、55 个测试文件通过，生产构建通过；OpenAPI 及生成类型同步。

最终完整后端：**5043 passed、1 skipped、212 warnings**，241.13 秒。首轮唯一失败是旧集成 transport fixture 仍返回 legacy envelope；同步 v2 fixture、保留原语义断言后相关 67 项与最终全量通过。源码冻结后未再修改生产代码。最终实际凭据字面扫描覆盖 1339 个文本／构建／本轮 artifact 文件，无命中；未发现受跟踪的真实秘密配置文件。该扫描不覆盖 Git 历史或所有外部存储。OpenAPI 重新导出字节一致；变更 Python 的 Ruff E9/F 与 diff check 通过。不能把专项数量相加当作全量测试数量。

生产源码 SHA256：`fd980a62d853f84663924cd87662cc9a4909d613304a998c3d449dc8137abc1f`。最终真实阶段诊断与秘密扫描结果另见下方冻结记录。

## 两组冻结真实阶段诊断

同一生产源码、固定旧人审题各运行一次：

| 组别 | 来源 | 实际调用 | provider token | 正文字符 | QA blocker |
| --- | --- | --- | --- | --- | --- |
| GitBook | 3 | 10 | 37380 | 1988 | 1 |
| Miro | 1 | 8 | 27712 | 720 | 1 |

合计 **18 次／65092 token**，usage 未知 0，不含旧运行成本；没有调用外部 embedding 或搜索。两组 Analyst、Comparator、Reflector 都实际执行模型并产生结构产物，Writer 和主张／回答审核也实际执行。没有 Planner 自动发现或完整 Graph 调度；canonical 使用 sparse，Writer 问题选证使用已有本机 E5、没有精排。原生价格账单未取得，token 统计不等于供应商账单。

GitBook 的 Chat 回答与已发表完整主张按 v2 正确绑定，当前报告没有金额 blocker；赠送 $20／$100 credits 段仍保留。Auth 访问规则已进入正文，但选择回答仅被 `answer_body_unresolved` 拒绝，中文“只有…才能…”未被闭合问句断言词表识别，尚未核实不能算已回答。精确中国含税报价维持服务器不足答复。

Miro 两问均未回答；生成视图没有完整保留权限问题的操作证据，Guest 页也未取得合格当前正文。报告还省略密码保护的套餐前提，说明结构绑定一致仍不等于原始条件完整。两组各 1 个发布 blocker，**0/2 完整报告达到交付标准**；没有把当前 5 个单题自动标为成功。

独立只读审查的正文判定为 **2 正确／1 局部／2 遗漏**；严格按“问题回答情况”栏目则为 **2 正确／3 遗漏**，Auth 规则在正文不能冒充已展示逐题答案。另有 1 条已发表密码保护主张遗漏条件。审查 SHA256：`0b1567f31c0fd8fd7d8c1b7112188c3438928e3da8e4c2def734ade63ffaeddf`。这是已曝光旧题的诊断，代理审查不能替代用户验收或盲测准确率。新 8 题未运行模型。

## 轨迹与复验

旧四次运行共 11 个单题、136205 已知 provider token（不是本轮新增调用）。T1 为 Basecamp 条件回答成功候选，T2 为 GitBook 排他套餐误判失败候选，T3 为 GitBook 缺精确报价的合理拒答候选；其余 8 题 unlabelled。合并本轮两组后，最终 `development-trajectories-v3` 为 6 次运行、16 个单题，13 个 unlabelled、三类各 1 个候选；已知历史＋本轮 provider token 共 201297，每个 run 仅计一次。它们均是单题标签，该三份报告整体并未因此交付通过。

原报告保持不变。忽略目录 `data/artifacts/agent-readiness-2026-10-18/` 保存官方来源抓取、runtime、哈希、诊断和导出；完整 HTML、数据库、模型权重和本机凭据不提交 Git。可用以下命令重建新的诊断目录：

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/prepare_agent_readiness.py \
  --artifacts <已保存真实运行目录1> <目录2> \
  --workspace <相同工作区> \
  --annotations eval/agent-readiness-trajectory-review-v1-candidate.json \
  --holdout-candidates eval/agent-readiness-holdout-v1-candidate.jsonl \
  --output <尚不存在的导出目录>
```

候选标签绑定具体 run／question／product／报告 SHA；换报告不能沿用。缺少输入产物或不属于同一工作区会拒绝，不会迁移源数据库或调用模型。

## 当前问题与下一步

1. Miro 的完整源和快照已有 comment/edit 操作事实，但问题检索 top 3 没选中；后续需在现有每问 3 条、总 8 条容量内保留遗漏操作对应的结构事实，并保留登录等非操作证据。本轮未扩大检索范围或加入产品特判。
2. 补中文“只有…才能…”等必要条件断言识别，同时核对原始主张是否真的包含问题所需前提。修复密码保护等短条目丢掉上文套餐条件的问题，不能只凭原句局部匹配放行。
3. 外部网站挑战／403 继续可能造成真实缺证；不能绕过来源准入或把旧报告当成当前一手资料。
4. 新题先经用户审核，再登记精确官方文档身份、冻结 runtime／源码并运行独立答案评测；参考答案不能回流 Agent。重点量化条件归属、逐条引用、答案覆盖、合理拒答和成本，不能只看 QA 绿灯。
5. 轨迹目前用于审计与评测。训练前还需更大规模的独立标注、可重放工具环境和经过验证的奖励；本阶段不需要准备 GPU。

固定官方 URL 的诊断仅覆盖 Collector→Analyst→Comparator→Reflector→Writer→QA 的实际阶段，不代表 Planner 自动发现、完整 Graph、生产稠密索引或多实例部署已验收。HTTP Qdrant、Redis、Temporal、实机 Postgres 的部署边界保持原记录。
