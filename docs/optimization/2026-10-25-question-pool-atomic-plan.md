# 按题证据池与多原子结论交付实施计划

> 用户已批准本方向和隔离／四家复验。使用 writing-plans 与 subagent-driven-development：按任务实现，规格审查后质量审查，连续执行；沿用现有 linked worktree `codex/pastoral-desktop`，基线 `8774bf000d21321b0f5526b0d6243ea76d3904d1`。

**目标：** 修复规范事实在逐题检索至 Writer 视图中的遗漏，把逐小任务重复选证／写作改为按完整问题生成多条原子结论、逐条审核和确定性正文投影，正确区分必要澄清与未完成；以真实复验判断是否达标，暂不训练。

**架构：** 已准入快照 → 带完整父题设的按题证据池 → 一个问题一组独立主张／精确支持 → 有界批次逐条审核 → 原问答案核对及确定性正文 → 独立最终QA。保持默认关闭的实验开关、24次／80000 token、来源／租户／版本校验、完整条件与例外。旧逐任务协议及收据继续按原版本重放。新路径减少规划／付费选证／逐谓词修复，不能直接采纳分析建议或跳过最终审核。

**技术栈：** 现有 Python、Pydantic、LangGraph、snapshot/StageEvidenceView、pytest、固定官方资料及 DeepSeek 完成接口。

## 方案取舍与验收边界

用户已选择按题池与多原子生成；不采用继续堆单任务提示、扩大总预算或无审核直接写作。小视图缺失只说明当前范围未送，不能声称页面未记载。推论必须显式绑定完整所选规则和题设，不添加运行时拒绝等未证机制。必要澄清不冒充产品结论，只有服务端可重建的澄清字段与已发表文本一致且独立审核完成，才解除对应问题的阻断。

本轮先离线验证，再冻结同一源码跑一轮四家回放与七角色单请求隔离；保留所有失败和成本，不能为了旧题分数重复调提示重跑。新页面抓取、完整Graph、生产稠密RAG、前端和训练不在本轮范围。原八题已曝光，不称泛化评测。

## Task 1：按题证据池与投影追踪

**文件：** `backend/packages/agents/writer/question_retrieval.py`、`backend/packages/orchestrator/question_packets.py`、必要的 `evidence_context.py`；新增 `backend/tests/unit/test_question_evidence_pool.py`。

- [x] 从上轮冻结 Trello snapshot／span37 复现逐板规则已入库却未进候选；先写最小真实形态失败测试。
- [x] 每题保留完整候选排名／原始fact身份／例外闭包及未选原因，不把每题top3直接当全部资料池；作用域和已准入状态仍由现有规则验证。
- [x] 池与各阶段实际可送视图区分；实际Writer按题选择来源，原文不切片，容量不足明确延期，不能静默漏掉重要规则或提高硬上限。
- [x] 正反例覆盖低排名相关规则、跨题公平性、复合请求、重复原文、冲突／过期／跨租户和超容量；旧选择收据可重放。
- [x] 独立规格审查、质量审查后封存本任务。
- [x] 真实Trello规模复核发现12条pool请求绕过旧`<=8`Writer扩展分支，由原路径32KiB降为16KiB，两关键规则仍被裁减；仅新版池恢复既有32KiB allowance，保留首次失败和32KiB对照，新增两红测后池15项／联合181项通过，独立规格与质量复审通过；真实入口两规则均完整进入view，另有一条无产品信息原文延期。实际14KiB生成窗仍待Task2核。

## Task 2：按题多原子生成、逐条审核与正文投影

**文件：** 新 `backend/packages/agents/writer/question_atomic_delivery.py`；`dimension_writer.py` 的实验入口和答案核对分支，必要时原解析／支持工具及QA实际派送重放入口、`config/settings.py`、`.env.example`；新增 `backend/tests/unit/test_question_atomic_delivery.py`。

- [x] 红测：同题多条独立主张一次生成，完整支持绑定；有效同行不受一个坏主张牵连；全部必要分支可发表。
- [x] 新增默认关闭 `WRITER_QUESTION_ATOMIC_ENABLED=0`，与原实验开关共同启用；旧实验入口与已存收据保持，新真实回放显式启用两个开关。一个scope统一view/use，不能把多个凭证的事实合并进单凭证audit。
- [x] 复用 `parse_question_claim_plans`、来源引用恢复及 `audit_report_claims`，以完整问题装包，去掉新执行的付费小任务规划／选证循环；保留旧协议重放函数。
- [x] 每条主张独立精确支持、完整条件与原子性检查。审核可同批多条，但按claim ID逐条核对；未审、无效、超时均不发表。
- [x] 生成上下文真实保留父题设、逐题证据和三类上游建议，绑定实际transport及依赖；建议不是来源。
- [x] 答案核对从已审原子主张按完整原题／server分段生成，不再逐小任务反复解释；正文只投影审核结果，安全缺价／合理澄清独立表达。有限局部修复仅处理有明确审核失败、且剩余完整链路可送的项；保留原总预算。
- [x] 回归旧任务收据、未审核拒绝、越引用断言、跨qid引用、复合主张、无进展与预算不足；独立规格及质量审查。

独立审查额外修复：完整池例外伙伴缺少视图授权、英文模态否定误收、纯操作预测漏审核；质量审查补修正常换行与解析前前八候选截断。完整原文／绑定及实际8条上限保持。最终原子专项47项通过，规格与质量复审通过；真实模型结果仍待Task4。

## Task 3：必要澄清与独立QA状态

**文件：** `backend/packages/agents/qa/independent_question_review.py`、必要的 `question_context.py`；新增 `backend/tests/unit/test_clarification_qa_alignment.py`。

- [x] 红测复现Bitwarden必要操作／归属澄清正文正确却diagnostic_only导致blocked。
- [x] 从现有服务端澄清合同重建资格，验证当前原问、coverage、正式可见文本、有限字段、无产品断言及当前writer产物；不要求无事实的必要澄清伪造claim。
- [x] 独立模型仍须实际送达并完整审核；允许其确认澄清已适当处理请求，不能因缺证／unknown／任意diagnostic就通过，也不能放行篡改字段／正文／跨题结果。
- [x] 若改变审核语义，升级固定SYSTEM／协议身份，旧缓存不复用；回归缺价、未发表、超时、未送与重做路由；独立规格及质量审查。

新增澄清专项43项；独立规格与质量均通过。v4重放实际QA span与完整输入／输出摘要，旧shared SYSTEM保持；新增提示4137 bytes，对应预留11995，未提高原12000上限。代码布局增量经AST／SYSTEM等值复核；额外调用处仅补显式producer验证参数。

## Task 4：冻结、真实复验、独立审计与交付

- [x] 相关回归及全后端验证，变更Ruff相对基线新增诊断为0、diff检查；沙箱受阻单项必要权限复验分开记录。冻结源码／包／脚本哈希。
- [x] 新忽略目录 `data/artifacts/question-pool-atomic-2026-10-25/` 保留上轮原件锁；沿用2026-10-21官方页面、原八题与固定 `deepseek-flash`、温度0、provider重试0；仅完成接口网络。
- [x] 一轮四家流程与七角色实际请求隔离；新增CLI对实际atomic generation入口的恢复测试及识别，旧task span继续支持；缺少真实请求则未验，不能假装通过。
- [x] 独立审计正文8题所有必要分支、全部主张支持及原子性、事实池至正文去向、上游实际送达、必要澄清状态、QA送达／通过及总成本。明确相对上轮70次／193892 token是否减少、1/8是否改善，但不作单改动因果结论。
- [x] 更新README、Agent执行说明、交付MD／JSON，记录失败／未验并准备准确提交范围。
- [ ] 按持续授权提交推送并核对远端SHA；本计划是提交前冻结记录，实际发布状态以Git远端核验及本次最终回执为准。

## 验证命令

```sh
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests/unit:backend/tests/integration ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_question_evidence_pool.py backend/tests/unit/test_question_atomic_delivery.py backend/tests/unit/test_clarification_qa_alignment.py -q --tb=short
```

最终同环境执行 `pytest backend/tests -q --tb=short`。逐项记录红测与绿测；测试数量、接口成功、合法JSON、QA送达都不能替代正文交付。默认实验关闭，未训练。

## 2026-10-26：首轮真实预算阻塞后的修正

首轮固定源码 `51af5f14…` 已封存并独立审计：四家36次／119110 token，隔离6次／22354 token；Writer无实际生成，隔离明确未验。正文1/8、四报告均不达标。调用下降不能称降本。所有原件、失败及费用保留；`round1-source.zip` 保存796份原源码／测试／配置字节。

离线以真实scope／view／packet及可恢复prewriter状态复现Trello四题、Cloudflare两题的整条最坏请求预测超过80k而提前拒绝；另三题最终checkpoint不足以精确还原当时内存状态，保持未解释，不能宣称所有根因已证实。最坏费用顺序结算与同时预留的总量恒等，不能用“settle就会免费”解释。

为完成用户已授权的通用预算修复，追加一次有界修正与修正后验收，而不是修改提示追逐原题分数：

1. 当前生成／审核请求按同一实际请求构造器执行准入，保留现有answer与finalQA保护、调用下限、24次／80000及原金额上限。
2. 最低非空支持和完整审核窗口仍是生成前提；未来全链最坏预测改为诊断，不把尚未知的真实usage或全部atoms当保证。每次真实审核／尾答仍独立准入；未送／无效／超时保持未发表。
3. 持久化当前预算、未来预测及拒绝原因等小型诊断，不存另一套授权，不改变支持、SYSTEM、产物与重放合同。
4. 先以真实活跃保护和预算耗尽／金额／并发预留／无合法候选红绿验证，经独立规格、质量复核及全后端测试后重新冻结；仅再跑一轮四家与可实际执行的七角色隔离。原题、原网页快照、模型参数及提示保持，首轮与修正轮成本分别及累计披露。
5. 不根据修正轮语义得分继续改提示重跑，结果仍不达标时如实列出缺口；不训练模型。

## 最终验收记录

2026-10-26：最终全后端7852通过／1跳过；首轮及一次通用预算修正均保留，修正轮原八题3通过／4部分／1失败，四份报告均不达标，实验默认关闭。两轮累计108次／384517已知token，未知0。七角色单请求隔离3通过／2部分／2失败，不等于完整Agent验收。详见[交付文档](2026-10-26-question-pool-atomic.md)及[结构化结果](2026-10-26-question-pool-atomic-results.json)。
