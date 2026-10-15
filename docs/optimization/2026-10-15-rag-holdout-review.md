# 离线真实候选集人工审核单（未审核）

版本：offline-holdout-v2-candidate-2。全部标签为 candidate / evaluation；尚无人审、没有第三方盲测资格。

固定研究日：2026-10-13；来源采集范围：2026-10-10T10:50:44.413482+00:00 至 2026-10-13T14:48:10.488413+00:00。2026-10-15 未联网复核。

审核者需逐条核对产品、角色、套餐、操作、市场、日期和否定条件；不能只看 URL 或摘要。原文字符坐标在 corpus.jsonl 的 provenance.excerpt_locations，期望答案是候选作者解读。

原文仅为短连续节选，多节选用空行连接；每段均可定位到原数据库 documents.text。未把作者摘要标成官方原文。来源产品/页面可能已在本项目采集与报告中曝光，本轮新题未用于查询实现调优。

冻结后不得因检索失败改题或标签。确有语义错误时另存版本并填写更正日志，不覆盖原始三份数据。审核通过也需另存审核记录及新版标签，不能倒填审核时间。

## 核对项目

- [ ] 原文、URL、采集时间、数据库原始记录与哈希相符。
- [ ] 问句与既有标签不是同事实改写；相似条件未被当成额外独立样本。
- [ ] 多来源问题要求的全部边界均被证明，单一命中不等于完整回答。
- [ ] 缺证只针对本冻结资料池；未将节选遗漏推断成官网未披露或产品不支持。
- [ ] 澄清控制所缺信息确实妨碍直接选择方案。
- [ ] 不把 10 月快照写成研究当日已重新核实。

## 逐条候选

### offline-holdout-v2-001

状态：未审核；事实组：`confluence.content-restriction-inheritance`；预期控制：`answer`。

问题：Confluence Cloud 限制了父页面的查看和编辑权限后，子页面是否会同时继承这两种限制？

候选边界：

- 父内容或文件夹的查看限制向下继承，无法查看父内容的人也无法查看其子内容。
- 编辑限制不会以同样方式自动继承；不能把父页面不可编辑直接等同于子页面不可编辑。

原文证据：

- `holdout-v2-confluence-restrictions`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/add-or-remove-page-restrictions/)；采集：2026-10-11T06:15:16.115135+00:00；节选坐标：0:385。

> If someone can’t view a parent content item or folder, they won’t be able to view any child content items under it. View restrictions added to the parent item or folder are inherited down to all content items nested under it.
> Editing doesn’t work this way. Even if someone is restricted from editing a parent item, they won’t automatically be restricted from editing the child content.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-002

状态：未审核；事实组：`confluence.custom-access-transition`；预期控制：`answer`。

问题：In a Confluence site transitioning to role-based access, does “Custom access” mean a reusable custom role has already been assigned? 请说明适用阶段。

候选边界：

- 该 FAQ 的过渡说明针对从逐项空间权限迁移到角色访问的网站，不直接适用于已经只使用角色访问的网站。
- Custom access 在过渡期保留既有逐项权限组合，表示尚未分配角色；它不同于具名、可复用的 custom role。

原文证据：

- `holdout-v2-confluence-roles`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/faq-role-based-access-in-confluence/)；采集：2026-10-13T14:48:10.488413+00:00；节选坐标：0:233。

> This page answers frequently asked questions for Confluence sites transitioning from individual space permissions to role-based access. The transition guidance on this page doesn’t apply to sites already using role-based access only.

- `holdout-v2-confluence-roles`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/faq-role-based-access-in-confluence/)；采集：2026-10-13T14:48:10.488413+00:00；节选坐标：235:523。

> Custom access means that a person, group, team, guest, app, or user class still has an existing combination of individual permissions instead of an assigned role.
> Custom access preserves existing permissions during the transition. It doesn’t mean that the access comes from a custom role.

- `holdout-v2-confluence-roles`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/faq-role-based-access-in-confluence/)；采集：2026-10-13T14:48:10.488413+00:00；节选坐标：525:559。

> |  | Custom access | Custom role |

- `holdout-v2-confluence-roles`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/faq-role-based-access-in-confluence/)；采集：2026-10-13T14:48:10.488413+00:00；节选坐标：561:717。

> | What it is | An existing combination of individual permissions that Confluence preserved during the move to roles | A named, reusable set of permissions |

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-003

状态：未审核；事实组：`confluence.free-migration-permissions`；预期控制：`answer`。

问题：一个付费 Confluence Cloud 站点降到 Free 后，已有权限会被全部重置吗？匿名访问及后续修改权限分别怎样？

候选边界：

- 已保存说明对付费降级到 Free 或 Data Center 迁移到 Free 的情况表示保留既有全局、空间与内容权限。
- 匿名访问被禁用；除非升级到付费计划，否则不能更改权限或重新启用匿名访问。

原文证据：

- `holdout-v2-confluence-plans`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/learn-about-confluence-cloud-plans/)；采集：2026-10-10T10:50:44.413482+00:00；节选坐标：0:358。

> If you migrate from Confluence Data Center to a free Confluence Cloud plan — or if you move from a paid Confluence Cloud plan to Confluence Free — your existing global, space, and content permissions will be retained, but anonymous access will be disabled. You won’t be able to change permissions or enable anonymous access unless you upgrade to a paid plan.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-004

状态：未审核；事实组：`confluence.plan-change-trial`；预期控制：`answer`。

问题：For an existing paid Confluence Cloud subscription, how long is a plan-change trial on monthly versus annual billing, and does Premium SLA compensation apply during the trial?

候选边界：

- 月付用户的换计划试用覆盖当前账期剩余时间及下一个完整账期；年付用户从开始试用起为 30 天。
- 试用可用新计划功能，但 Premium/Enterprise 的 SLA 赔偿要到试用结束后才开始适用。

原文证据：

- `holdout-v2-confluence-plans`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/learn-about-confluence-cloud-plans/)；采集：2026-10-10T10:50:44.413482+00:00；节选坐标：360:570。

> If you're on a monthly paid subscription, the trial will last for the remainder of your current and next full billing cycle. Cancel any time during the trial period if you decide you don't want to change plans.

- `holdout-v2-confluence-plans`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/learn-about-confluence-cloud-plans/)；采集：2026-10-10T10:50:44.413482+00:00；节选坐标：572:684。

> If you’re on an annual paid subscription, you can try another plan for 30 days from the day you start the trial.

- `holdout-v2-confluence-plans`；[官方来源](https://support.atlassian.com/confluence-cloud/docs/learn-about-confluence-cloud-plans/)；采集：2026-10-10T10:50:44.413482+00:00；节选坐标：686:870。

> During a trial you can use all the features available on the new plan, but the SLA compensation available on the Premium and Enterprise plans won’t commence until your trial has ended.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-005

状态：未审核；事实组：`coda.editor-authoring-boundary`；预期控制：`answer`。

问题：Coda（现 Superhuman Docs）的 Editor 可以给现有表格加行和建按钮，这是否也意味着他能新建文档或增删页面？

候选边界：

- Editor 可以编辑已有页面、向表格加行并构建按钮。
- 角色能力表中 Editor 不能创建或删除文档，也不能增删页面与子页面；不能从文档内编辑能力推导创建能力。

原文证据：

- `holdout-v2-coda-roles`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors)；采集：2026-10-13T08:03:18.781486+00:00；节选坐标：159:377。

> As an editor in Docs, you can collaborate in docs. Collaboration is not limited, so you can do things like edit existing pages, add rows to tables, construct buttons, and interact with all that a Doc Maker has created.

- `holdout-v2-coda-roles`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors)；采集：2026-10-13T08:03:18.781486+00:00；节选坐标：379:441。

> | Ability | Doc Maker (workspace admin) | Doc Maker | Editor |

- `holdout-v2-coda-roles`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors)；采集：2026-10-13T08:03:18.781486+00:00；节选坐标：443:527。

> | Create or delete docs | ✅ | ✅ | ❌ |
> | Add or delete pages & subpages | ✅ | ✅ | ❌ |

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-006

状态：未审核；事实组：`coda.cross-workspace-maker-tier`；预期控制：`answer`。

问题：A Coda Doc Maker in a Pro workspace is invited to a document in another workspace. Can they assume the same maker abilities in Free, Pro, Team and Enterprise workspaces?

候选边界：

- Doc Maker 能力跨工作区取决于两边的计划层级；在同级或更低层级的工作区文档中可进行 maker 操作。
- 因此 Pro 的 maker 身份不能无条件扩展至更高层级 Team/Enterprise 的文档；仍需先有文档协作邀请，不能推导对所有文档自动有访问权。

原文证据：

- `holdout-v2-coda-roles`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors)；采集：2026-10-13T08:03:18.781486+00:00；节选坐标：1099:1306。

> The answer depends on the plan type of your workspace and of the other workspace. If you’re a Doc Maker in one workspace, you can take Doc Maker actions on docs in other workspaces of the same tier or below.

- `holdout-v2-coda-roles`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors)；采集：2026-10-13T08:03:18.781486+00:00；节选坐标：529:798。

> For instance, let’s say you’re a Doc Maker in a Pro workspace, and you’re invited as a collaborator to a doc that lives in a Pro or Free workspace. You will be able to take Doc Maker actions on this doc - because you’re a Doc Maker in an equal or higher tier workspace.

- `holdout-v2-coda-roles`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors)；采集：2026-10-13T08:03:18.781486+00:00；节选坐标：800:1097。

> But let’s say you’re still a Doc Maker in a Pro workspace, and you’re invited as a collaborator to a doc that lives in a higher tier workspace (Team or Enterprise). In this case, you will not be able to take Doc Maker actions in this doc, because you’re a Doc Maker only in a lower tier workspace.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-007

状态：未审核；事实组：`coda.folder-doc-permission-floor`；预期控制：`answer`。

问题：在 Coda 的受支持文件夹权限场景中，某人有文件夹 Can edit，把其中单个文档设为 Can view 能降低他的权限吗？若只想共享一个文档，必须同时开放文件夹吗？请结合两份官方说明。

候选边界：

- 文件夹权限设置文档访问的下限；单个文档可以提高而不能降低由文件夹取得的权限。
- 仍有文件夹权限时不能只移除其中单个文档的访问；应先移除文件夹权限或移动文档。
- 可以直接邀请某人访问单个文档，不必同时给文件夹访问权。

原文证据：

- `holdout-v2-coda-folders`；[官方来源](https://help.superhuman.com/hc/en-us/articles/47804378033677-Share-folders-and-the-docs-within)；采集：2026-10-13T08:03:39.140881+00:00；节选坐标：0:214。

> A folder sets the floor. Whatever access someone has to a folder, they have at least that same level of access to every doc inside it. A doc's own permissions can raise someone above that floor, but never below it.

- `holdout-v2-coda-folders`；[官方来源](https://help.superhuman.com/hc/en-us/articles/47804378033677-Share-folders-and-the-docs-within)；采集：2026-10-13T08:03:39.140881+00:00；节选坐标：216:626。

> - You can't remove someone's doc access while they still have folder access. Since folder access sets the floor, the only way to take away their access to a doc inside is to remove their folder access first (or move the doc to a folder they can't access).
> - You can grant someone access to a doc without giving them any access to the folder it lives in. Just share the doc directly with them as described here.

- `holdout-v2-coda-share-doc`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210173956109-Share-your-doc)；采集：2026-10-11T13:49:28.284455+00:00；节选坐标：0:85。

> You can invite anyone to collaborate on your doc - you just need their email address.

- `holdout-v2-coda-share-doc`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210173956109-Share-your-doc)；采集：2026-10-11T13:49:28.284455+00:00；节选坐标：87:166。

> Anyone with access to a folder will also have access to all docs in the folder.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-008

状态：未审核；事实组：`coda.sharing-toggle-full-access-exception`；预期控制：`answer`。

问题：Coda 的 “Allow anyone who can edit to change permissions and share” 关掉之后，Can edit 和 Full access 用户是否都不能再改共享权限？

候选边界：

- 关闭该开关可阻止普通编辑者修改访问权限和共享文档。
- Full access 是明确例外：即便开关关闭仍能修改权限并共享。

原文证据：

- `holdout-v2-coda-share-doc`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210173956109-Share-your-doc)；采集：2026-10-11T13:49:28.284455+00:00；节选坐标：168:563。

> - Allow anyone who can edit to change permissions and share. This setting allows any people with edit access to your doc to also have control over sharing that doc. If you’d like to prevent others from modifying the access to your doc, toggle this setting off. Note that anyone with the Full access permission will still be able to change permissions and share, even with this toggle set to off.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-009

状态：未审核；事实组：`nuclino.public-item-sharing`；预期控制：`answer`。

问题：Nuclino public item links: can a person without an account edit the item, and what can prevent a full-access member from enabling public sharing? 用中文保留条件。

候选边界：

- 公开 item 可分享给团队、工作区以外或没有 Nuclino 账号的人；拿到链接者可查看而不能编辑。
- 开启 item 分享要求工作区 Full access，团队 owner/admin 还可通过高级安全控制禁用公开分享。

原文证据：

- `holdout-v2-nuclino-share-item`；[官方来源](https://help.nuclino.com/0f8a5a5b-share-an-item)；采集：2026-10-13T14:48:06.994961+00:00；节选坐标：0:174。

> 🔐 Only workspace members with full access can share items. Team owners and admins can disable public item sharing using advanced security controls.
> ⭐️ Available on all plans.

- `holdout-v2-nuclino-share-item`；[官方来源](https://help.nuclino.com/0f8a5a5b-share-an-item)；采集：2026-10-13T14:48:06.994961+00:00；节选坐标：176:285。

> You can share items with users who are not part of your team, workspace, or who don't have a Nuclino account.

- `holdout-v2-nuclino-share-item`；[官方来源](https://help.nuclino.com/0f8a5a5b-share-an-item)；采集：2026-10-13T14:48:06.994961+00:00；节选坐标：287:440。

> - Send the link to anybody you'd like to share the item with. People with access to the link will be able to view the item without being able to edit it.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-010

状态：未审核；事实组：`nuclino.default-access-guest-exception`；预期控制：`answer`。

问题：Nuclino 修改新成员的 workspace default access 有哪些套餐和角色条件？被设为 Full access 的 guest 是否因此也能修改？请合看功能页与角色表。

候选边界：

- 修改默认访问级别要求付费计划及工作区 Full access；该默认值决定新工作区成员的默认角色，可选 Full access、Comment-only、Read-only。
- 角色表对修改工作区默认访问明确排除 guest，因此不能仅凭 guest 拥有 Full access 就认定其能修改。

原文证据：

- `holdout-v2-nuclino-default-access`；[官方来源](https://help.nuclino.com/2cd918e0-change-the-workspace-access-setting)；采集：2026-10-13T10:49:09.014440+00:00；节选坐标：0:120。

> 🔐 Only workspace members with full access can change the workspace default access level.
> ⭐️ Available on the paid plans.

- `holdout-v2-nuclino-default-access`；[官方来源](https://help.nuclino.com/2cd918e0-change-the-workspace-access-setting)；采集：2026-10-13T10:49:09.014440+00:00；节选坐标：122:418。

> The workspace default access setting allows you to control what role new workspace members have by default. There are three settings available:
> - Full access: Members can read and edit by default.
> - Comment-only: Members can only comment by default.
> - Read-only: Members can only read by default.

- `holdout-v2-nuclino-roles`；[官方来源](https://help.nuclino.com/fed9f070-roles-and-permissions)；采集：2026-10-13T10:49:06.808832+00:00；节选坐标：124:169。

> |  | Full access | Comment-only | Read-only |

- `holdout-v2-nuclino-roles`；[官方来源](https://help.nuclino.com/fed9f070-roles-and-permissions)；采集：2026-10-13T10:49:06.808832+00:00；节选坐标：171:236。

> | Change workspace default access | ✅ (except guests) | ✖️ | ✖️ |

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-011

状态：未审核；事实组：`nuclino.comment-feature-vs-role-plan`；预期控制：`answer`。

问题：Nuclino 的评论功能页写着 Available on all plans，是否说明 Free 团队也一定可以分配 Comment-only 角色？Read-only 可以评论吗？

候选边界：

- 评论能力本身在所有计划可用，但能评论的工作区角色为 Full access 或 Comment-only。
- Comment-only 与 Read-only 工作区角色的可分配性属于付费计划；不能把功能覆盖所有计划解读成所有角色都在 Free 可用。
- 角色表中的 Read-only 不具备查看、添加、解决、删除评论这一项能力。

原文证据：

- `holdout-v2-nuclino-comments`；[官方来源](https://help.nuclino.com/a6f815d8-comment-on-content)；采集：2026-10-13T10:49:33.319047+00:00；节选坐标：0:114。

> 🔐 Only workspace members with full access or comment-only roles can comment on content.
> ⭐️ Available on all plans.

- `holdout-v2-nuclino-roles`；[官方来源](https://help.nuclino.com/fed9f070-roles-and-permissions)；采集：2026-10-13T10:49:06.808832+00:00；节选坐标：0:122。

> ⭐️ The team member and guest roles, as well as comment-only and read-only workspace roles are available on the paid plans.

- `holdout-v2-nuclino-roles`；[官方来源](https://help.nuclino.com/fed9f070-roles-and-permissions)；采集：2026-10-13T10:49:06.808832+00:00；节选坐标：124:169。

> |  | Full access | Comment-only | Read-only |

- `holdout-v2-nuclino-roles`；[官方来源](https://help.nuclino.com/fed9f070-roles-and-permissions)；采集：2026-10-13T10:49:06.808832+00:00；节选坐标：238:290。

> | View, add, resolve, delete comments | ✅ | ✅ | ✖️ |

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-012

状态：未审核；事实组：`nuclino.collection-item-view-model`；预期控制：`answer`。

问题：In Nuclino, are collections always table columns? Explain how collections and items are represented in board, table and graph views.

候选边界：

- Board 中 collections 表示流程阶段，items 作为可跨 collection 拖动的卡片或任务。
- Table 中 items 为行，collections 和 fields 为列；Graph 用于查看 collections、items 及其关系，不能把表格列的表示推广至所有视图。

原文证据：

- `holdout-v2-nuclino-getting-started`；[官方来源](https://help.nuclino.com/d81c3c05-getting-started)；采集：2026-10-12T14:19:08.106796+00:00；节选坐标：0:509。

> In the board view, collections visualize the stages of your workflow, while items act as cards or tasks. They can be dragged and dropped from collection to collection, allowing you to easily track your progress.
> In the table view, items are the rows of your table, and collections and fields are the columns which allow you to label and contextualize your docs and tasks.
> In the graph view, you can get a quick visual overview of all the collections and items in a workspace and how they relate to each other.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-013

状态：未审核；事实组：`confluence.final-bill-evidence-gap`；预期控制：`insufficient`。

问题：请只据这份离线证据，算出 2026-10-13 美国 37 人 Confluence Premium 年付的最终含税总账单，给出确定美元金额。

候选边界：

- 该冻结资料池没有 37 人、美国、Premium 年付的单价/阶梯、税率与最终账单证据，应返回缺证并列出所需报价条件；不能用试用规则或权限说明计算金额。

原文证据：

无 gold 引文；审核重点为资料池边界或需澄清的信息，不能将无引文视为已证明外部世界不存在该信息。

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-014

状态：未审核；事实组：`coda.final-bill-evidence-gap`；预期控制：`insufficient`。

问题：Coda 团队有 2 个 Doc Maker 和 18 个 Editor。仅凭本资料池，能给出截至 2026-10-13 的确定美元含税月账单吗？

候选边界：

- 保存原文区分 Doc Maker（含 workspace admin）付费许可证与免费 Editor，但缺套餐、周期对应单价、税费和最终报价，不能给出确定美元含税月总额。

原文证据：

- `holdout-v2-coda-roles`；[官方来源](https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors)；采集：2026-10-13T08:03:18.781486+00:00；节选坐标：0:157。

> A workspace can have an unlimited number of members in any role but both Doc Maker (Workspace admin) and Doc Maker are paid licenses, while editors are free.

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-015

状态：未审核；事实组：`coda.ambiguous-editor-identity`；预期控制：`clarify`。

问题：Coda 里这个“编辑”要不要付费？

候选边界：

- 先澄清“编辑”指 Editor 成员角色、Doc Maker，还是仅有某个文档 Can edit 权限的人，以及对应工作区；不能把这几个口径混用直接判断该人的账单。

原文证据：

无 gold 引文；审核重点为资料池边界或需澄清的信息，不能将无引文视为已证明外部世界不存在该信息。

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

### offline-holdout-v2-016

状态：未审核；事实组：`nuclino.ambiguous-external-collaboration`；预期控制：`clarify`。

问题：Nuclino 想让一个外包参与这份内容，但不让他看到别的东西，该怎么开权限？

候选边界：

- 先确认参与是只读、评论还是编辑，目标为单个 item 还是工作区，以及该外包是否为团队/工作区成员和可用计划；不能直接用公开只读链接回答所有协作需求。

原文证据：

无 gold 引文；审核重点为资料池边界或需澄清的信息，不能将无引文视为已证明外部世界不存在该信息。

审核结论：□通过　□需更正　□排除

审核人：________　审核时间：________　原因：________

## 冻结 SHA-256

- `corpus.jsonl`：`c632c1caf32f9792660a23edd68a44eb111e279be7d0d94e4c28332b8950f162`
- `queries.jsonl`：`6efa15daaf069423ebbb67844c2fd182f08df963549d689a63aae7ed8c4d4e73`
- `labels.jsonl`：`28e2d62814572fc89b0c64516de02dd81f2b11854c468530dfdc2c8ea270d44d`

## 更正日志

candidate-2：在任何检索运行之前的证据完整性检查中，为两处 proof 补齐原始表头/层级条件例句；题干与 expected_facts 未变。candidate-1 三份数据和哈希保存在 versions/candidate-1。此次修正不依据检索结果。
