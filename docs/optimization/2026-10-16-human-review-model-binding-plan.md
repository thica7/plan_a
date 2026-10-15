# 独立人审与真实模型前提／引用验收计划

> 用户已批准：先推送上一轮交付，再准备独立人审内容，并继续真实模型测试。执行沿用当前分支；采用 subagent-driven-development 分工准备资料与实现，并依次做 SPEC／QUALITY 审查，不新增功能或更改既有金标。

**Goal:** 将“资料是否够”和“模型是否正确理解并引用资料”分开验证，给出可逐条复核的报告交付结论。

**Architecture:** 固定新官方证据及候选结论，人工审核状态与模型输出分开存储。真实模型使用生产语义提取、分析、比较、写作、审核与绑定保护；固定证据输入用于隔离前提和引用错误，不冒充联网发现／采集验收。人工审核未返回时只运行 candidate-diagnostic，不计正式通过率。

**Tech Stack:** 现有 Python/FastAPI RunService、DeepSeek 配置、生产 evidence admission/snapshot/writer/QA、pytest、JSONL。

## Task 1：推送已验证交付

- [x] 确认源码锁 `29254d486597f2887bab8cb4074eed6afd643ab17fa3b30c338e5883b9e595a3`、凭据扫描、fresh 38 项回归及 diff check。
- [x] 提交并推送 `d47c9a9c96f917db47c53e43c6195f1fc004beee` 至 `origin/codex/pastoral-desktop`，远端哈希与本地一致。

## Task 2：准备人审样本

**Files:** 新建 `eval/product-condition-review-v1.jsonl`、`docs/optimization/2026-10-16-condition-human-review.md`。

- [x] 只用新的官方资料准备 8 道候选，覆盖角色／套餐／访问范围、禁止操作、配置前提、资料不足和澄清。与旧 8／16 题分开；标明已曝光、待人审，不称盲测。
- [x] 每题记录问题、官方依据、可支持结论、不可推断边界、要求的来源及事实绑定；不复制整页资料，不将用户条件或编辑摘要伪装为官方原文。
- [x] 数据冻结后记录 SHA256，通过异步问题把 1–8 的审核内容和官方链接交给用户；不自动填 reviewed_by。

## Task 3：真实模型有界验收

**Files:** 新建 `backend/scripts/eval_evidence_binding.py`、`backend/tests/unit/test_evidence_binding_eval.py`。

- [x] 默认仅列出输入和哈希，不调用模型。加 `--live` 才使用既有凭据与模型，不输出 settings／key；不下载权重或增加工作区额度。
- [x] 测试先行：拒绝未人审 formal、模型输入不含候选答案／评分标准、输入漂移中止、结果区分机械检查与语义人审、不会调用搜索工具。
- [x] 首先验证 Collector 前置条件，发现新产品身份未登记而跳过。受控诊断仅以 manual_note／unknown 的官方短节选机械原文映射进入真实准入、临时 canonical 与快照，再调用生产下游阶段；没有假装完成 Collector。Writer 模型与逐条主张审核实际为 0，真实硬化与 QA 拒绝，记录为空报告而不伪造通过。
- [x] 按小批次先执行 2 产品的前提／引用测试，最多 24 次 provider transport、每次最多 2048 输出 token、总预算最多 80000 token、重试 0；沿用现有预算保护，失败保留原始产物，不提升配额或伪造完成。
- [x] 记录各阶段真实调用／回退、提取原文与条件、矩阵、正文主张、引用、门禁、provider usage 和未知费用。人审参考不进入生产提示词；未人审结果仅候选诊断。

## Task 4：复核与交付

- [x] 若失败，按 systematic-debugging 先找出边界，再写最小失败测试；不改金标迎合模型，修复后的已曝光重跑不称独立验收。
- [x] 代码审查、相关回归与必要的全量测试；冻结最终生产源码和输入，确认实际结果来自当前代码。
- [x] 更新 README／交付记录，列出 1–8 待用户确认内容、真实模型执行范围与是否达到交付标准；未经人审不写“正式合格”。
- [x] 新增交付完成验证后单独提交，原始模型响应、运行数据与凭据继续不上传 GitHub。

## 最终执行结果与待办

- 上一轮交付先推送 d47c9a9，随后完成8题候选与审核卡，全部仍candidate，用户未返回审核。第4题在模型执行前限定已发布interface，源节选未变。
- 新入口20项回归；全量后端4246通过、1跳过。SPEC／QUALITY无开放P1/P2，源代码和输入live前后锁一致。
- 真实DeepSeek4次调用、provider9326tokens；Collector0、Writer模型0、逐条主张审核0，QA14issues／10blocker，正式正文0字符，报告未达交付标准。
- 资料与调用记录完成不代表语义验收；下一步先完成独立人审，接通可验证的新产品身份／官方来源及正式结构化证据后，再验收实际Writer和正文引用。
- [ ] 用户确认8题，保存真实人工审核记录。
- [ ] 真实来源／结构化事实进入Writer并完成生成报告的独立语义人审。
