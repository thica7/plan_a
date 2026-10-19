# 逐题证据包与结构化澄清实施计划

> For agentic workers: REQUIRED SUB-SKILL: subagent-driven-development。每项任务只由一个实施者改代码，完成后先做规格审查，再做独立质量审查。用户已确认本页的目标、顺序与真实四产品复验，连续执行，不重复请求实施许可。

**Goal:** 统一分析与写作的逐题证据选择，减少 Reflector 把局部未见误当全局缺证；将产品事实与询问用户输入分开，完整绑定每条原子主张，恢复 Bitwarden 的澄清回答。

**Architecture:** 从同一已接受 SNAP、问题与检索配置生成有身份的逐题选择；各阶段按既有预算消费同一选择并记录实际遗漏。Writer 在同次调用中先产逐题计划与独立事实原子，服务器据有限缺项生成非断言澄清；v3 回放核对事实原文、派生询问及实际发表记录，旧 v2 继续可读。

**Tech Stack:** Python、pytest、当前 SQLite canonical / SNAP / Agent 入口；前端仅同步确有变化的 OpenAPI 类型。

## 已确认边界与设计取舍

- 基线：`814c419b77643ff27638c93d31b99cab2b3049ac`，`codex/pastoral-desktop`；复用现有隔离工作区。161 项相关基线测试通过；同一提交上轮全后端 6151 通过、1 跳过。
- 保护 `/tmp/plan_a_v32_previous_artifact_sha.json` 中 1181 份历史资料/评测文件，不改旧报告、参考答案、审核标签及上轮冻结。
- 选择共享逐题入口：它可复用现有检索及凭据。只改 Reflector 提示无法解决未发送；让各阶段读取整个 SNAP 会扩大上下文；写作后新增通用审核调用会增加费用，均不作为本轮主方案。
- 不增加来源、阶段上下文或模型调用上限，不用产品名、题号或答案白名单。Collector 在封存前仍用自己的逐题采集合同，不能读取未来分析包；Planner、Survey 不伪装已消费不存在的 SNAP。
- 实际视图可能因预算不同而不完全相同，统一的是问题、核心原文与条件的选择身份；必须如实记录未送达，不能只记 ID 就算对齐。
- 不因新增结构字段便宣称语义正确。未知、冲突、失效来源、真正缺证及比较要求仍需阻断。

### 独立审查后的必要补正

- 部分已知核心／例外遗漏同样属于逐题上下文缺口，Reflector 保留机器可验证的约束并至少提示 warn；空合格候选逐题记 no_eligible_original，不能标成完整或预算不足。
- 日志保持现有脱敏。用于恢复的有限选择收据只保存不可逆范围／原问题／检索配置摘要、当前快照及事实 ID，摘要绑定消费凭据；展示诊断不再承担原问题凭据。恢复仍需唯一收据及完整视图／producer 重验；无法从脱敏模型输入核实的实际派送保持 unverified。
- 完整原文等价重放限定同一产品、维度。另一产品的相同文字不能填补当前产品未送达的原文；同范围合法等价去重保留。

## 任务一：共享选择及 Reflector 实际输入

**主要文件**：`backend/packages/orchestrator/evidence_context.py`；必要的内部 helper `backend/packages/orchestrator/question_packets.py`；`agents/analysts/logic.py`、`agents/comparator/logic.py`、`agents/reflector/logic.py`、`agents/writer/dimension_writer.py`；仅当完整性重放需要才改 `research/evidence/views.py`。测试新增 `backend/tests/integration/test_question_packet_alignment.py`。

- [x] 先写匿名失败用例，建立 Free/Families 两题及跨域角色、计费缺项两题的已接受 SNAP。实际 Analyst、Comparator、Reflector、Writer 输入都须收到对应核心原文，不能仅断言 prepared view 或 metadata 中有 ID。
- [x] 加入共享异步入口 `_begin_question_evidence_use(record, agent=..., competitor=..., dimension=...)`。复用 `retrieve_question_facts`；包身份绑定 run/workspace/project、SNAP ID/content hash、原问题及实际检索模式/模型版本。无显式问题保留旧行为。
- [x] 每范围先按题保核心与例外，再汇总多产品/维度；保留已有 8 条/14000 bytes 单范围选择限制及每阶段预算。`_begin_evidence_use` 不得用按字典序排列的 producer IDs 覆盖显式问题选择，也不能因此绕过分析产物的完整凭据验证。
- [x] 每次模型输入携带题号、选中事实身份、完整原文与条件以及本次视图的遗漏状态；共享 helper 重放使用当前 SNAP 验证。已有完整原文以共享池引用传递时保持可复原，不重复塞入多份正文。
- [x] 用现有 trace 记录包与实际请求的关联/输入哈希，区分候选、阶段 view、实际模型发送；不能把未验证的其他阶段发送标成成功。
- [x] Reflector 按题核对完整实际证据。局部上下文缺失需标为 `context omitted`，不能写成所有已采资料没有事实；已给明确规则应据规则作条件判断，不要求原文重复用户数字、域名或问句。不得删除未知 finding、放松真实来源/比较门禁或用正则自动肯定产品事实。
- [x] 离线真实入口测试覆盖：不同产品/项目隔离、旧 SNAP/问题变更、被撤回/过期来源、预算不足、同源多条件、无问题路径、多产品真实比较和 producer 依赖；必要例外遗漏仍有硬 gap。

测试行为示例（在匿名现有 fixture 上构造记录，响应 fixture 只作传输，不作语义真值）：

```python
assert free_limit in analyst_actual_input
assert free_limit in reflector_actual_input
assert scoped_role in reflector_actual_input
assert packet_snapshot_id == accepted_snapshot.id
assert missing_original_id not in actually_sent_fact_ids
assert not current_source_is_missing_when_only_context_was_omitted
```

运行并保存 RED / GREEN：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/integration/test_question_packet_alignment.py -q --tb=short
```

完成后保存 `/tmp/plan_a_v32_packet_freeze_v1.json`，停止写入，做 SPEC → fresh QUALITY；有具体问题由同一实施者修复并保留每版冻结。根代理通过审查后再启动任务二。

## 任务二：原子事实、独立澄清及逐题记录

新事实审核用默认省略的 `claim_review_version=3` 标记，以便最终 QA 重放整句支持与原子性检查；旧 v2 不强加新检查。 v3 最终重放同时复用实时入口的功能主张绑定门：操作须有真实操作观察，其余须有合法来源片段，保留已有价格及完整主引用自动绑定合同。v3 逐题路径仅覆盖当前 `research_questions` 支持的 feature；其他维度继续原无题 v2 路径，不宣称新增逐题绑定。结构化询问首版限当前四类输入；日期条件及例外的事实绑定仍保留，未覆盖的真实日期询问如实标未核实，不能把自由问句充作产品事实。

**主要文件**：`agents/writer/dimension_writer.py`、`agents/writer/answer_coverage.py`、`research/evidence/report_claims.py`、`research/evidence/answer_coverage_models.py`、`research/evidence/source_exceptions.py`、`agents/qa/evidence_alignment.py`；必要时同步 `backend/scripts/prepare_agent_readiness.py` 和不足答复状态入口。生成文件 `frontend/openapi.json`、`frontend/src/api/openapi.ts`。测试新增 `backend/tests/unit/test_atomic_question_answers.py`，保留现有 v2 兼容测试。

- [x] 用匿名所有权/移除保留两句、共享/管理两句重现半句绑定仍发表，以及澄清因官网没问句被拒。先运行失败用例，不改旧输入或参考答案制造通过。
- [x] 同一个 Writer 响应含逐题计划及事实原子；服务器按模型明确列出的原子展开，不用中文分号/动词正则猜切自然语言。每原子独立选择当前已发送的完整 span 或 operation，最多发表原有 8 条。未知管理操作没有提取或绑定时不发表，不能改叫非操作绕过门禁。
- [x] 每个已发表原子都审核整句及其所有条件，而不是只核对开头的操作前提。所有权与保留可分开绑定当前两段；不能借父事实别段、未发送原文或模型 `supported` 标签补缺。
- [x] 事实原子与澄清字段分开。只有事实送入引用支持审核；澄清只询问已确认有限字段，不生成产品断言、条件结论或未经提供的输入。用已有 `missing_fields` 保存字段身份，由服务器生成可重放询问文字。
- [x] v3 选择的 `answer` 为完整已发表事实全文加确定性询问；`evidence_spans` 只覆盖事实，不能把问题充作产品证据。新版本需要同步 `ReportAnswerCoverage.binding_version`、`ReportDimensionAudit.answer_binding_version`、解析、保存、最终 QA 和导出；旧 v2 重放严格性不变，未知版本拒绝。
- [x] v3 的必要澄清守卫读取已验证拼接成功的询问字段，不再要求官网原句包含询问；源事实、认证/保留副本/访问路径例外仍只从实际已绑定主张判断。按当前题与已发送规则判断必需缺项；无法可靠缩减时保持保守，不猜未知来源语义。
- [x] `reason` 由实际已发表 IDs、状态及缺项生成有限说明，或以同等严格方式审核；不能自由写入父事实、未发表角色定义或新答案。具体不足答复统一为可辨识的不足状态，不伪称已算精确金额；空稿逐题有真实未核实记录，不能补标 answered。
- [x] 正负例覆盖完整源规则＋澄清、缺一个必要字段、捏造澄清输入、源规则缺失、错角色/操作/引用、半句支持、未发表内容进入 reason、body 改稿、超过容量、v2 旧记录、v3 审核/QA/导出全过程。OpenAPI 有意变化应正确生成并说明，旧 TS 赋值及默认序列化仍兼容。

v3 回放的完整性合同：

```python
assert record.answer == "\n".join([*complete_published_texts, server_clarification])
assert [span.quote for span in record.evidence_spans] == complete_published_texts
assert record.missing_fields == authorized_missing_fields
assert server_clarification.startswith(("请确认", "Please confirm"))
# 逐项篡改字段、原子和答案后，应由实际重放入口拒绝；
# ReportAnswerCoverage.model_validate 对 binding_version=999 也必须拒绝。
```

示例中的 `complete_published_texts` 来自当前审核通过并实际发表的 IDs；`server_clarification` 仅按已验证有限字段生成。实现不可用自由模型文本代替该函数结果。

先保存失败，再定向回归：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_atomic_question_answers.py backend/tests/unit/test_source_span_binding.py backend/tests/unit/test_writer_question_delivery.py backend/tests/unit/test_answer_coverage.py -q --tb=short
```

冻结并做 SPEC → fresh QUALITY，再做累计审查。真实四家反馈可以失败；不得为达到 4/4 放宽事实支持、删掉问题或改审核标签。

### 全量回归补正

- 旧调用可没有 binding_version，按原 legacy 语义读取，不能因新增可选字段崩溃。
- 固定摘录诊断的独立观察槽位由产品／维度／来源 URL／原文身份生成并严格重算；不改参考答案，不放松真实冲突排除。有效输入恢复后按真实 Writer 调用计数，空计划仍为零审核主张、不可交付，不能为保旧零调用断言而跳阶段。

### 累计消费链补正

最终 producer 读回必须重验 Writer 及其真实上游的逐题收据，而非仅比较旧 payload hash。共享无状态校验同时用于消费与最终回放；缺失、重复、篡改及当前问题／配置变化均拒绝，读取不改状态／日志，无包 legacy 保持兼容。Writer 仅从实际发送的最终 compact 记录三类直接上游依赖；新 audit 明确保存空集合或实际边，旧字段缺失保持兼容。相同 payload hash 不代表使用，省略的 advisory 不纳入最终回放；不扩展成传递依赖图。

## 最终验证与交付

- [x] 根代理运行全后端、变更范围 Ruff、API/旧 TS、前端构建、包括新增文件的空白检查；保留四项无关历史 F401。
- [x] 冻结生产代码、实际运行/指标 helper、原始输入及参考数据；新目录 `data/artifacts/agent-question-packets-2026-10-20/`，不覆盖上轮产物。先验防漂移与参考答案不会进入 runtime。
- [x] Bitwarden、1Password、Dropbox、Cloudflare 各顺序跑一次固定官方来源真实阶段流程；每组原上限 24 次调用、80000 token、2048 输出、无重试。模型、工具计费分账；三核心阶段真实执行与回退分开记录。
- [x] fresh 只读内容审读按原人审八题分别核对正文、保存记录、全部额外发表主张、前提归属及实际逐条绑定；合理澄清/具体不足可合格，空稿不可合格。系统 QA 与内容判定分别报告。
- [x] 复核 1181 份旧文件及新冻结前后不变，扫描当前凭据/常见密钥模式、构建和新产物；不输出密钥，不声称已查完整 Git 历史。
- [x] 更新交付文档、README、Agent 实际执行说明和正式验收记录，独立只读交付复核重要项为零。

Git 交付按既有授权提交推送当前分支，核对远端 SHA 与工作区；实际结果记录在本机 verification/git-delivery.json，不合并主分支。

本轮不训练模型、不赋奖励、不下载新权重、不执行 Docker、不改真实 `.env` 或新增基础设施。四家流程不冒充 Planner 发现、全 Graph 或生产稠密 RAG 验收。

## 本轮验证结论

工程验证完成；真实八题正文与记录均为3正确、5遗漏，六条发表观察5条完整绑定，系统0/4可交付。报告交付目标仍未达标，剩余原因与建议见[交付记录](2026-10-20-agent-question-packets.md)，不把计划项完成当作语义验收通过。
