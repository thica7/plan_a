# 单谓词生成、逐子句审核和失败补交实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development；唯一生产作者，规格审查通过后再做独立质量审查。按下列任务逐项红→绿。

**Goal:** 让每个已获证据的子任务只生成自己的结论，并让最终正文保留有效结论；本轮重点是Trello、1Password和Cloudflare CPU计费。

**Architecture:** 保留SELECT→GEN→REVIEW→独立ANSWER→正文／QA。给新执行增加内部 `task_clause_contract=single-predicate-clauses-v1`，旧记录缺标记时保持当前合同和真实SYSTEM。新合同缩小GEN输出、显式列出实质子句、修复ANSWER可选引用入口，失败项最多一次补交且复用已认证的有效SELECT。既有证据准入、完整前提、任务身份、预算、精确引用和独立审核继续执行。

**Tech Stack:** Python、现有RunService、DeepSeek原生JSON、pytest；不加模型/基础设施依赖，不执行Docker或训练。

## 已核证据与方案选择

基线7c228f38474ded5ec1031cbf04e73a78c61e7e57；最新真实8题3通过／3部分／2失败，22分支11完整，文本与证据报告仅Bitwarden通过，严格系统QA0/4。

- Trello A/B各自GEN和REVIEW成功，ANSWER span102/110把reviewed-quote与reviewed-claim混入support_refs，均被拒。仅保留合法claim refs的离线对照能接收相同结论；不能据此静默修改旧响应。
- 1Password6次SELECT、4次GEN、0次REVIEW，四稿都把单库上限与Private归属合写；CF CPU两次正确选择完整计费行，却把runtime上限加入GEN。
- predicate子原因在parse_generation中丢失，repair只看到task_predicate_mismatch；generation_outcome又合并为task_generation_invalid。
- Trello合法管理员稿带题设看板A，旧authority词形守卫误判成无operation binding；不能为排版丢失的标签扩大真实改权资格。

仅增加prompt难以解决上述合同与身份问题；大范围建立新推理框架超出本轮。选择有界的生成／子句子合同与局部补交，复用当前来源和状态聚合。

## Task 1：新执行合同和单任务GEN

**Files:** Create `backend/packages/agents/writer/task_clauses.py`；Modify `selected_task_delivery.py`、`question_atomic_delivery.py`、`dimension_writer.py`；Test `backend/tests/unit/test_task_clauses.py`及实际Writer集成fixture。

- [ ] 先建立独立红测试：一任务只能回应自己ID，一稿混Private/单库或CPU/runtime应拒，正确单谓词应进入原审核链。

```python
with pytest.raises(ValueError):
    normalize_generation(raw_for_other_task, payload)
assert normalize_generation(valid_single_task_raw, payload)["question_plans"][0]["question_id"] == server_qid
```

- [ ] 新GEN响应仅接受下面完整根对象；规范化回现有内部计划时qid来自服务器，不接受模型父题状态、自由计划或多atom。raw原文保留。

```json
{"version":1,"task_id":"server-id","status":"generated","atom":{"text":"one complete requested predicate","kind":"fact","support_refs":["s1"]}}
```

- [ ] GEN输入优先展示当前任务精确请求、task_instruction、所选完整quote和完整条件；parent/upstream只作限制，未选片段不能增加断言。避免让整段能力列表成为输出目标。不通过缩短或删掉条件来获得单谓词。
- [ ] 新子合同标记进入实际SYSTEM／payload／receipt／重放；旧v1/v2/v3、无该标记的成功/失败继续按原合同，伪造新标记或混用raw须拒。

## Task 2：服务器子句清单与逐项独立审核

**Files:** `task_clauses.py`、`selected_task_delivery.py`；必要接线 `task_answer_outcomes.py`。Tests：`test_task_clauses.py`。

- [ ] 先红测试：同一稿含清缓存和读取设置，即使模型顶层报predicate_count=1，也不能用一个整句审核吞掉第二实质子句。
- [ ] 服务器按有界标点／连接词生成有序完整子句片段，每项包含稳定clause_id、start/end、quote，拼接必须等于原文。条件、例外、同动作AND前提继续保留，点号不得拆坏域名和小数。最多16片段，超限拒绝，不截断。

```python
assert "".join(c["quote"] for c in clauses(text)) == text
assert all(text[c["start"]:c["end"]] == c["quote"] for c in clauses(text))
```

- [ ] REVIEW须逐项回传clause_id、作用(assertion/condition/premise/exception/connector)、是否独立谓词、task_match、支持判决和合法支持；不接受重复／缺项／整句替代多个片段。只有一个实质目标断言，其余完整前提与例外经审核才可发表。整体来源审核与操作守卫仍需通过，不能让模型自报count证明一般语义正确。
- [ ] 合法的管理员规则若含请求已给资源标签，仅可在标签、角色、原文与任务全部绑定且独立子句审核通过时判资格；未知角色/资源、真实share/manage_access与额外授权继续要求原operation。不可全局改松正则、盲删资源名或重写旧主张。

## Task 3：失败诊断、认证选证复用和ANSWER引用

**Files:** `selected_task_delivery.py`、`task_clauses.py`、`task_answer_outcomes.py`；必要 `task_decision_witnesses.py`／预算接线。Tests：新合同的真实派送与replay。

- [ ] 先红测试：CF CPU夹带runtime必须在反馈中保留task_contains_sibling_predicate；成功peer不重做；有效SELECT复用后只补GEN＋REVIEW，不伪造新SELECT span。
- [ ] 新合同中保留具体拒绝码、对应失败稿/子句和当前task目标的有界反馈。诊断不进入证据白名单，旧合同保持原反馈序列化。
- [ ] 引用复用绑定同run/snapshot/consumption/task与真实成功SELECT及完整原句；跨任务、篡改、失败SELECT不能复用。GEN／REVIEW失败可补一次，源不足则按原SELECT路径；预算预检按实际需派送阶段与完整ANSWER/QA计算，不能提高持久化额度。
- [ ] 新ANSWER wire只呈现唯一可选claim ref与内联quote，移除混淆性的可选quote alias；支持元数据和数量凭证的完整原文不丢。修复反馈明确本task合法refs，不接受跨task或旧wrong refs，也不偷偷清洗旧raw。
- [ ] 两阶段失败补交与ANSWER坏行补交各有一次上限，成功peer保存。实际trace、缓存身份、receipt、replay必须重建原始失败和复用链；正文与QA仍基于同一认证结果。

## Task 4：验收、交付和提交

**Artifacts:** `data/artifacts/writer-clause-delivery-2026-10-31`；旧1364件锁定不变。**Docs:** 本计划、新交付记录/结果、原样四报告、README和Agent执行说明。

- [ ] 命令：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_task_clauses.py -q --tb=short`。先红后绿，再旧合同与预算回归。
- [ ] 独立规格→质量审查；冻结完整源码和评测脚本、Ruff新增为0、全后端、标准API类型及前端相同文件hash或必要回归。
- [ ] 四产品离线预检先全通过且模型0，再以64calls／240k、温度0、重试0、单run0.25美元上限运行固定页面的七生产阶段真实回放。生产默认预算及实验开关不改。不称新抓取/全Graph/独立盲测。
- [ ] 按相同8题22分支，独立读最终正文与各自精确quote，分别报告文本／证据／原子／严格QA；统计实际stage调用、已知/未知tokens、未送审、超时和复用次数，不拿supported或JSON合法代替完成。保留失败与回退，不临时改变评分标准。
- [ ] 所有公开报告逐字节复制；精确暂存、真实凭据literal与强token扫描后正常commit/push原codex/pastoral-desktop分支，保留工作树。没有PR、强推或main合并任务。

## 首轮验收后追加的定向修复

首轮真实结果按严格逐条绑定为2/8原题通过、6部分；完整结果和原样报告独立保留，不随后续复验修改。原源码、输入、审核单及266件首轮文件另锁定。

已证实的新合同传递缺陷：SELECT后当前任务仍带规划候选refs，且CPU计费目标仅留在旁栏，REVIEW未收到。定向修复只在新合同将实际所选refs与结构化目标一致传入GEN、REVIEW和重建；来源正确但回答错目标须失败，不能借未选引用放行。

1Password真实稿的“但可移除后再加入”另含独立操作，独立审计为非原子。核对现有有限能力守卫是否漏掉中文转折连接词；若证实，只补该通用语法对照及真实失败测试，完整条件例外和共享前提不删减。

独立质量探针还需覆盖“但用户可……”等带中文显式主语的转折，不能只拦省略主语。修复沿相同有限能力守卫完成，不列举产品或角色白名单；保留正当条件、例外及主语长度边界的测试。

- [ ] 建立实际CF失败及无产品名通用对照的红→绿测试，旧未标记合同逐字节保持。
- [ ] 追加规格→质量独立审查，冻结新源码，再做全后端与四产品真实复验，结果写入独立`writer-clause-targetfix-2026-10-31`目录。
- [ ] 仍按同一8题22分支严格审核；不增加预算、不更换评分、不覆盖首轮失败、不将同题其他任务的quote自动补给当前主张。

## 真实复验后的派送一致性窄修

目标投影修复版本全后端9438通过，但四家严格内容验收仍2/8完整、报告前三类1/4、系统QA0/4。该轮源码、真实结果和原样报告单独保留。

只读重建证实CF两个失败任务的复用补交分别14749、14259 UTF-8 bytes，超过14000上限；repair forecast为true，真正call却在长度守卫直接返回None。省去可选失败raw诊断后仍保留完整问题与所选quote且可入窗。Trello四项补交为真实`reserved_for_delivery`，不通过抬高预算放行。

- [ ] 只在新合同中对补交诊断作确定性的有界投影，完整原失败raw继续保留在原trace；不得裁切源证据、当前任务或完整前提。
- [ ] 统一实际wire字节预检与call守卫，真实超窗明确记录原因，避免预检允许后静默跳过。成功peer、一次补交上限、来源准入和原始身份不松动。
- [ ] 以原CF失败重建与通用无产品名fixture先红→绿，覆盖跨run／task／snapshot或诊断篡改、源证据完整性及真实派送/replay。
- [ ] 规格→质量均通过后才启动最终全后端与同预算四家真实复验。结果使用独立`writer-clause-dispatchfix-2026-10-31`目录；前两轮失败均锁定保留。

## 实际执行结论

实施和验证已经完成本轮三个增量：单任务GEN／服务器子句审核；实际引用与CPU目标传递及中文条件边界；补交诊断入窗、实际派送与本地延期证明。最终增量规格293、独立质量414项通过，全后端9446通过／1跳过；标准API／TS新生成一致。真实四家全部跑完、同8题22分支逐条独立验收、三轮结果及12份原样报告已保存。发布范围与远端状态以Git提交和推送核验为准。

**本计划的报告交付目标未达成，不能将上面机制测试标作全文交付合格。** 最终2/8题完整、报告前三类1/4、严格QA0/4。单谓词的一般语义判断、持续访问与邀请的选证区分、来源不足时的语义重选、合理澄清的QA状态及受保护额度限制的补交仍需后续修复。管理员规则采用通用角色列表输出并保留题设资源，未放松真实改权绑定来接收带资源标签的执行断言。

各验收条目的实现、测试和局限以[交付记录](2026-10-31-single-predicate-clause-delivery.md)与[最终结果](2026-10-31-clause-final-results.json)为准；历史失败、拒绝审查、红测和原源码不覆盖。没有执行Docker或模型训练。
