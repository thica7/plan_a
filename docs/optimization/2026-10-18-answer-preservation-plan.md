# 已采事实与回答判断修复计划

> 用户已授权依次实施并重跑四产品，不再重复请求确认。复用现有 `codex/pastoral-desktop` 工作树；按 systematic-debugging、TDD、独立规格及质量审查执行。原首次评测文件保持不变，本轮属于已曝光开发回归，暂不训练。

**Goal:** 将问题需要的完整来源事实保留到正文，正确区分否定支持、澄清和缺证，再修复计费观察准入及诊断误脱敏，验证四产品报告。

**Architecture:** 继续使用已准入快照、完整主张及 v2 引用绑定。局部证据视图与实际模型输入分别受限，问题筛选不从无关操作推断要求；回答选择后增加有界语义复核并显示已审核的结论类型。功能问题允许收集来源中的计费规则，但不因此生成合格采购现价。诊断仅修脱敏边界，保留真实秘密保护。

**Tech Stack:** 现有 Python/Pydantic/pytest、DeepSeek、本机 E5；无训练、下载或 Docker。

## 1. 完整事实到写作上下文

Files: `backend/packages/orchestrator/evidence_context.py`、`backend/packages/agents/writer/dimension_writer.py`；新增 `backend/tests/unit/test_writer_question_preservation.py`。

- [x] 以旧 Bitwarden 的六条已选原始观察重放：16 KiB 视图只能容纳五组完整记录，My Items 在 compact 前丢失。匿名构造六组完整记录，先验证缺失 RED。
- [x] 对有界显式问题的 Writer 视图使用最多 32 KiB 的本地证据额度，实际 `compact_dimension_context` 模型输入仍最多 14 KiB；不得裁剪原文或条件。消费凭据及最终 QA 按同一额度重放。
- [x] 显式问题只按实际问题操作筛选；去掉“从最佳匹配事实反推所需操作”的路径。无操作问题不得因原文中其他动作而被筛掉；显式六类操作及定向重做约束仍保留。
- [x] 记录请求事实、视图事实、实际发送事实及省略阶段；匿名范围、完整条件、容量与历史重放回归通过。

## 2. 否定支持、澄清与结论核验

Files: `backend/packages/research/question_evidence.py`、`backend/packages/agents/writer/answer_coverage.py`、`backend/packages/agents/writer/answer_resolution.py`、`backend/packages/agents/writer/dimension_writer.py`；新增 `backend/tests/unit/test_answer_semantic_review.py`。

- [x] 先以匿名模型边界测试复现：上限小于请求不是缺证；未知移除/删除操作不能标 direct/yes；选择未发表 ID 或把例外留在 reason 不能通过。
- [x] Collector 明确同时接受支持“能”和“不能”的原文作为 candidate，不得为了要求的肯定结果补证；candidate 仍不是已回答。
- [x] Writer 优先给每道问题分配完整规则、例外和必要澄清，避免背景与重复套餐占满八条主张。不放宽六类操作绑定或逐条主张审核。
- [x] 回答选择后使用一次有界 QA 复核，同样只选已发表完整主张。复核检查所有子问、否定方向、操作/归属歧义、SSO/副本等源内例外；无预算、格式无效或未完成则不保留未经复核的 answered。
- [x] 二次复核还读取 compact 实际发送、但未发表的完整事实，以发现独立例外遗漏；仍不能把这些原文直接填入答案或充当已发表 ID。
- [x] 复核与最终 QA 保留 v2 完整复制和来源边界。报告显示结论类型和必要补充信息；不能把元数据的 yes 隐藏成已完成，不能用 reason 补事实。

## 3. 计费与域名范围原文准入

Files: `backend/packages/research/extraction/semantic.py`、相关 quote quality 调用；新增 `backend/tests/unit/test_question_rule_extraction.py`。调查确认后限定必要调用文件，不改 Writer 独占文件。

- [x] 匿名 RED 覆盖 feature 问题中的最低费用、请求/CPU 计费和无金额的销售报价规则；长页选窗不能被无关 availability 片段抢占。
- [x] 为明确计费问题提供受限的完整原文观察路径；保留问题作用域，金额仍按原价格规则校验，不能把请求中的用量和币种写成来源事实。
- [x] 表格候选仅遗漏装饰管道且可唯一重放为完整原行时，恢复原行；删单元格、改角色、缺条件或多义匹配继续拒绝。域名/账户范围句可作为原文条件，不因缺少六类动作静默消失。
- [x] 原文→accepted items→normalized_fields→snapshot 验证，并区分字段产生前丢弃与 admission 拒绝。

## 4. 导出误脱敏

Files: `backend/scripts/export_agent_eval.py`，必要时 `backend/scripts/eval_live_products.py`；现有导出测试及新增匿名回归。

- [x] 先运行 `/tmp/export-redaction-tests/test_export_redaction_regression.py` 对照五项既有 RED，移入项目测试时使用合成品牌/值。
- [x] 修复 credential 键边界及 URL 用户信息边界，不以具体品牌白名单修补；保留 URL 编码、引号、Bearer/Basic、前缀键、中文邻接 API key、真实敏感字典键和 PII 的保护。
- [x] 普通标题、context ID、合法 JSON-LD、嵌套 JSON 字符串可复核；原 raw `&` 参数边界不被解码后的伪边界破坏。旧占位不猜测恢复。

## 5. 验证、四产品回归和交付

- [x] 各模块 RED→GREEN、独立规格再质量审查；未解决 Important 不进入最终冻结。
- [x] 完整后端、变更 Python Ruff、OpenAPI 对比、diff check及只输出计数/路径的实际凭据扫描。前端/schema 未变时不冒称新前端验收。
- [x] 冻结生产源码、实际评测入口及输入/登记/manifest 哈希；八题参考只留评测侧。四产品各一次，单组 24 calls/80000 token/max output2048/retry0，已有本机 E5 离线推理，输出新目录。
- [x] 独立只读核对全部子问、结论类型、条件、逐条引用与保存的完整正文；完整报告和单题分别统计。失败、未知用量、格式错误与缺证保留，不暗改金标或首轮产物。
- [x] 更新 README、Agent 执行说明、交付及结构化结果；新结果不自动转训练标签，reward=null、training_ready=false。

Git 收尾沿用用户既有授权，提交并推送当前分支；最终 commit 和远端一致性以最终交付回复为准，不将报告内容阻断写成验收成功。
