# 问题缺口驱动补证实施计划

> 按用户已确认的方向连续执行。使用 writing-plans、TDD、subagent-driven-development 和 dispatching-parallel-agents；复用当前隔离 worktree。原始参考答案不进入任何 Agent 输入。

**目标**：将显式问题作为采集请求传递，在当前研究管线内发现缺少的证据、先重用已抓正文再定向补抓，重新准入后进入正常分析与写作；三家真实报告逐题验收。

**架构**：复用现有 QualityGap / RepairTask / Capture / Admission。新增问题级“候选证据/缺口”评估，不赋予它事实生产或最终 answered 权限。与仅改提示词相比，这能追踪未覆盖问题；与自由循环 Agent 相比，保留明确预算和停止条件。Writer 后置重做仅作既有兜底，本轮主修补证发生在分析快照冻结前。

**技术**：Python / Pydantic，现有 DeepSeek、本机 E5、Research Pipeline 和共享证据快照。不加 Docker、Redis、Kafka 或新服务。

## 1. 问题请求与缺口合同

文件：`research/models.py`、新 `research/question_scope.py`、新 `research/question_evidence.py`、`research/repair/strategies.py`；Writer 保留旧 import 入口。

- [x] 将现有按产品分题逻辑移至 research 公共层，新增 `ResearchQuestion(question_id, question)` 与 `ResearchBrief.questions`。只传原始问题，不从预算/角色/套餐请求构造产品事实。
- [x] RED：合法来源数/任意功能不能关闭另一具体问题；缺行、重复/未知问题、拒绝或跨产品 evidence ID 均保留缺口。
- [x] `question_review_payload(brief, evidence_items, max_bytes=12000)` 只发送当前分支已准入完整观察；容量省略明确记录。
- [x] `question_evidence_gaps(brief, evidence_items, assessment=None)` 校验 `{questions:[{question_id,status:candidate|missing|unverified,evidence_ids,missing_fields,reason}]}`；candidate 只代表可供下游核对，不代表答案正确。缺口 metadata 保留 question ID、原问和缺少条件，不产生产品事实。
- [x] 用现有 RepairTask 生成基于原问的官方查询，预算受原 brief 限制。

匿名例子：`Questions about Example Suite Guest access` 不能由另一角色的评论观察关闭；`status=candidate,evidence_ids=[rejected]` 仍生成缺口。

## 2. 定向原文提取

文件：`research/extraction/semantic.py`、必要 `extraction/quality.py`、`evidence/admission.py` 与小范围操作解析；独立测试。

- [x] RED：问题目标在 12k 后、第三页比前两页更匹配、邻近价格导致功能句被拒、明确功能可用性/否定句被丢、同页不同 focus 结果 ID 冲突。
- [x] 依真实问题选择完整连续正文窗口并为页面排序；词项和相似度只用于选择，不能作为支持判断。保留标题、原文偏移和来源条件，不拼造句子。
- [x] 暂不提高输入/输出上限。指令注入仍拒绝；完整功能段的邻行金额不能自动升级为结构化报价，也不应误杀该功能段。
- [x] 支持通用功能可用性/排他限制句，不添加 Miro/GitBook/套餐答案特判。源中角色、套餐和否定必须保留。
- [x] 提取 focus/window 指纹进入缓存和 extraction version；准入用同一请求重新计算原文/位置/值，不能只相信 metadata。

## 3. Collector 与管线补证

文件：`agents/collectors/logic.py`、`research/pipeline.py`，必要来源保留入口；root 实施。

- [x] RED：真实 brief 含决策问题；语义缓存不串不同 focus；问题补证的新事实不会被旧 extraction 或来源数量裁剪吞掉。
- [x] 初次提取按问题选择页面；每分支最多 3 个定向页面（原有更小全局额度优先），不是给每页无限重试。
- [x] 补证评估通过有界模型回调，只读已准入证据。先尝试已有正文的缺口 focus，再复用现有剩余搜索/抓取额度；每分支最多一轮问题补证、最多两次评估。
- [x] `(question_ids, body_hash, window_hash)` 相同不重复模型调用；无新准入证据且缺口不减少停止。缺证、无进展、容量/预算不足及权威未验证留在结果/trace 中。
- [x] 任何 research_depth 下都对新增补证计数，RepairTask 不能扩大 brief 的搜索/抓取上限；新 URL 继续要求既有官方权威验证。
- [x] 合格补证进入 normalized fields、RawSource、KB、快照及正常 Analyst/Writer；缺口页只在已有候选/抓取预算内保留。

## 4. 验证与交付

- [x] 先匿名 RED→GREEN 和现有相关回归，再独立规格/质量审查；实现冻结后跑完整后端回归，必要时同步 OpenAPI/前端。
- [x] 最后冻结版本分别跑 Miro、Basecamp、GitBook 官方 URL 真实阶段流程。每 run 最多 24 calls / 80000 tokens，输出 2048、Writer/review 1600、retry 0；最多三组正式尝试及一次有具体原因的定向重跑，全部尝试计费/失败保留。
- [x] 使用已确认但已曝光的 8 题参考，仅在生成后对照实际正文。工程通过、候选证据找到、模型 answered、可交付分别报告。
- [x] 不将固定 URL Collector→下游阶段诊断称为 Planner 自动发现、完整 Graph 或生产语义 RAG 全链路验收。当前中文日期报价自动处理等既有边界保持保守。
- [x] 更新 README、Agent 实际执行说明和交付记录，扫描凭据与提交范围，按既有授权准备当前 GitHub 分支的提交；推送结果以 Git 提交记录为准。

复测命令：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests -q --tb=short`。真实入口沿用 `backend/scripts/eval_answer_official.py`，预览后锁定输入、登记及代码哈希，再 `--run`；启用通用问题补证，不提高总预算。

验收：8 题正文结论、对象、角色、套餐、日期和引用符合已确认边界，且三个完整请求报告不含未解决 blocker。达不到时保留具体失败与未验收项，不伪称全部交付。

## 5. 首轮真实诊断后的有限修复

三组首轮真实执行均完成，未达到完整交付标准。使用预留的一次 GitBook 定向重跑验证下列通用修复，不增加总调用/输出上限：

- 多个问题且全文不超过 12000 字符时保留完整正文，避免只选一个可用性小节而丢掉同页授权条件。长文档和单问题继续选择连续窗口。
- 中文“看不到／不会”等明确否定允许作为实际答复，仍核对对象、角色与逐字原文片段；旧运行不改写，只做离线解析重放。
- 仅列举包含关系不能成为“只支持某套餐”或“必须升级某套餐”的依据。增加限定范围的套餐排他操作符守卫，匹配同套餐完整集合；未知范围保留未核实。这不是通用语义蕴含证明。
- 中文明确报价日期独立解析并验证，不用运行日期替换；无效或矛盾日期不自动生成已回答记录。

两次源码版本分别登记，首轮所有开销和错误保留。Basecamp 解析重放不冒充修复后的完整真实重跑；正式 Miro 中失败的是 Guest 来源，Visitor 来源经浏览器重试成功。
