# 产品调研资料与人工审核说明

本文件对应 `eval/product-research-queries-draft.jsonl`、`eval/product-research-corpus.jsonl`、`eval/product-research-labels.jsonl`。用户已确认先做离线评测，可采集官方资料。

## 当前状态

| 项目 | 数量 / 状态 |
| --- | --- |
| 问题草案 | 50，全部保留原始问题 |
| 官方资料短节选 | 14，共同资料池 |
| AI 候选标签 | 13 |
| 人工审核标签 | 0 |
| 尚未标注问题 | 37 |
| 未公开发布 / 更新日期的资料 | 13，明确 `not_provided` |
| 正式质量验收 | 未就绪；入口拒绝没有人工标签的正式评测 |

本资料池是首批固定节选，尚未覆盖全部问题，尤其缺生活服务的城市与门店实测。`insufficient` 表达这个资料池不足以回答，不代表外部没有证据；`clarify` 不代表已经证明产品不存在。候选标签中的 `answer` 只覆盖列出的事实，审核时仍需判断是否完整回答原问题，并可改为资料不足或将问题拆分。

## 来源与范围

每个来源保存 HTTPS 地址、实际市场、完整产品型号、角色、抓取日期、源发布 / 更新日期及 UTF-8 文本的 SHA-256。未公布源日期时保存 `null` 与 `source_date_status=not_provided`，抓取日期不充当发布日期。

问题的 `as_of` 必须是有效的 `YYYY-MM-DD`，表示研究日。带具体时刻的输入会拒绝，避免默默丢掉时刻后放行未来证据。正式加载仅纳入 `purpose=evaluation` 的已审核标签；`reviewed` 总数与实际 `included` 数分别报告，调参标签不能充当验收样本。

节选仅保存少量原文。`proof.start/end` 是本地保存的 `text` 的字符位置，不是网页全文位置。多个节选之间以空行分隔，`excerpt_location` 说明所在章节；空行不表示原网页中这些句子连续相邻。SHA-256 检查保存文本是否改变，不能证明网页事实一定正确。

| 来源 | 本轮用途 |
| --- | --- |
| [Apple iPhone 15 中国规格](https://support.apple.com/zh-cn/111831) | 中国市场容量与接口的固定短节选 |
| [Apple 2023 年 iPhone 15 发布稿](https://www.apple.com.cn/newsroom/2023/09/apple-debuts-iphone-15-and-iphone-15-plus/) | 有明确发布日期的历史起售价；不能代替当前各容量报价 |
| [Apple iPhone 15 Pro 美国规格](https://support.apple.com/en-us/111829) | 不同型号与市场的干扰资料 |
| [Google Pixel 更新承诺](https://support.google.com/pixelphone/answer/4457705?hl=en) | 更新年限及美国首次上市口径 |
| [Google Pixel 硬件规格](https://support.google.com/pixelphone/answer/7158570?hl=en) | 运营商与地域限制，不能推断中国大陆可用性 |
| [DJI 德国规格](https://www.dji.com/de/mini-4-pro/specs) | `/cn/` 请求实际重定向德国；作为市场干扰资料，未保留完整测试条件 |
| [Notion 定价](https://www.notion.com/pricing) | 实际显示欧盟 EUR；未保存动态计费开关状态，不作为全球报价答案 |
| [Notion 计费说明](https://www.notion.com/help/billing) | 月付、年付的差异 |
| [Notion 访客说明](https://www.notion.com/help/add-members-admins-guests-and-groups) | 访客访问范围，不代替全部套餐权益表 |
| [Figma 定价与席位](https://www.figma.com/pricing/) | 席位分类；开关状态未核实，展示金额不当作已确认月付价 |
| [Figma Dev Mode](https://help.figma.com/hc/en-us/articles/15023124644247-Guide-to-Dev-Mode-in-Figma) | 交付功能及付费计划限制 |
| [Slack 免费版限制](https://slack.com/help/articles/27204752526611-Feature-limitations-on-the-free-version-of-Slack) | 可见历史与删除期限的区别 |
| [Shopify 美国费用说明](https://www.shopify.com/pricing) | 第三方支付费随套餐变化，未覆盖完整总成本 |
| [Shopify 通用账单说明](https://help.shopify.com/en/manual/your-account/manage-billing/billing-charges) | 套餐与应用周期费用；不充当特定国家报价 |

## 人工审核步骤

当前无需运行命令或配置服务。正式质量验收前，人工需要逐条核实原问题、市场 / 型号 / 日期、出处与原文、事实完整性，以及是否应澄清或拒答。不要只确认 quote 字符串匹配。

1. 首先审核 008、023、026、028、030 五条候选答案，尤其确认截止日期、计费周期、席位和付费限制是否完整。部分答案可能需要补充资料或改为 `insufficient`。
2. 审核 002、009、016、020、022、024、038、046 的资料不足 / 消歧理由，确认只针对这个固定资料池。
3. 对确认的标签记录真实审核者与审核时间，将 `review_status` 改为 `reviewed`；未确认的继续保持 `candidate`。不要用 AI 身份填入人工审核字段。
4. 问题 `purpose=evaluation` 是验收集合；未来调参或训练用 `tuning` 集合另行编制，不能根据验收失误改标准答案或扩展查询再宣称提高分数。

正式入口会排除候选标签并报告数量。候选诊断只能帮助定位检索问题，不代表真实语义模型达标；本轮也没有运行裁判模型或 Ragas。
