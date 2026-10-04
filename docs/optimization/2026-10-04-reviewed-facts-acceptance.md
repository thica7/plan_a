# 五条产品事实的人审验收与结构化资料

## 验收范围

用户于2026-10-04明确审核008、023、026、028、030，并授权下载开源模型，仅在本机运行。本轮建立独立 `reviewed-v2` 资料版本，供隔离检索评测使用；原候选资料和标签保持原始哈希。没有迁移真实知识库、修改既有报告或自动审核新问题。

新增7条官方资料、保留9条不同页面的旧资料作为干扰项，共16条。另5条旧节选与新增资料具有相同官方URL、产品、市场与角色，会在生产入库规则中归为同一文档；因此不在新版本同时索引为两个active文档，替换关系记录在manifest。原14条旧资料仍完整保留在原corpus。五个问题的文本不变，五条标签标记 `reviewed_by=project_user`，保留本轮人审来源和时间。标签的proof坐标针对保存的节选/摘要，不宣称与网页全文坐标相同。这五题已曝光，不能作为盲测或泛化证明。

## 事实与边界

| 编号 | 结构化结果 | 使用限制与官方证据 |
| --- | --- | --- |
| 008 | 7年支持承诺；由2023-10开售月份推算2030-10；`has_exact_day=false` | 月份推算与原政策分开，不虚构截止日。[更新政策](https://support.google.com/pixelphone/answer/4457705?hl=en)、[开售月份](https://support.google.com/pixelphone/answer/15738422?hl=en)。 |
| 023 | 月付/年付、自动续订、年付相对成本、席位计费；金额矩阵为空 | [计费帮助](https://www.notion.com/help/billing)支持机制，不支持具体套餐金额。金额问题的证据状态为 `missing_entity_price`；结构化记录本身不等于生产workflow已实现自动价格拦截。 |
| 026 | Professional / Full 年付16、月付20；Dev12/15；Collab3/5，USD/席位/月 | 本轮在[官方价格页](https://www.figma.com/pricing/)分别切换Annual、Monthly核实。年付显示值是月均金额，不能当作年度总价；税费与客户最终账单未知。 |
| 028 | Professional/Organization/Enterprise 与 Full/Dev 席位双重前提 | [Dev Mode指南](https://help.figma.com/hc/en-us/articles/15023124644247-Guide-to-Dev-Mode-in-Figma)。限制针对完整Dev Mode能力，不能据此宣称免费查看者完全不能基础检查设计。 |
| 030 | 免费90天可见；留存可选1年滚动删除或90天删除；付费默认工作区生命周期 | [免费限制](https://slack.com/help/articles/27204752526611-Feature-limitations-on-the-free-version-of-Slack)、[留存配置](https://slack.com/intl/en-gb/help/articles/203457187-Customise-data-retention-in-Slack)。通用文档不证明某个免费工作区实际默认配置；付费仅能访问仍被保留的数据，另有自定义删除及Enterprise-sponsored Slack Connect例外。 |

## 数据文件与验证

- `eval/product-research-reviewed-v2-{corpus,queries,labels}.jsonl`：检索资料、原问题与本轮审核标签。
- `eval/product-research-reviewed-v2-facts.json`：五条结构化事实及未知项。
- `eval/product-research-reviewed-v2-manifest.json`：新旧资料哈希、审核范围及曝光说明。

`load_dataset(require_reviewed=True)` 已接受5条审核标签、检查proof文本/坐标、保存文本哈希、产品/市场匹配和as_of边界。16条资料中15条没有官方发布/更新时间，已明确记录 `source_date_unknown`；抓取时间不能替代发布或事实生效时间。

金额证据状态、税费未知和留存例外保存在检索metadata中。本轮检索评测不生成最终答案，因此尚不能验收报告是否遵守这些边界，也不能宣称生产价格自动拦截已经完成。

字段也保留来源映射：Pixel更新政策只挂期限/起点，截止月份推算同时引用政策和上市表；Slack可见性资料与留存配置资料各自只挂对应事实，避免把另一页的限制误归到当前引用。
