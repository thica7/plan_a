# 子任务证据与原子交付实施计划

用户2026-10-31已授权实施：Writer按子任务选证及原子写作、Trello漏答、Cloudflare完整引用／例外、1Password正文与状态一致、统一QA，再跑四家。基线129d9e4cc91e336125454a987031d52d6eff4b26，复用codex/pastoral-desktop隔离worktree。Docker、训练、前端重做、数据库改造不在范围。按systematic-debugging、writing-plans、TDD、subagent-driven-development、verification-before-completion执行；一位生产作者，规格通过后质量审查。

## 证实根因与方案

上一轮固定官方快照最终6/8原题通过，文本2/4、文本加证据1/4、strictQA0/4。Trello第二题没有GEN transport，整题question_context_budget_exceeded；其他GEN仅两facts，10条original被延后。CF一个billing_inputs允许3claims，CPU句漏同源Cron／Queue例外，minimum单句附加未选monthly规则。1P单vault独立REVIEW支持，但重复数量guard漏single，转unreviewed；另一个混合句留下，ANSWER对two-vault未知。QA同时把显式单产品问答按比较矩阵缺口阻断。

比较三种方案：追加通用Prompt与词表不能解决共享窗口和多任务自由选择；整个替换Agent流水线扩大范围且丢现有审核／数量凭证；采用任务级证据与交付边界，复用现有SELECT、精确source refs、审核及回放。选择第三种，落实用户已授权方向，不再要求重复确认。

## Task 1：Writer与QA的同一交付链（唯一作者串行）

文件范围：新增小型task-local协调／投影模块；必要接线atomic_question_projection.py、question_atomic_delivery.py、task_support_selection.py、task_decision_witnesses.py、dimension_writer.py、complete_predicates.py、answer_coverage/presentation.py、qa相关入口与reflector/logic.py。保留旧代码路径，不重构无关巨型模块。若API形状确需变化，使用标准生成工具。

1. 先用真实payload离线重放记录上述断点，新增自包含、品牌无关的失败测试；实际旧run只放ignored新artifact探针，不把参考答案或旧run全文塞进生产或unit依赖。
2. 新显式task_execution_policy，默认空走原GEN5。调度身份为(question_id,task_id,attempt)。从完整当前问题pool按task分配窗口，保留完整来源、限制与例外闭包；一个任务放不下明确deferred，不吞同题其他可完成任务。
3. 复用现有task_support_selection选证契约：先提案选完整span／operation，严格核task/ref/source，再只把该任务与完整选定证据交给GEN，每次最多一个独立主张。选择不是事实审核，不能借未选邻句；每条主张仍独立REVIEW。billing按所问依赖生成最小必要规则，不附加未问调用上限；若断言上限必须含其适用例外。
4. 真正执行share/manage_access仍需operation绑定；服务器明确的资格名单／跨资源非蕴含是独立谓词，须完整source-span和实际任务审核，不因提及Share按钮或假设改权而被当作已经执行操作。必须先复现误拒，不全局放行inference。
5. 统一有界数量语义，正确识别single／one／一等同单位形式；描述数量不变成上限，时间、scope、role不能省略。新policy可改数量guard语义，旧记录保留原语义。
6. 先完成所有任务首轮，再只修失败任务，保留成功peer。新receipt与严格replay支持同qid多个GEN，需核唯一task/attempt、完整选证、真实transport、源hash及实际REVIEW；同步旧_rebuild假设，篡改不得通过。
7. 从同一已审task结果构造ANSWER候选、正文和coverage，仍保留真实独立ANSWER审核及reviewed_quantity_conjunction-v1。supported来源规则不自动等于任务已履行；未知与合理澄清如实保留，不用额外正文掩盖问答缺口。
8. QA依据同一实际发表答案／选证与明确任务范围。复用_question_delivery_scope，显式单产品问题不强制比较矩阵；比较／排名、多产品、全量研究及不明范围仍保留矩阵门。缺来源、错误引用、没答子问不能被范围豁免；历史混合问题保守处理，不强制清模型keep。
9. 生产默认实验开关不改；原GEN／REVIEW／ANSWER／QA receipts无新policy不升级。预算和finalANSWER／QA保护继续执行；不隐藏增加调用或无限重试，预算不足记录任务级延期。

## Task 2：独立审查与最终验证

- 作者红绿、自审、源码冻结。独立规格核完整任务窗口、跨题／错ref／缺例外、one-task-one-claim、single同单位、正文状态／QA一致、旧回放／数量AND、预算及失败局部重做；通过后独立质量审查，有问题交原作者修后重审。
- 所有旧原件只读，新目录data/artifacts/writer-task-delivery-2026-10-31；已锁599旧文件。最终源冻结后一次全后端回归、实际路径差分Ruff、必要API／类型／前端检查；仅新修改或失败才重复相应检查。
- 同8原题／22分支与2026-10-21官方快照，真实deepseek-flash别名、温度0、默认模型参数与48calls／160000tokens控制、最多两产品并行、显式实验开关、无隐藏retry。新任务结构实际成本如超该profile先算清并明确另轮参数，不静默提高生产预算。
- 真实执行7生产阶段；固定快照不等同新抓取、竞品发现、完整Graph或实时性验收。独立审计直接读最终正文与精确所选片段，原题／分支、额外主张、原子性、内容／系统QA分别计，保留全部失败。
- 更新README、Agent职责说明、交付与原样报告，精确扫描暂存源码／文档，按既有授权正常push当前分支，不强推／合main／清工作区。真实凭据、模型权重、运行库不提交。

验收目标是通用任务交付能力，并非把四家答案写进规则。1Password官方报价缺源仍按缺项交付，不编销售路径；新抓取与新产品独立验收另记。本轮不以工程测试通过宣称报告4/4。

## 首轮真实失败后：必要的 v2 修正

首轮已完整保留：107次真实传输、304718已知token，8原题仅2通过／4部分／2失败，四种整报告交付均0/4。最终冻结源码工程回归9274通过／1跳过不能证明业务合格。独立审查还修复了首次SELECT失败不可回放、混合业务缺口被矩阵豁免两项边界，相关红绿证据均保留。

真实诊断又复现：Trello未执行GEN的修复尝试污染首轮聚合状态，当前回放失败；其尾答完整请求与最终QA合计超160k上限881，而重复task候选占1489字节。Cloudflare完整CPU行被候选预测窗口挤出，选定行的临时表示又丢失已准入parent适用范围。管理员闭合资格规则仅因合法产品前缀被服务误拒。Bitwarden的collections规则实际已入窗，生成混入其他数量／所有权谓词才被拒；不是缺少该资料。1Password邀请规则被强化为确认后成员资格禁令，独立REVIEW拒绝合理，不能靠放宽审核解决。

同一用户授权下继续最小修正，新增显式v2策略，保留v1真实SYSTEM、payload及原回放语义，旧失败不升级：

1. 无GEN的补交只记录准入／执行失败，不覆盖已生成任务结果；自包含复现实际聚合回放失败。
2. 对实际贪心ANSWER窗口按完整SYSTEM＋可读输入＋输出保护额度，局部补交不得消费尾答及最终QA保护；去掉重复尾答候选，不删真实分析、比较和反思产物。旧checkpoint限额／已付用量不提高。
3. 候选容量以真实SELECT输入计量，避免按未发送的生成包装提前挤出合格原文；选后GEN仍独立检查完整条件与实际字节。CPU准入复用现有selected＋parent表格依赖校验，错SKU／缓存脚注继续拒。
4. 仅允许当前产品绑定的资格规则前缀，闭合角色名单、对象、范围和实际操作门保持。任务明确required kind与最小谓词，必要局部修复携带真实失败原因；模型混合／虚构／情态强化继续拒绝。
5. 先维持48calls／160k profile。若完整窗口预算证明无法承载，再明确记录runner专属新profile及参数差异，不改生产默认、不当作同条件因果比较。

新证据与下一轮真实输出放data/artifacts/writer-task-delivery-fix2-2026-10-31；已锁784旧文件，首轮原样报告公开保留。仍先TDD、规格与质量审查、最终回归及四家真实回放，再独立检查最终正文。预算修正不代表后续语义一定通过。
