# 新产品答案边界人审单（用户已确认）

项目用户已回复“1–6 均认可，按这些边界审核”，六题已转为 **human-reviewed**。这次确认覆盖参考答案边界、问题和来源；生成正文质量、答案覆盖、引用语义及报告交付仍需另行验收。

Basecamp 与 GitBook 在基线 `99302fa` 的 eval、docs、backend/tests 中未出现；此轮采集和开发已经暴露这批材料，后续只能称独立新产品样本，不能继续称盲测。Miro 属于已知回归样本，不计入本批。

六份正文均经 robots 检查后，通过生产 `fetch_evidence_page → capture_candidate` 取得 HTTP 200 与 `full_source`。官方身份只在精确 URL 上登记；登记审核人为 `codex_operator`，不冒充用户人审。公开文件只保留短节选、元数据与哈希，完整正文留在 Git 忽略目录。GitBook 旧路径迁移、robots 302 时停止以及后续规范路径重试均有记录。

## answer-holdout-v1-001 · Basecamp

**问题：** 我们在 Basecamp 5 里把客户小陈加入了项目 A，并已登录。项目每周用于交付复盘，内部消息 X 仍未设为客户可见。小陈现在是否能看到 X？

**已确认参考边界：** 不能。题设是 Client，项目成员身份和已登录并不会使仍私有的 X 自动对客户可见；内容要先明确设为客户可见。每周复盘只是用途背景，不能替代内容可见性条件，也不能推断 Client 因此拥有项目管理权限。

**官方来源：** [What Clients can see and do - Basecamp 5 Help](https://5.basecamp-help.com/article/1082-what-clients-can-see-and-do)

## answer-holdout-v1-002 · Basecamp

**问题：** 一位 Basecamp 5 Client 已加入项目 A，未加入同一账号的项目 B。A、B 都用于同一个客户的季度交付。仅凭他在 A 中的邀请，他也会看到 B 吗？

**已确认参考边界：** 不会。Client 在 A 中的邀请不等于也被加入 B；项目范围取决于被加入哪些项目。同一账号、同一客户和季度交付用途都不能补上 B 的加入条件；也不能据此推断 A 的所有内容已对该 Client 可见。

**官方来源：** [Inviting People - Basecamp 5 Help](https://5.basecamp-help.com/article/1060-inviting-people)

## answer-holdout-v1-003 · Basecamp

**问题：** Basecamp 5 账号里一位长期合作的外部伙伴被标为 Outside Collaborator。他是否一定不能担任 Admin？我们尚未说明账号创建时间。

**已确认参考边界：** 应先确认该 Basecamp 账号的创建时间。官方权限说明为 2022 年 9 月 14 日之前创建的账号保留 Outside Collaborator 的权限例外，因此在创建时间缺失时不能统一断言一定不能担任 Admin。长期合作只是背景，不能替代账号创建时间，也不能自动将他视为公司成员或管理员。

**官方来源：** [Permissions - Basecamp 5 Help](https://5.basecamp-help.com/article/1171-permissions)

## answer-holdout-v1-004 · GitBook

**问题：** 我们的 GitBook 站点当前是 Essential 套餐，每周发布更新说明。因为它已经能公开发布文档，现在就能使用 AI Assistant Chat 侧栏吗？

**已确认参考边界：** 不能。来源明确把 AI Assistant Chat 排除在 Free 和 Essential 之外；能够公开发布文档以及每周发布说明都不替代 Chat 的套餐资格。资料还区分 Ultimate 的相关问题信用额度和 Enterprise 的包含关系，不能把该限制扩大为 Essential 的所有 AI 功能均不可用，也不能保证升级后无需其他配置或额度。

**官方来源：** [GitBook pricing & plans | GitBook](https://www.gitbook.com/pricing)

## answer-holdout-v1-005 · GitBook

**问题：** GitBook 文档站点已经配置 Authenticated access 和授权后端。合作方小林有现成登录凭证，但该后端没有授权他访问；站点用于培训材料。他只要拿到链接并登录，就一定能看吗？

**已确认参考边界：** 不能。题设的 Authenticated access 要求访问者登录，并且由授权后端允许访问；仅持有凭证、拿到链接或登录都不能替代后端授权。培训材料只是用途背景。该结论限定于已配置 Authenticated access 的站点，不能推广为所有公开 GitBook 文档都必须登录，也不能推断访问权等于编辑权。

**官方来源：** [The complete guide to creating and publishing documentation in GitBook [updated for 2026] | Guides | GitBook Documentation](https://gitbook.com/docs/guides/editing-and-publishing-documentation/complete-guide-to-publishing-docs-gitbook)

## answer-holdout-v1-006 · GitBook

**问题：** 我们在为 GitBook 做采购预算。仅依据所给合并规则说明，截至 2026 年 10 月 16 日，Enterprise 套餐在中国的含税人民币月费准确是多少？

**已确认参考边界：** 资料不足，不能给出准确金额。合并规则说明没有与该日期、中国地区、人民币、月付和含税口径相符的 Enterprise 报价；不能将合并能力或规则要求换算为价格，也不能猜测定制套餐的最低金额、税率或汇率。

**官方来源：** [Merge rules | GitBook Documentation](https://gitbook.com/docs/collaborate/merge-rules)

## 审核回执

用户原话：“1–6 均认可，按这些边界审核”。审核来源：`request_user_input_async:call_f4b725730c524d64b6ae1f19243b51e6`。记录时间：`2026-10-16T04:43:15Z`（收到确认时记录，未提供原始客户端发送时间）。六题当前为 `review_status=reviewed`、`reviewed_by=project_user`；仅修改这三项审核元数据，题目、来源和 gold 事实内容保持逐字段一致。

人审后数据：`eval/product-answer-holdout-v1.jsonl`。运行时文件：`eval/product-answer-holdout-v1-runtime.json`，仅含问题和来源身份；参考答案、预期结果、必要条件与禁止推断不进入生产提示。两组各 3 题，问题合计长度为 236 和 261 字，不会截断成不完整问题。

原候选 SHA256：`2ef6385e29d87f75a6617305a71caf35e47a38a546cd5053cbb75bae783a7b9e`。采集正文、robots 和完整尝试记录：`data/artifacts/answer-condition-2026-10-16/holdout/`。本单未运行模型，也未进行任何报告语义验收。

人审后数据 SHA256：`1925b319a40380486fede510fe704c6507c12029ec36689c440b0987723e6ea9`。原 candidate 字节归档：`eval/product-answer-holdout-v1-candidate.jsonl`，原 SHA256 保持 `2ef6385e29d87f75a6617305a71caf35e47a38a546cd5053cbb75bae783a7b9e`。审核记录：`eval/product-answer-holdout-v1-review.json`。本次更新未调用模型，未验收生成正文。
