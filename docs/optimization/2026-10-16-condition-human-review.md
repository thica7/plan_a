# 前提归属与引用绑定：8 道已确认的人审边界

这批新资料覆盖 Miro、Airtable、Trello、Zoom，共 6 道可回答、1 道资料不足、1 道需澄清。它与已有题集分开；题目和候选答案已经曝光，不能称作盲测。用户已对 1–8 项回复“确认”，当前状态均为 `reviewed`，审核人为 `project_user`，审核记录时间为 `2026-10-16T01:50:40Z`（收到确认后的记录时间，不冒充客户端发送时间）。这只确认参考结论，不代表真实报告的前提或引用审核通过。

确认依据及范围保存在 [人工审核记录](../../eval/product-condition-review-v1-review.json)。审核前候选按原字节[归档](../../eval/archive/product-condition-review-v1-candidate/cases.jsonl)，旧模型结果仍对应该候选版本，不追溯改成正式验收。

| 编号／结果 | 问题 | 已认可结论 | 不可推断边界 | 官方依据 |
| --- | --- | --- | --- | --- |
| 1／可回答 | Free 套餐通过公开链接给 Visitor 查看，每周复盘；能改成编辑或评论吗？ | 不能；Visitor 编辑／评论限付费及 Education 套餐。 | 复盘频率不是条件；不能扩展为所有访问都需付费，或升级后自动授权。 | [Miro：Collaboration with Visitors](https://help.miro.com/hc/en-us/articles/360012524559-Collaboration-with-Visitors) |
| 2／可回答 | Guest 直接获邀 A、每周复盘；能免登录看 A 并访问未获邀的 B 吗？ | 不能；Guest 需登录，范围限直接获邀看板。 | 同团队、每周复盘不授予其他看板访问权，也不会自动变成 Member。 | [Miro：Collaboration with Guests](https://help.miro.com/hc/en-us/articles/360021415119-Collaboration-with-Guests) |
| 3／可回答 | 用户已是该 Trello 看板的 Observer；预算审批卡片有截止日期，能移动或编辑吗？ | 不能；禁止操作归属于 Observer 角色。 | 用途、截止日期不改变权限；未给出套餐、计费、评论或投票开关证据。 | [Trello：Add an observer to a board](https://support.atlassian.com/trello/docs/adding-observers-to-boards/) |
| 4／可回答 | 同一 base 内 A、B 均已发布；保留 base 访问权，只发 A 邀请，能自动收窄为只看 A 吗？ | 不能；已有权限不因只邀 A 自动收窄，对已发布 interface 仍按原 base 权限访问。 | 不能推断未发布 interface 可见、能够编辑或所有记录无条件可见；供应商用途不改变权限。 | [Airtable：Managing and sharing Airtable interfaces](https://support.airtable.com/articles/4255096925-managing-and-sharing-airtable-interfaces) |
| 5／可回答 | 同一 workspace 内，workspace 为较高的 Creator、base 为较低的 Editor，权限如何取值？ | 按两层较高值，题设为 Creator。 | 活动排期用途不是条件；不能据此保证所有具体操作都成功或授予其他 workspace 访问权。 | [Airtable：Airtable permissions overview](https://support.airtable.com/articles/3994336578-airtable-permissions-overview) |
| 6／可回答 | Zoom 主持人许可小林本地录制，小林在分组 A；会同时录下 B 吗？ | 不会；许可针对具体参会者，范围限录制者所在房间。 | 获准录制不等于录制所有房间；不能混用云录制规则，训练营用途不是条件。 | [Zoom：Managing meeting breakout rooms](https://support.zoom.com/hc/pb/article?id=zm_kb&sysparm_article=KB0062540) |
| 7／资料不足 | 仅凭电脑录制资料，能报 2026-10-16 中国最低付费套餐的含税月费吗？ | 不能报价；缺少当前、地区、周期、税费相符的价格证据。 | 免费及付费订阅者均能用某功能，不等于最低付费套餐为零或所有录制免费。 | [Zoom：Enabling or disabling computer recording](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0063640) |
| 8／需澄清 | Miro 外部协作者不想注册，未说明角色和分享方式，能直接访问吗？ | 先确认是否是 Visitor，以及该看板是否为公共看板。 | 片段只支持 Visitor 无账号访问公共看板；不能概括全部外部角色、私有看板或编辑权限。 | [Miro：Visitors, guests and members](https://help.miro.com/hc/en-us/articles/7045408248594-Visitors-guests-and-members) |

## 来源核验与使用边界

官方页面已逐页打开核验，核验时间为 `2026-10-15T18:55:38Z`（北京时间 2026-10-16）。每题只保留一条官方连续原文中的完整句或完整原文行，详见 [已人审 JSONL](../../eval/product-condition-review-v1.jsonl) 的 `sources[].excerpt`；本审核单不重复英文节选。8 个页面各只用于一题，按空白分词分别为 **22、17、25、10、23、23、10、17** 个英文词，同一页面累计均不超过 25 词。

审核前候选 SHA256 为 `791d13eaae9c32936ca9416eff2573f3fb52f9e3d54400c669692261e839332a`；当前已人审 JSONL SHA256 为 `7ebbf481a35c2b7216c1f81000661ed2980795fc4e3e5006be589d1154debd4d`。本次仅更新 `review_status`、`reviewed_by`、`reviewed_at`，问题、参考答案、条件、禁止推断及全部来源逐项未变，模型允许输入也保持一致。已校验 8 行 JSON、编号唯一、6／1／1 结果分布、来源 ID 和节选词数上限。

第 1 题采用官方操作步骤的完整原文行；第 5 题采用官方权限检查条目的完整原文行。其余均为完整句，未补写标题式摘要冒充原文。题设中的复盘、预算审批、供应商用途、活动排期、训练营，以及既有角色／权限，是问题输入；不混入官方原文。参考答案、所需条件和禁止推断是中文编辑判断，现已获项目用户确认；不是额外的官方原文。

Zoom 云录制的官方完整原句超过 25 英文词，因此本批第 6 题缩小为本地录制授权和房间范围。不能将第 6 题当作云录制验收。第 8 题也不补写其他角色的登录规则，只检查缺失条件时是否先澄清。

本批固定的是短节选输入，不是整页采集快照；不包含合成采集、伪造抓取或付费模型输出。确认后 formal 模式的参考数据门禁已具备条件；仍须将机械引用检查与报告语义人审分开。先前真实调用发生在人审前，维持候选诊断记录。本次未新增模型调用，报告交付与语义引用仍未验收。
