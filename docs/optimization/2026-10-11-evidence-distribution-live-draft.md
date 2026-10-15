# Notion 小团队文档与知识协作工具 — L1 极简产品分析

## 执行摘要

**目标产品**：Notion，定位为小团队共同维护产品文档与团队知识的一体化工作空间。本次研究聚焦 feature 与 pricing 两个维度，对比 Notion、Confluence、Coda 三款同类产品。

**核心结论（暂定）**：在本次证据范围内，三款产品在协作功能上均有可验证的官方支持，但**当前定价数据未纳入本次证据视图**，因此无法给出价格层面的推荐结论。选择建议只能基于功能取舍，价格需另行验证。

## 竞争发现

| 产品 | 可验证协作能力 | 证据来源 |
|---|---|---|
| Notion | 评论、提及与提醒；支持评论的解决（resolve）与重新打开（re-open）[source:raw-source-b92f96c0c5e5d2643df7] | Notion Help Center |
| Confluence | 免费计划包含多项功能，官方称可"推动团队前进"[source:raw-source-859c368a1a9cd092356d] | Atlassian 官方功能页 |
| Coda | 支持通过 action formula 隐藏或显示页面；具备自动化（automation）能力[source:raw-source-253e8845f02fcb0d4c4d] | Coda 官方产品更新页 |

**协作能力对比要点**：
- **Notion**：评论工作流较完整，支持评论的解决与重开，适合文档评审闭环 [source:raw-source-b92f96c0c5e5d2643df7]。
- **Confluence**：官方强调免费计划的功能覆盖度，适合预算敏感且需要开箱即用的小团队 [source:raw-source-859c368a1a9cd092356d]。
- **Coda**：以公式驱动的页面控制与自动化见长，适合需要流程自动化的团队 [source:raw-source-253e8845f02fcb0d4c4d]。

三款产品在本次证据中均被标记为对应能力"supported"，但**证据置信度均为 0.64**，低于 0.75 阈值，因此上述功能对比仅作方向性参考，不足以单独支撑"最佳选择"结论。

## 产品机会与验证
- 待验证机会假设：探索与用户任务相关的产品改进，用户任务：共同维护产品文档和团队知识；验证动作：让目标用户完成同一任务并记录阻碍；成功信号：能够说明目标产品、同类竞品、关键取舍与证据不足。用户简报仅作为输入上下文，竞品差异与用户需求仍待验证。

## 置信度说明

**主要限制**：
1. **定价维度完全缺失**：Notion、Confluence、Coda 的 pricing 均处于 `clarify` 状态，缺失字段为 amount、currency、current_price。Notion 的 pricing 材料属于 `collected_but_omitted`（已采集但未纳入本次视图），并非原始页面缺失 [source:raw-source-b92f96c0c5e5d2643df7]。
2. **功能证据置信度偏低**：所有 feature 事实置信度为 0.64，低于 0.75，不能单独支撑赢家结论。
3. **多维度证据被截断**：Notion、Confluence、Coda 的 feature 及 Notion 的 pricing 均因 `context_budget_exceeded` 被省略，属于已采集但未选中，不代表产品缺乏该能力。
4. **未覆盖维度**：persona、review、market 维度在本次证据视图中无可用事实。

**结论性质**：本报告功能对比为**暂定结论**，价格结论**无法给出**。

**下一步验证**：补齐三款产品官方定价页的当前价格、币种、计费周期与席位口径。

## 证据附录

| 来源 ID | 产品 | 类型 | 置信度 | 标题 |
|---|---|---|---|---|
| raw-source-b92f96c0c5e5d2643df7 | Notion | webpage_verified | 0.96 | Comments, mentions & reactions in Notion |
| raw-source-859c368a1a9cd092356d | Confluence | webpage_verified | 0.96 | Confluence Features - What's New |
| raw-source-253e8845f02fcb0d4c4d | Coda | webpage_verified | 0.96 | What's new - Coda |

**来源质量说明**：三个来源均为 `webpage_verified`，来源级置信度 0.96，但**事实级置信度为 0.64**。本次证据中**无** `web_search_result` 或 `llm_public_knowledge` 类型来源，但事实置信度低于 0.75 阈值，故功能对比与任何赢家判断均不构成强结论。
