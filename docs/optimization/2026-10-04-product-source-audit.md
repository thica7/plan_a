# 产品调研官方证据补核记录

> 后续状态：用户已审核这五条范围，另建 reviewed-v2 资料；Figma两种周期开关也已实际核实。见[人审验收续记](2026-10-04-reviewed-facts-acceptance.md)。下文保留当时的AI补核记录，原候选标签没有改写。

核查日：2026-10-04。对应原候选 008 / 023 / 026 / 028 / 030。

这是 AI 对官方来源的补充检查，不是人工审核，也不是检索或答案质量验收。原问题、原 corpus 和标签均不修改；reviewed_by / reviewed_at 未登记，人工审核数仍为 0。此记录可用于下一步资料补全与人审，不能作为已审核 gold。

已重新读取下述官方页面。核查日期不等于来源发布日期或更新时间；页面未明确提供的日期保持未知。动态页面的 HTML 文本可访问不代表价格开关、地区税费或登录后配置已验证。

## 008：Pixel 8 更新期限

- [Google 更新政策](https://support.google.com/pixelphone/answer/4457705?hl=en)：支持期限从设备在美国 Google Store 首次可购买时起算，覆盖系统和安全更新。短节选：`updates for 7 years`。
- [Google 上市月份表](https://support.google.com/pixelphone/answer/15738422)：Pixel 8 行的月份为 2023 年 10 月。短节选：`Pixel 8`、`October 2023`。
- **推算而非官方逐日截止日期：** 结合上述两页可推算支持期至 2030 年 10 月；该上市表只提供月份，不能据此声明精确截止日。旧评测也不能独立证明核查日的最新政策。
- 原固定节选没有完整起点，需补上市月份证据并将“官方期限”“月份推算”“具体日期未知”分开。候选结论建议：补证后可回答月份范围，精确日仍未确认；待人审。

## 023：Notion 月付与年付

- [Notion 计费说明](https://www.notion.com/help/billing)：两种计费周期的续费时间不同，年付总成本较低；收费按 workspace 的成员席位计，不等于任意用户都按同一总价。
- 短节选：`Yearly billing costs less.`。
- 这能支持周期与一般成本区别，不能给出任意地区、币种和套餐的当前金额。原问题若需要具体报价，仍应确认方案、币种、税费和价格页面的周期开关。
- 候选结论建议：计费周期规则已补核，金额完整性仍需补证。原 answer 标签仍为 candidate，不自动改 reviewed。

## 026：Figma 席位与套餐

- [Figma 价格页](https://www.figma.com/pricing/) 分开列示 Professional 套餐中的 `Full seat`、`Dev seat`、`Collab seat`，并有月付 / 年付选项。
- 本次文字抓取显示 USD 和金额，但未操作并验证两个周期的开关状态。页面文字顺序不足以证明某金额属于哪个计费选项；不把抓取数值登记为已核实报价。
- 资料结构应包含 plan、seat_type、billing_interval、currency、amount、tax_scope、verified_at；任何缺失字段都应保留未知，不能把一种席位价格套给所有用户。
- 候选结论建议：席位拆分可支持，完整价格矩阵尚未验证；待人审。

## 028：Figma Dev Mode 交付

- [Figma Dev Mode 官方指南](https://help.figma.com/hc/en-us/articles/15023124644247-Guide-to-Dev-Mode-in-Figma) 列出设计检查、生成代码查看、资产下载、版本差异比较与交付能力。
- 短节选：`Available on all paid plans`、`Requires a Full or a Dev seat`。
- 原候选仅记录付费套餐，缺少席位条件；应同时呈现资格限制，不能把高级交付能力解释为所有席位可用。
- “输出中文并保留出处”属于报告格式要求；不是产品消息留存能力，也不应参与事实检索。
- 候选结论建议：功能与资格可由当前页面支持，原节选需要补齐席位限制；待人审。

## 030：Slack 留存与历史可见

- [Slack 免费版功能限制](https://slack.com/help/articles/27204752526611-Feature-limitations-on-the-free-version-of-Slack) 说明免费版可见历史范围与一年以上数据删除机制。短节选：`most recent 90 days`。
- [Slack 留存设置说明（英语英国版）](https://slack.com/intl/en-gb/help/articles/203457187-Customise-data-retention-in-Slack) 补充：免费版可以选择 90 天或一年保留；付费默认随 workspace 生命周期保留，也可以设置自定义删除期限。权限和套餐会影响具体配置。
- 美国入口此次跳转到了日语官方版本，随后核查明确英语地区 URL；未把网页语言当产品市场授权。
- 原节选只说明历史可见范围，不足以完整回答套餐留存能力。需要分开记录 visibility_window、retention_policy、deletion_deadline、paid_default、override_scope。
- 候选结论建议：补充留存配置证据后，仍需明确免费设置、付费默认与覆盖条件；待人审。

## 待审核的具体范围

| 样本 | 本次补核支持 | 仍需确认 | 人审状态 |
| --- | --- | --- | --- |
| 008 | 期限起点及上市月份 | 是否接受截止月份推算，精确日未知 | 未审核 |
| 023 | 计费周期和一般年付差异 | 是否要求具体金额及地区 | 未审核 |
| 026 | 套餐与席位拆分 | 价格周期、税费与开关 | 未审核 |
| 028 | 交付能力及付费席位条件 | 原节选补齐后是否完整 | 未审核 |
| 030 | 可见范围、可选留存、付费默认 | 各配置及覆盖限制是否完整 | 未审核 |

本轮不会用上述补核内容为旧查询量身扩充检索词典。后续数据版本应有新内容 hash、短证据节选与真实审核记录，并保留旧固定 corpus 作为回放基线。
