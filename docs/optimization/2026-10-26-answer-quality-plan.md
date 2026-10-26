# 逐子问文本质量与独立审核实施计划

> 按用户已批准的方向继续：暂不以降本为目标，优先完整答复、精确引用、完整前提及正文／QA一致；暂不训练。采用 systematic-debugging、writing-plans、TDD、subagent-driven-development，逐任务实现后先规格审查、再质量审查。沿用已有隔离工作树，开发分支 `codex/pastoral-desktop`，基线 `43ade3d7d25545d7a7b6b7b03694e82dc15855a6`。

**Goal：** 修复当前子问范围、核心证据实际发送、逐条审核证据边界和最终QA逐题资格，使文本质量能够独立验收。

**Architecture：** 现有共享快照／按题池 → 版本化当前子问任务与完整支持 → 绑定任务的独立结论 → 单主张、独立支持审核 → 完整原题答案核对／确定性正文 → 无损编码的逐题最终QA。历史v1生成与审核请求仍按原SYSTEM／原装包重放；新投影和最终QA语义使用显式版本，不复用旧正向缓存。

**Tech Stack：** 现有Python／Pydantic／snapshot／StageEvidenceView／pytest及DeepSeek完成接口。无新基础设施，不训练、不改前端。

## 已证根因与方案取舍

1. Trello span-48把查看看板与下载主张同批审核，下载自己的所选句只讲禁止编辑／上传；模型错误借用查看主张的正向t0并给supported。上游分析中也有下载断言。审核实际输入约12KB，含三类上游建议；审核需要的是本条精确支持，而不是另一份产品总结。
2. 原子生成只用`question_atom_tasks`排序，没有发送任务契约／支持提示，SYSTEM仍写完整原问；完整父原问与当前投票子问产生范围冲突。原始11条先输出背景，任务容量被占用。A/B投票本轮都进入8条解析结果，主要问题为错选s9，不能误写成B被截掉。
3. Cloudflare核心CPU Standard表在pool/view，生成装包却把0～4分统一分为0档，再优先最短，先选无关权限短行，CPU完整表未实际发送。缓存脚注CPU未审不等于完整费率已到。
4. CF跨域题实际逐题重放无core／exception缺口，账单题有core遗漏。最终QA用`not evidence_issues and producer_verified`统管全部题，把维度聚合`answer_coverage_incomplete`污染完整题。
5. BW／1P完整最终候选含大量完全相同的绑定及问题文本；6000-byte窗内未做题内结构去重。纯内存原型保留全部信息后可从7600／7766缩至5822／5964，但真实新协议和模型效果尚未验收。

方案A（采用）：修上述边界并版本化当前子问投影、单条独立审核、无损最终QA。方案B：整体重回逐任务多次写作，会重引旧调度和重复规划，本轮不整体切换。方案C：只增加提示或扩大上下文，不能修复未发送core、错引用资格与全局状态污染，不采用为主要方案。

用户“允许继续”已授权此范围；本计划记录实现细节，不再重复申请实施许可。所有计数及成本保留，但不以调用下降作为成功标准。

## Task 1：单主张支持隔离与可核验选中支持

**Files：** 新 `backend/packages/agents/writer/atomic_claim_review.py`、新 `backend/tests/unit/test_atomic_claim_review.py`；修改 `question_atomic_delivery.py` 运行及重放入口，必要时适配原子测试夹具，不改共享旧REPAIR_SYSTEM字面。

- [x] 红测复现两条主张共享一批、下载自己的支持为禁止上传句、旁边查看主张与上游建议包含下载正句。
- [x] 新审核投影一次只发一条主张及其完整支持、必要限制、当前子问与绑定父题设；三类上游内容只保留可重建的生产者／快照哈希引用，不向审核模型提供产品建议正文。
- [x] 新审核协议显式版本2和SYSTEM身份，receipt保存版本；缺字段的历史receipt按原v1两条批次、原payload／SYSTEM重放。新版本字段删除、改为未知版本或篡改引用均拒绝。
- [x] 正向审核附本条支持见证（索引及原句中的精确节选）；服务端只接受实际本条selected support中的精确文字，别条主张／父题／建议里的文字不能作为见证。节选不能替代完整支持及条件，实际审核始终带完整原文。见证检查不冒充语义蕴含证明。
- [x] 解析只让当前坏主张失效；未审／超时／无见证／引用错配不发表。保留现有完整主张、原子性、操作条件检查及真实transport重建。

红测接口示意（新增模块在本任务定义）：

```python
def test_witness_cannot_borrow_sibling_quote():
    selected = ["Observers cannot upload attachments."]
    witness = {"support_index": 0, "quote": "download attachments"}
    assert not selected_support_witness_valid(witness, selected)


def test_witness_matches_only_exact_selected_text():
    selected = ["Guests may download attachments after approval."]
    assert selected_support_witness_valid(
        {"support_index": 0, "quote": "download attachments"}, selected)
    assert not selected_support_witness_valid(
        {"support_index": True, "quote": "download attachments"}, selected)
```

专项命令：`COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_atomic_claim_review.py backend/tests/unit/test_question_atomic_delivery.py -q --tb=short`。

- [x] 看见正确红测后实现最小修复；运行专项与既有引用／操作回归；独立规格、质量审查通过。

## Task 2：当前子问任务、core优先装包与完整候选

**Files：** 新 `backend/packages/agents/writer/atomic_question_projection.py`、新 `backend/tests/unit/test_atomic_question_projection.py`；修改 `question_atomic_delivery.py` 新投影分派与重放，复用 `question_allocation.py`／`task_protocol.py` 已有拆题和支持评分；不全局改变旧 `source_span_candidates`。

- [x] 红测以当前A/B投票子问＋完整含下载／导出／义务的父题：保留全部题设，只创建当前投票规则和A/B任务；父题不是输出任务列表。
- [x] 生成投影版本2显式发送服务器任务ID、原请求片段、focus／resource及最终实际目录里的s/o支持提示。每条结论绑定当前任务且只含独立谓词；明确操作／资源任务逐项分配，人数与容器等可识别独立约束分别规划。无法有限拆开的通用source_rule可交付少量必要独立规则，不能强迫复合结论或只准一条而丢另一约束。额外背景、重复／未知任务不能占满8条名额；缺项按任务记录，不能默默视作完成。超出容量明确延期，不切开AND/OR前提。
- [x] 装包先预留任务元数据，纳入当前qid core及完整例外闭包，再按当前任务真实分数挑完整原文，最后才背景；0分短行不能替代已有core。硬14000-byte不变，不用只出现在ID列表证明送达。
- [x] 新候选只从既有可验证绑定集合选择完整句、闭合表格／条件组；排除可识别的孤立标题及Because未闭合片段。缺少可验证完整支持就保留缺口，不编造新source span。完整原始fact仍作限制上下文。
- [x] 支持提示由最终实际发送目录重建，包含合法o操作与s原句，编号和绑定双向一致。提示不是证明，仍须独立审核。任意双s拼接继续拒绝；需要多规则时先分别发表有证规则，由原问核对受审有限推论，未具备足够绑定就留缺口。
- [x] 原子receipt保存生成投影版本，旧v1原SYSTEM／原排序／原候选重放保持；新SYSTEM、任务、core选择、refs、版本和hash任一改变均失败。

关键红测以真实形态匿名夹具构造：5960-byte计费core＋0分权限短行＋Standard背景，断言 `core.id in actual_generation_fact_ids` 且完整 `core.quote`实际存在；不能只断言packet包含ID。带`if X and Y / unless Z`及角色／套餐的完整支持必须原样保留。另用被冻结的CF与Trello资料作只读回归，不改原件或评分标准。

专项命令：同离线环境运行 `pytest backend/tests/unit/test_atomic_question_projection.py backend/tests/unit/test_question_atomic_delivery.py backend/tests/unit/test_question_allocation.py backend/tests/unit/test_source_span_binding.py -q --tb=short`。

- [x] 红绿、旧v1真实重放及新版本篡改测试后，独立规格、质量审查通过。

## Task 3：逐题最终QA资格与完整上下文无损编码

**Files：** 新 `backend/packages/agents/qa/question_review_encoding.py`、新 `backend/tests/unit/test_question_review_encoding.py`；修改 `independent_question_review.py`、必要的 `question_context.py`／`evidence_alignment.py`，保持共享旧最终审核SYSTEM；新增逐题资格测试，保留严格澄清所有负例。

- [x] 红测：A题实际完整，B题core缺失，只有维度聚合覆盖失败，A不能被连带diagnostic；未知来源／生产者／hash／例外异常仍阻断，不能靠匹配problem字符串放行。
- [x] 从当前真实重放和完整绑定重建带qid／claim／source依赖的资格；核心完整性必须用本题实际generation派送原文，不能拿其他题已发fact的union补本题。维度覆盖缺口仅在可明确归因时按题处理；canonical、生产者、实际派送、选中支持与例外的硬失败不放松。必要澄清维持当前完整服务端合同和真实独立审核。
- [x] 新独立协议v5及独立编码版本。只共享完全相同的结构与字符串，选择实际byte净收益表示；严格`decode(encode(payload)) == payload`，保留全部主张、原文、绑定坐标、前提、否定、模态、例外、子问与正文。不得用相近字符串或删部分主张来“压缩”。
- [x] 引用缺失、循环、跨包、类型伪装、未使用／额外表项及变更条件／坐标均拒绝；若不能无损装入仍整项未送。SYSTEM说明编码，actual dispatch与正向缓存重放使用精确新payload，旧v4缓存不当作新v5审核。
- [x] 新v5SYSTEM保留全部语义约束并简洁表达，使最终QA保护不超过原12000；保持6000-byte／最多6批／每项2次界限。
- [x] 不事后替换已签`report_md`破坏Writer或QA依据；先解决逐题资格，再以最终审核状态独立核验正文结论。

```python
def test_review_encoding_is_exact_roundtrip():
    support = {"quote": "Only editors with plan A and approval may export unless locked.",
               "start": 8, "end": 80}
    value = {"claims": [{"id": f"c{i}", "support": support} for i in range(4)]}
    assert decode_review_payload(encode_review_payload(value)) == value
```

专项命令：同离线环境运行 `pytest backend/tests/unit/test_question_review_encoding.py backend/tests/unit/test_independent_final_question_qa.py backend/tests/unit/test_final_qa_shared_context.py backend/tests/unit/test_final_qa_batches_transport.py backend/tests/unit/test_question_context_qa.py backend/tests/unit/test_clarification_qa_alignment.py -q --tb=short`。

- [x] 看见红测后实现并复验真实形态BW／1P完整候选装包；不将1P六次脱敏历史输入说成已验。独立规格、质量审查通过。

## Task 4：整体集成与正式内容验收

- [x] 相关回归、全后端及变更Ruff相对基线新增0；记录真实失败、夹具适配及修复过程，冻结源码／提示／参数／资料哈希。保留527份历史原件及审计，全部只读锁核。
- [x] 在独立的新忽略目录保留原件；只使用完成接口，固定官方资料和原八题，重跑四家阶段流程＋七角色请求隔离。补至少两个通用跨句／条件新回归样本；候选或未人审不计正式独立盲评，不给Agent参考答案。
- [x] 保持生产默认预算和双实验0；质量复验使用独立、有界配置（每运行最多48次／160000 token，原费用护栏仍为0.25美元），为完整写作审核留额度，成本只记录。公开全部参数，不与旧24次／80000预算混作同条件成本对照。一次冻结复验后独立审计：8原题22必要分支、全部正文主张支持／原子性、关键core实际发送、逐题原子交付／最终QA送达和状态。未达标如实报告，不为旧题反复改提示刷分。
- [x] 明确这轮修的是逐题事实交付；产品经理完整竞争战略维度、实时抓取、自动发现、全Graph发布／前端／生产稠密RAG不冒充已验。未训练。
- [ ] 更新README、Agent执行说明、交付MD／JSON；最终代码与数字独立审查，通过后按既有授权准确提交范围并推送，核对远端SHA。计划提交前状态与最终发布回执分别记录。
