# 用户评价整理到 SWOT 再到扩报告设计

## 背景

当前项目已经有 `review_site` 查询入口、`review` 技能、`survey_interview`
用户研究补充、手工用户研究材料导入、`UserPersonaModel`、writer 固定章节、
`ReportVersionRecord` 和 report quality 检查。它还没有把课题中提到的
`用户评价整理 -> SWOT 分析 -> 结构化报告输出` 做成一条一等数据链路。

主要证据：

- `backend/packages/skills/review.yaml` 定义了 review 采集技能，但默认
  ScenarioPack 没有把 review 作为必选或常规可选维度。
- `backend/packages/tools/review_site.py` 和
  `backend/packages/crawler/sources.py` 支持评价站点查询或 URL 展开，但没有
  形成评价主题聚合模型。
- `backend/packages/agents/survey/logic.py` 会把 persona/user/review/buying
  相关维度补成 survey/interview 方向性信号。
- `backend/packages/agents/writer/logic.py` 会写 wins、weaknesses、watchouts
  和用户研究证据章节，但没有 SWOT schema 或 SWOT 章节。
- 全仓库 `swot` 只有前端图文案命中，没有后端 schema、agent、quality gate
  或测试。

## 目标

把扩报告能力升级为明确的结构化分析链路：

`review/persona 采集 -> 用户评价主题整理 -> SWOT 结构化分析 -> 报告固定章节输出 -> quality gate 检查`

完成后，报告的核心内容应显著增加，不再主要依赖证据、QA、RAG gap 等支撑章节撑篇幅。

## 非目标

- 不做大规模前端重设计。
- 不接入新的付费评价 API。
- 不把低置信度用户评价当作官方事实证明。
- 不要求每次 run 都必须联网抓取真实评论；没有 review 维度或没有评价源时，报告必须明确列为证据缺口。

## 数据模型

新增 `ReviewThemeSummary`，用于表示每个竞品的用户评价整理结果：

- `competitor`: 竞品名称。
- `dimension`: 默认 `review`，也可由 `persona/user/customer/buyer` 触发。
- `praise_themes`: 好评主题列表，每项包含 `theme`、`evidence`、`source_ids`、`confidence`。
- `complaint_themes`: 差评或抱怨主题列表，结构同上。
- `adoption_blockers`: 采用阻力，例如 onboarding friction、switching cost。
- `switching_triggers`: 替换或迁移触发因素。
- `persona_segments`: 从评价或用户研究中提取的用户/买家群体。
- `sentiment_hint`: `positive`、`mixed`、`negative` 或 `unknown`。
- `source_ids`: 参与整理的原始来源 ID。
- `confidence`: 聚合后的整体置信度。

新增 `SWOTAnalysis`，用于表示每个竞品或整体对比的 SWOT：

- `competitor`: 单竞品 SWOT 时必填；整体 SWOT 可为空或使用 `overall`。
- `strengths`: 优势条目。
- `weaknesses`: 劣势条目。
- `opportunities`: 机会条目。
- `threats`: 威胁条目。
- 每个条目包含 `text`、`source_ids`、`confidence`、`evidence_gap`。

模型应放在现有 schema 边界内，优先扩展 `backend/packages/schema/models.py`，
让 `CompetitorKnowledge` 能挂载 review summary 和 SWOT summary。

## 数据流

1. Planner 和维度规范化

   - 保留现有核心维度 `pricing/feature/persona`。
   - 允许用户手动选择 `review`。
   - 当 topic 或 scenario 描述包含用户评价、口碑、评论、抱怨、好评、adoption、
     switching 等信号时，动态 scenario 可以推荐 `review`。
   - 直接修改默认 ScenarioPack 时应谨慎，优先把 `review` 加入相关包的
     optional dimensions。

2. Collector

   - `review` 维度继续使用现有 `review.yaml` 和 `search_review_site`。
   - 评价来源可以是 `review_site`、`webpage_verified`、`survey_response`、
     `interview_record`、`manual_note`、`manual_transcript`。
   - 采集阶段只负责来源和摘要，不在这里生成 SWOT。

3. Analyst

   - 在 `review/persona/user/customer/buyer` 维度下生成 `ReviewThemeSummary`。
   - 输入包括 raw sources、survey/interview bundles、manual user research。
   - 没有足够评价材料时，生成空 summary 并带 evidence gap，不伪造用户评价。
   - 对 persona 维度保留现有 `UserPersonaModel`，但同步把可用痛点、采用阻力、
     使用场景投影到 `ReviewThemeSummary`。

4. SWOT Builder

   - 新增独立 helper 或 analyst 子步骤，从以下结构合成 SWOT：
     `FeatureTree`、`PricingModel`、`UserPersonaModel`、`ReviewThemeSummary`、
     comparison matrix、QA gaps。
   - Strengths 主要来自高置信优势、好评主题、矩阵胜出维度。
   - Weaknesses 主要来自抱怨主题、证据不足、矩阵落后维度。
   - Opportunities 主要来自用户未满足需求、竞品弱点、迁移触发因素。
   - Threats 主要来自相邻工作流、强竞品优势、切换成本、采购风险。
   - 每条 SWOT 必须带 source_ids。没有 source_ids 时只能作为 evidence gap，
     不可作为强结论。

5. Writer

   - 新增核心章节 `用户评价整理`，位置在 `竞争发现` 之后或 `竞品深挖` 之前。
   - 新增核心章节 `SWOT 分析`，位置在 `竞品深挖` 之后或 layer-specific section 之前。
   - `决策摘要`、`竞争发现`、`竞品深挖` 应引用 review summary 和 SWOT 的要点。
   - `用户研究证据` 仍保留为支撑章节，用于解释 survey/interview/manual note
     的证据性质。

6. Quality Gate

   - 当 run 维度包含 `review/persona/user/customer/buyer/feedback/adoption/switching`
     时，报告必须有 `用户评价整理` 或英文等价 heading。
   - 报告必须有 `SWOT 分析` 或英文等价 heading。
   - SWOT 章节中至少要有 strengths、weaknesses、opportunities、threats 四类标签。
   - SWOT 结论如果缺少引用，quality gate 应降分或生成 blocker。
   - 缺评价来源时，`下一步采集与验证计划` 必须列出评价站点、访谈或手工材料补充任务。

## 报告结构

推荐核心顺序：

1. 执行摘要
2. 决策摘要
3. 竞争发现
4. 用户评价整理
5. 竞品深挖
6. SWOT 分析
7. 横向决策矩阵
8. Layer-specific analysis
9. 证据与 QA 支撑
10. 来源质量与覆盖
11. 用户研究证据
12. RAG 缺口补全
13. 场景 QA 清单
14. 声明校验与证据风险
15. 下一步采集与验证计划
16. 证据附录

核心分析章节应该占主要篇幅。支撑章节保持完整但更简洁。

## 测试策略

新增或扩展单元测试：

- `review` 维度会触发 review 技能和 review/user-research 相关结构。
- analyst 能从 review/user research 来源生成 `ReviewThemeSummary`。
- SWOT builder 能从矩阵、persona、review summary 生成四象限，并保留 source_ids。
- writer fallback 在缺 LLM 或 LLM 输出过薄时补齐 `用户评价整理` 和 `SWOT 分析`。
- report quality 能识别中英文 heading，并在缺 SWOT 或缺评价整理时失败。
- 缺评价来源时，报告不能假装有用户评价，只能列 evidence gap 和下一步采集任务。

回归测试：

- 现有 pricing/feature/persona 默认 run 不应因为没有 review 源被误判为失败，
  除非它显式请求 review 或用户评价相关维度。
- 现有中文报告 heading、RAG gap fill、duplicate section gate 继续通过。

## 风险和处理

- 风险：低质量 review 搜索结果被写成强结论。
  处理：用户评价和 review_site 只支持方向性结论；强结论需要 verified 或多源支持。

- 风险：报告变长但核心仍空。
  处理：quality gate 检查 SWOT 四象限、评价主题、source_ids 和 evidence gap，而不仅检查长度。

- 风险：persona、review、user research 概念混乱。
  处理：persona 保留用户画像；review summary 负责评价主题；SWOT 负责战略结构。

- 风险：一次实现跨度太大。
  处理：先完成后端 schema、builder、writer、quality gate 和单元测试；前端只做必要展示适配。

## 验收标准

- 新 run 请求 `review` 或用户评价相关维度时，报告包含 `用户评价整理` 和 `SWOT 分析`。
- SWOT 四象限至少能在有证据的测试 fixture 中各生成一条带引用的条目。
- 没有评价来源时，报告明确写出评价证据缺口和下一步采集计划。
- report quality 对缺少用户评价整理或 SWOT 的报告给出可解释失败。
- 相关 pytest 单元测试通过。
