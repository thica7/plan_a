# 结构化报价链路实施计划

> 使用 subagent-driven-development 执行当前会话的实施与独立审查；用户已授权本阶段，不重复请求确认。

**目标：** 以最小增量让报价条件贯穿抽取、准入、存储、快照和报告边界。

**技术：** Python/Pydantic、现有 research pipeline、现有 answer guard、pytest 固定本地正文；不调用模型。

**设计：** `2026-10-06-structured-pricing-design.md`。工作区：现有 `plan_a_pm_modes` worktree，分支 `codex/pastoral-desktop`，基线 `13612d1`。

## Task 1：实施耦合的数据链路

文件范围：`backend/packages/research/models.py`、`evidence/normalization.py`、`extraction/pricing.py`、必要的专用报价解析 helper、`evidence/admission.py`、`backend/packages/tools/evidence_fetch.py`，及对应新增测试。现有 snapshot/answer guard 原则上保持不变。

1. 先写失败测试：旧展示文本兼容、零金额、条件/来源不串行、歧义和伪造字段受限、正文来源标记。
2. 增加逐报价 qualifiers/market 契约，归一化按原 EvidenceItem 保留来源和条件。
3. 两条价格抽取路径写入同一报价行的明确数值与条件；缺失不推断。
4. 准入重新核验原文与字段；真实官方归属、采集时效及历史上下文约束当前价；生产端明确正文来源级别。
5. 补实际 pipeline → RawSource → snapshot → Writer/QA 的离线测试，包括完整报价和关键反例。
6. 运行新增测试及相关回归，自审；不提交，由主 agent 统一交付。
7. 独立规格审查通过后进行代码质量审查；发现问题先修复并复审。

## Task 2：验收与交付

1. 主 agent 检查真实 diff 与测试证据，确认冻结评测和生产检索未修改。
2. 用 `/private/tmp/plan_a_phase2_full_verify.py` 运行后端全量隔离测试；临时 cwd、禁用 env 文件、临时 KB，不读取真实 runs。
3. 相对 `13612d1` 检查新增 lint；哈希核对 frozen_inputs；执行脱敏密钥扫描。
4. 写 `2026-10-06-structured-pricing-delivery.md`：实际范围、测试结果、限制、下一步资料要求。
5. 仅暂存本阶段明确文件，提交并 push `codex/pastoral-desktop`；匿名 GitHub REST 验证远端 commit SHA。

## 完成标准

完整明确的离线报价沿真实链路到达现有 guard；歧义、缺条件、历史/陈旧或伪造资料无法得到完整当前价回答。独立审查没有未修复的重要问题。报告实际验证结果和未验收范围，不宣称 RAG 已合格或真实联网已验收。

## 执行记录

Task 1 已完成，最终 SPEC/QUALITY 复审通过；新增 104 项正式测试。Task 2 最终隔离回归为 3088 passed、1 skipped，新增 lint 为 0，冻结的 8 个输入哈希不变。交付范围与未验收内容见 `2026-10-06-structured-pricing-delivery.md`。交付文档随本阶段代码提交现有分支；远端 SHA 由推送后的主 agent 验证结果确认。
