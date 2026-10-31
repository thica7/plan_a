# 任务语义选证、具体重写反馈与状态一致性实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development。单一生产作者，规格通过后再交独立质量审核；禁止多个作者同时修改Writer。用户已确认本轮方向，执行中不重复请求继续许可。

**Goal:** 修复已采原句没有正确进入对应任务结论的问题，并以四家真实模型回放及逐条独立内容审核判断交付质量。

**Architecture:** 在现有SELECT→单任务GEN→逐子句REVIEW→ANSWER→最终QA中增加新鲜执行专用的语义子合同。将任务目标、证据适用范围与表述错误分开；证据语义不符必须重选，只有表述错误才复用原SELECT。正文与QA读取同一实际审核结论，未审核事实和真正缺口继续保留。

**Tech Stack:** Python、现有Writer/QA、DeepSeek原生JSON、pytest、既有固定网页回放工具。不新增服务、Docker、训练、生产默认开关或全局模型预算。

## 已核实的根因

基线`c23874807feff5092c211eea17848dc210fda276`，工作树干净，复用现有`codex/pastoral-desktop`隔离worktree。

- 1Password：SELECT span44收到完整已接受／确认背景，候选s37/s44含current access，却选s42 invited；补交继续复用错误原句。span58称supported，但把第二谓词标connector，真实协议正确拒绝。不能放宽审核去接受邀请→持续访问。
- 来源标题明确Families范围，却在选证投影中丢失；标题只能限制来源适用范围，不能成为新增产品事实或可选引用。
- CPU：原表格同一cell同时有收费额度／费率和runtime限制；两稿均复写整个cell。错误被提前合并成`task_selected_target_mismatch`，反馈缺具体应移除的谓词。
- Trello：`rule_vote`辅助任务被重复计入A/B答复分母；另一稿把定义、Workspace否定、逐板设置和跨板推论合写，REVIEW把独立产品规则标为premise后放行，claim只归属跨板任务。
- Bitwarden：澄清跳过生成后，回放未创建该qid的`facts_by_question`，逐题核验KeyError被变成未验证。最终QA还把已认证纯AND单上界反例误解为需要再证明另一上界和题设年份。

诊断原件在`data/artifacts/writer-semantic-delivery-2026-10-31/diagnosis-{1password,status}.{json,md}`。旧三轮725件已锁，不改原报告、raw或参考答案。

## Task 1：语义子合同与选证

**Files:** 新建`backend/packages/agents/writer/task_semantics.py`；修改`task_clauses.py`、`selected_task_delivery.py`、必要的`task_support_selection.py`和`dimension_writer.py`接线。测试新建`backend/tests/unit/test_task_semantics.py`。

- [ ] 先运行现有三份task测试作为基线；用自包含Example产品fixture写红测。

```python
target = semantic_target(task, bound_request_context)
assert target["lifecycle"] == "current_access"
assert not support_matches(target, "A guest can only be invited to a single vault.")
assert support_matches(target, "A guest only has access to a single vault.")
```

- [ ] 使用独立内部合同值，例如`semantic-target-clauses-v2`；没有新标记的v1/v2/v3、旧单谓词v1、旧SYSTEM和raw保持各自身份。新鲜Writer选新合同，恢复任务保留已持久化合同；公开API与两个默认关闭的实验开关不变。
- [ ] 语义目标由当前任务及其唯一已绑定完整请求构建：精确子问、focus、共享题设及明确状态。生命周期区别只在明确已接受／确认、且当前任务询问持续访问／容量时使用；邀请任务不被误当持续访问。不按产品品牌列答案或白名单。
- [ ] 选证显式列出语义适用的候选与不适用原因；服务端再次验证，不能仅信模型选择。原quote、条件、例外、角色、套餐、源身份不裁切。来源title/url作为限制性scope传入，不给它可选支持ref。
- [ ] 收费性质任务须区分实际billable/non-billable规则与纯导航。原Trello SELECT span96选s21跳转句，但同窗s5/s19已有完整分类原句；拒绝用纯导航证明规则，不误拒同段含规则和导航的完整证据。不编写品牌答案。
- [ ] 证据语义不足进入一次原SELECT重选；重选仍有同run/snapshot/task绑定和完整原始失败链。语义适用且仅写作错误，保留原认证SELECT复用。成功peer不覆盖，预算不增加。

## Task 2：具体的生成与重写反馈

**Files:** `task_semantics.py`、`task_clauses.py`、`selected_task_delivery.py`；测试`test_task_semantics.py`及现有`test_task_target_delivery.py`／`test_task_dispatch_delivery.py`。

- [ ] 写红测：CPU含runtime得到具体`sibling`原因；邀请证据不能通过“缩短句子”变成当前访问证据；正确CPU依赖与共享AND条件继续通过。

```python
feedback = rewrite_feedback(task, reason_codes, failed_clauses)
assert feedback["strategy"] == "rewrite"  # 或 reselect，来自实际失败类型
assert "runtime" in feedback["instruction"].lower()
assert "invitation" in reselection_feedback["instruction"].lower()
```

- [ ] 将目标指令聚焦到单一关系：CPU账单缺输入任务只写该计费依赖，不抄数值／runtime清单；当前访问容量不附Private规则；Workspace可否统一设置与跨板传播分别写、分别审核。保留完整限制上下文，不把题设变成事实。
- [ ] 反馈包含有界的人可读修复指令、具体失败谓词／子句定位、实际原因码和原span/hash；诊断不成为证据。优先保留具体`sibling`原因，不用泛化target mismatch吞掉根因。
- [ ] 子句诊断也必须有总UTF-8边界；保留少量必要摘录、完整原文位置/hash，原全文留在trace。不能只删raw块却把全文复制到另一必留字段。按target给重选原因，非邀请问题不套用邀请说明。
- [ ] CPU结论校验用账单依赖关系，而不是将源文费率信号分类器当生成结论分类器。两种中文语序“账单还需要CPU用量输入”“CPU用量是账单必要输入”须能进入原独立源审；请求价格／运行时／费率清单及无证否定仍拒。必要版本／套餐限定中的数字不能一概误当费率。
- [ ] 可选raw诊断的入窗压缩沿用上一轮机制；新增短指导不允许挤掉完整证据或静默跳过。实际UTF-8 cap、保护额度、一次补交上限和本地延期证明仍须通过原rebuild/replay。
- [ ] 新合同审核不得将独立产品定义／设置规则伪装成premise。真正的共享条件与例外继续作为condition/exception保留；将未问的背景产品规则从本任务稿移除，不借它去填另一个任务。不能再扩大词形黑名单来假装完成一般语义证明。

## Task 3：正文、回答和最终QA的一致性

**Files:** `selected_task_delivery.py`、`task_answer_outcomes.py`、`answer_presentation.py`（仅必要投影）；`backend/packages/agents/qa/question_context.py`／`independent_question_review.py`必要接线。自包含测试新建`backend/tests/unit/test_semantic_delivery_status.py`，复用现有clarification/quantity QA夹具。

- [ ] 对全部canonical qid初始化显式空originals，修复澄清跳过生成导致的KeyError。仍走`reconcile_packet_originals`；仅已认证request-only允许CORE缺口，EXCEPTION、未知来源和正文变动继续拒绝。

```python
assert clarification_qid in replay["facts_by_question"]
assert replay["facts_by_question"][clarification_qid] == []
assert question_delivery_complete(..., request_only=True)
```

- [ ] 辅助规则依赖与用户待答任务显式分开。辅助规则仍需审核，并保留真实未审依赖；不把它作为重复用户分支。不要仅按`focus`前缀全局豁免。
- [ ] 拒绝复合claim后，Workspace否定与跨板结果分别使用自己的主张和引用；禁止跨任务借用一条未按目标审核的claim来强改unknown为answered。
- [ ] 最终QA接收同一认证任务结论、实际发表文本及纯AND反例语义。单同单位上界足以否定纯AND请求；OR、独立多问、未知日期例外和条件未覆盖必须继续阻断。场景背景年份不是额外待答任务。
- [ ] 澄清交付与产品事实未知分别记录，不能因澄清通过清掉所有历史finding；只有被当前实际发表结论完整处理的相应finding才能被替换。观察区与问答区共用发布资格，避免“暂无观察”掩盖已发表有效推论。

## Task 4：独立验收、四家真实流程、交付

**Artifacts:** 本轮全部新文件只写`data/artifacts/writer-semantic-delivery-2026-10-31`。**Docs:** 新交付记录/结果和四份原样报告，README与Agent执行说明更新，旧三轮不改。

- [ ] 单一作者完成红→绿、针对性回归、实际源码归档和Ruff新增0；规格审查通过后再独立质量审查。两者通过后再启动全量和真实模型，避免对未审版本反复跑全量。
- [ ] 最终全后端记录测试前后源码身份；标准工具临时导出API/TS比较。前端未改时核260文件与已有340测试／构建版本一致。
- [ ] 四家先离线preflight，模型0；随后同固定2026-10-21网页、同64calls／240000tokens／0.25美元配置上限、温度0、重试0、最多2并行跑真实七生产阶段。生产默认不变。明确不是新抓取、盲测、全Graph、生产RAG或数据库E2E。
- [ ] 同8题22分支独立看最终正文与逐条实际quote，分别统计正文／证据／原子／严格QA。新出现的无证断言也计分，不借未选或未发数据。保留所有失败，不筛选最好一轮。
- [ ] 公开报告逐字节复制；记录实际模型调用、token已知/未知、GEN/REVIEW、QA已送/未送/超时、语义重选、真实补交和本地延期。是否达标由实际内容决定，不由单测数或supported标签代替。
- [ ] 按此前授权精确提交并正常push既有`codex/pastoral-desktop`；暂存literal凭据／强token扫描、源码blob与已审冻结匹配，不提交.env、数据库、权重或私有原始运行目录。不得PR／main合并／强推。

## 验证命令

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=backend:backend/tests:backend/tests/unit:backend/tests/integration \
../plan_a/.venv/bin/python -m pytest \
  backend/tests/unit/test_task_semantics.py \
  backend/tests/unit/test_semantic_delivery_status.py -q --tb=short
```

第一轮必须因尚未具备这些行为而失败。提交的测试不依赖被忽略的真实运行产物；私有原件仅作额外只读复现实证。

## 首轮真实验收后的必要修复

首轮已冻结、双审、9508后端测试通过，真实112次传输／416918已知token；独立正文验收仍为1/8原题完整、四口径均0/4。首轮[结果](2026-10-31-semantic-initial-results.json)和四份原样报告保留，不覆盖或改判。源码`1b16775…`的完整审计完成后才允许继续修改。

下一候选只处理首轮实际暴露的同一任务范围，不新增架构或放宽验收：

1. CPU指令从“额度／费率＋仅依赖”冲突改为单一已选账单依赖目标；完整原题、原句、套餐／模式限制及旧合同保持。
2. 对真实REVIEW定位失败子句／作用／目标不符，给出具体重写说明，保span/hash和UTF-8总界，不能默认只摘首句。
3. 合理同单位上限推论不能被“非题设premise一律拒绝”误阻；优先复用既有typed quantity witness签发必要来源前提资格。独立产品规则、OR、未知条件／例外、描述人数和跨单位推论仍拒绝。
4. 检查Trello实际中文条件句是否被有限条件语法误拒；如属实只补常见条件范围及闭合控制，不把闭合后的第二操作纳入前提。
5. 1Password两次选到明确inapplicable邀请ref，服务端拒绝是正确行为。调整真正可选catalog与限制性上下文的区分，使已判不适用的ref不再作为正向可选证据；原文、约束和身份保留，不能把neutral候选当成已获支持。

先保存最小计划和私有红测探针，再单作者实施、规格→质量审查、最终全量、四家同资料同预算真实复验及新的独立正文审计。使用新目录`data/artifacts/writer-semantic-followup-2026-10-31`和新的原样结果文件，保留本轮所有失败。
