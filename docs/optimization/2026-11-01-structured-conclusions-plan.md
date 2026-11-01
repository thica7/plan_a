# 数量上限与计费缺项的结构化结论实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development。该纵向改动耦合GEN、源审、发表与QA，由一个代码作者顺序完成，规格通过后交独立质量审查。用户已批准设计与实施，不重复请求执行许可。

**Goal:** 为数量上限和计费缺项建立服务器验证、可重放、带内容版本的结论对象，正文、问答及最终QA消费同一发表版本，并以离线与四家真实回归判定实际交付。

**Architecture:** 在已有SELECT后提供有限的服务器关系候选，模型仅选择候选ID，不自由编写这两类产品断言。服务器从真实所选原文及请求引用重建关系，生成最小来源事实供独立源审，并用受限规则推导结果。全部价格／澄清覆盖结束后，统一冻结ConclusionSet到现有atomic receipt；正文和QA只通过重建后的authority消费该集合。

**Tech Stack:** Python、Pydantic、既有源绑定／quantity witness／billing gates、atomic receipt、RunJournal、DeepSeek原生JSON、pytest。复用当前隔离分支和存储，不新增数据库、服务、训练或Docker。

## 基线和已复现断点

- 基线`e45c12a5f6aab1622f01a89c67e505fde1f7afa1`，当前worktree干净，分支`codex/pastoral-desktop`；沿用`../plan_a/.venv/bin/python`，不解析成系统Python。
- 最新四家真实结果3/8原题完整，报告文本／证据／原子各1/4、严格QA0/4。旧结果、raw及冻结源码不改判。
- Cloudflare SELECT原文CPU计量列正确，GEN仍自由复制费率／执行限制或cache条件，引用并未缺失。
- Bitwarden raw有有效No与数量凭证；当前只读重放可返回该推论的观察，存档report_md仍为空，说明生成时序与认证投影未统一。
- `_dimension_question_coverage`在task ANSWER后仍用价格及澄清兜底覆盖coverage。因此必须在最终coverage合并之后冻结发表对象，不能只给task aggregate换名称。
- 两份只读调查位于`data/artifacts/structured-conclusions-2026-11-01/diagnosis-{architecture,billing}.{json,md}`，原件hash保持。

## 边界与内部合同

1. 新内部selector使用`structured-conclusions-v1`；与现有`task_clause_contract=semantic-target-clauses-v2`并存，避免破坏已有语义守卫。只在两个Writer实验开关均开启、且该scope尚未产生Writer派送或receipt时进入新合同。已有记录按其持久化selector恢复；缺selector保持旧行为。两开关默认仍为false。
2. 第一批有限关系为`quantity_upper_bound`和`billing_input_gap`。数量优先使用已有typed request_property、同单位上限及范围见证；不把访问、邀请或描述人数混为同一种上限，不把低于上限推成无条件支持。其他任务继续自身执行路径，作为回归对照，不承诺所有自然语言关系都已结构化。
3. 模型提案只含版本、task_id、选择状态及服务器candidate_ref；不能提交text、verified、判定、伪造引用或任意数字。未知关系／多候选／跨task引用及布尔版本拒绝。输入与源事实使用独立provenance。
4. Source review仍独立核对精确选中原文、完整条件／例外、适用scope及source binding。结构或哈希正确不代表语义正确；uncertain、unsupported、未送审、超窗均不能创建已验证结论。
5. 数量推论由受限规则签发；纯AND可由一个有效超限否定整体，OR／独立多问不适用。计费仅声明有源的计量关系和未确定费用输入，不生成金额、实际超额或完整报价。
6. 计费缺的是足以确定费用的信息。明确CPU总量、同周期同scope的可靠充分界限或已给该费用项，应区别处理；包内上界已定费用时不得仍硬要精确CPU。每次调用限制不是总计量输入。解析不确定时保留未知，不能当零用量或虚构缺项。
7. 身份验证、问题交付与发布审核分别记录。澄清和有依据的缺项可正常交付，同时保持产品事实或精确金额未知；不能据对象存在清掉所有历史finding。

## 文件边界

| 文件 | 职责 |
| --- | --- |
| 新`backend/packages/agents/writer/structured_conclusions.py` | 有界候选／提案／结论模型、字段校验、数量／计费两类有限推导及确定性文本投影 |
| 新`backend/packages/agents/writer/conclusion_publication.py` | 最终ConclusionSet、内容revision、receipt重建authority及正文／问答／QA投影 |
| `selected_task_delivery.py`、必要的`task_clauses.py` | 新鲜selector、两类结构化GEN与真实源审接线；原分支和SYSTEM保持 |
| `task_answer_outcomes.py`、必要的`task_decision_witnesses.py` | 复用已认证数量推导和任务结果；支持新关系对象，不从自由句子猜结构 |
| `question_atomic_delivery.py` | 保存／恢复新selector、模型派送身份、结论集合及其摘要；旧receipt不增空字段 |
| `dimension_writer.py` | 在最终价格／澄清覆盖后冻结集合，先完成真实audit与receipt，再渲染报告 |
| `answer_presentation.py`、`independent_question_review.py`及必要QA context适配 | 共读同revision；保留原文独立审核，基于明确问题scope处理当前与历史状态 |
| 新`backend/tests/unit/test_structured_conclusions.py`、`test_conclusion_publication.py`及必要交付集成测试 | 自包含正负测试，不依赖私有真实运行目录 |

不扩公共端点或枚举；对象保存于已有atomic receipt并由audit现有digest绑定。若实现发现必须改公开DTO，先在私有实施记录说明必要性，优先采用已有receipt承载。

## Task 1：冻结基线与写红测

- [x] 保存本轮独立artifact目录；前轮1096文件和更早1364文件已锁定，不覆盖旧记录。
- [x] 基线现有三份task测试110通过（13.86秒、退出0）；linked worktree已确认，未新建嵌套worktree或重装依赖。
- [x] 新测试先验证提案严格边界。以下接口是测试所需契约，代码作者可用等价命名，但必须统一更新所有调用与计划记录。

```python
def test_model_cannot_mark_a_conclusion_verified():
    raw = {"version": 1, "task_id": "t1", "status": "selected",
           "candidate_ref": "c1", "verified": True}
    with pytest.raises(ValueError):
        parse_relation_proposal(raw, task_id="t1", candidate_refs={"c1"})
```

- [x] 运行红测，确认因缺少行为失败；禁止把import拼写错误当红证据。先定义最小模型／入口后以行为断言复现也可，不先实现验证逻辑。

## Task 2：有限关系候选、源审和受限推导

- [x] 数量候选从本task的真实selected bindings、完整源quote、typed property、唯一父请求及既有上限见证构造。生成源事实句与最终推论是两件事；独立源审验证上限，程序验证数值与任务逻辑。

```python
def test_same_unit_excess_is_derived_after_source_review():
    source = supported_limit(unit="collections", maximum=2, plan="Free")
    request = requested_limit(unit="collections", required=3, plan="Free")
    conclusion = verified_quantity_conclusion(source, request, source_review="supported")
    assert conclusion.result == "no"
    assert conclusion.derivation["rule"] == "same_unit_upper_bound"
    assert conclusion.source_refs and conclusion.request_refs
```

- [x] 反例包括：描述人数非最大值、错单位／套餐、OR、独立多问、未知日期例外、跨snapshot／scope／task、篡改quote或源hash、缺／重复／不确定源审。原有数量／资源合同不被追溯放宽。
- [x] 计费候选只从实际selected CPU计价cell或明确适用计量规则生成，保完整表头／row／notes／scope。复用正CPU时间费率与适用范围gate，不能借Duration、请求列或未选parent补计费断言。

```python
def test_cpu_runtime_limit_is_not_a_billing_meter():
    proposal = billing_relation_from_selected(
        quote="Maximum CPU time per invocation: 30 seconds.",
        request={"plan": "Compute Paid", "usage_model": "Standard"})
    assert proposal is None
```

- [x] 精确总量、零值、可靠包内上界、已给该项费用与未解析界限分别测试；zero／negative／free／not billed、错计价分母、缺header、未知scope不可生成verified CPU gap。1Password缺pricing原文保持缺证。
- [x] 两类GEN只选择服务器候选；服务器文本模板不含另一个关系、费率／运行时清单或完整账单。新source-review输入明确“来源计量／上限关系”与“程序推导”分工，保原真实来源检查。
- [x] 未获源审支持不产生verified对象；模型字段`text/verdict/verified`或额外JSON、多根、重复key、无穷数、bool版本、无效状态拒绝，成功peer不受失败项影响。

## Task 3：冻结一次最终结论集并持久化

- [x] 在`_dimension_question_coverage`最后价格／澄清合并结束后构造ConclusionSet。新两类任务从已验证关系与受限规则生成结果；原price limitation和request-only clarification需作为最终投影依据，不能再次擦掉已获支持的计费关系。
- [x] 集合绑定workspace/project/run、snapshot、consumption、question/task、完整来源和真实review／派送引用。`revision`使用规范内容摘要，与RunJournal每次保存递增的存储revision分离。

```python
def test_conclusion_revision_tracks_meaning_not_journal_writes():
    first = freeze_publication(validated_inputs())
    restored = freeze_publication(validated_inputs(journal_revision=99))
    assert first.revision == restored.revision
    changed = freeze_publication(validated_inputs(required=4))
    assert changed.revision != first.revision
```

- [x] 保存新selector与ConclusionSet到atomic receipt，更新audit digest；已有receipt无新selector时序列化／SYSTEM／replay保持。反序列化数据不能自行成为authority；由真实producer重建source、proposal、source review及推导后签发临时authority。
- [x] 利用现有RunJournal原子detail保存／CAS／fence；外部模型调用放在数据库事务外。save/load及冷replay后内容revision一致；篡改结论、版本、源、任务、review或answer均失效。

## Task 4：正文、问答、最终QA共读同版本

- [x] 在audit/receipt齐备后，正文观察与问题回答从同一authority生成。推论标明题设条件，来源事实和用户条件保持各自来源。已回答容量问题不能同时显示“无已核实观察”而无解释。
- [x] 最终QA上下文带同一集合revision、当前真实正文、原题、完整选中原文和必要限制。support/basis/cache identity覆盖该revision，旧审核不可批准新版本。

```python
def test_report_and_qa_must_reference_the_same_revision():
    publication = frozen_quantity_publication()
    assert render_question(publication).revision == qa_context(publication).revision
    with pytest.raises(ValueError):
        verify_publication(rendered_revision="old", publication=publication)
```

- [x] QA仍可因原文、条件、覆盖缺项或语义争议阻断。只为有明确scope且被本结论完整解决的问题提供解决依据；混合／未绑定历史finding及真正缺证不批量清除。
- [x] 对Bitwarden测试：纯AND已验证单上界否定、合理两项澄清、资料事实未知、正文／观察／QA相同revision。对CF测试：pricing兜底后CPU计量规则及缺项仍同源发表，无runtime、无精确金额。
- [x] 不截完整任务／原文／条件，保原14000 UTF-8 user cap与QA保护额度；仅去掉重复投影和SELECT专属目录，剩余超窗真实记录延期，不伪造派送。

## Task 5：双审、离线与真实验收、文档交付

- [x] 单作者完成红→绿、针对性回归、旧合同SYSTEM／raw／replay负控、Ruff相对Git基线新增0，冻结源码manifest及ZIP后停写。先独立规格APP，再独立质量APP；此前不跑全量或真实模型。
- [x] 自包含集成测试真实走候选→GEN→独立源审→推导→最终价格／澄清合并→同一结论集→正文／QA／冷replay；只mock外部模型response，不能mock业务推导为成功。
- [x] 用已存实际BW与CF snapshot加做明确标注OFFLINE_MOCK的完整接线与运输探针；1P缺价及Trello旧分支回归，不把离线mock算模型质量。原件hash前后保持。
- [x] 最终全后端记录测试前后源码identity；标准API／TS新生成比较，前端未改时核对260文件与先前340测试／build版本，不假称本轮重跑。全量需原生临时PostgreSQL，由root授权执行，无Docker。
- [x] 四家同2026-10-21固定网页、同原8题／22必要分支、同64calls／240000tokens／配置0.25美元、temperature0、retry0、最多2并行。记录实际新结构化GEN／source-review／结论对象数量与revision，不把selector存在或空结论集算功能已验。
- [x] 新独立内容审查逐原题、每条正式主张及自己的所选quote评分：文本／证据／原子／严格QA四口径分开，未完成都保留，未选／未发表内容不补正文。统计真实calls/tokens/unknown、QA planned/sent/valid/unsent/timeout；model alias权重未知，不作严格因果或降本宣传。
- [x] 更新README、Agent说明、专用交付文档、脱敏结果与四份原样报告；新文件不覆盖旧轮。持久化本机演示服务未停止或重启。

发布顺序：独立验收后精确暂存，运行凭据字面／强token与实际blob扫描，再normal commit/push既有`codex/pastoral-desktop`，不PR／main合并／强推；实际提交与远端验证在发布动作完成后汇报。

## 本机验证命令

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=backend:backend/tests:backend/tests/unit:backend/tests/integration \
../plan_a/.venv/bin/python -m pytest \
  backend/tests/unit/test_structured_conclusions.py \
  backend/tests/unit/test_conclusion_publication.py -q --tb=short
```

真实batch不设置`COMPETISCOPE_LOAD_ENV_FILES=0`，凭据只由现有私有配置加载且从不输出。四家回放不是新抓取、盲测、一次四品横向比较、全Graph、生产语义RAG或数据库端到端验收；报告是否达标以新独立正文结果为准。

## 实际验收结论

最终candidate4先经规格与质量APP后运行全量和真实复验：后端9628通过／1跳过；真实117调用／450696已知token；两类各1条非空结论和同revision正文／问答／QA已验证。独立内容3/8原题完整、12/22分支，文本／证据／原子报告1/4、严格QA0/4，不能宣称整报达标。四个候选与全部失败记录保留，见[交付](2026-11-01-structured-conclusions-delivery.md)与[结果](2026-11-01-structured-conclusions-results.json)。
