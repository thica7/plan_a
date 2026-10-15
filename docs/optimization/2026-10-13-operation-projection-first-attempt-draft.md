# 比较 Notion、Confluence、Coda（现 Superhuman Docs）、Nuclino 的文档协作能力。请固定这四家，分别核实阅读、评论、编辑、创建、分享、权限管理六种操作的角色、套餐、文档或工作区访问范围、分享及父级访问前提。相同操作才能对照，未知不等于不支持；发现缺口后定向采集官方文档。本例只验收能力比较，不研究价格；不得给采购赢家。输出极简中文分析。

## 执行摘要

本稿按产品与维度展示已审核的证据观察。证据不足以给出赢家或采购建议；采集报价不等于适用价格或完整账单。

## 竞争发现

### 同操作与条件对照

各格仅展示已审核的同操作观察；角色、套餐、分享或父级访问条件不同，不能视为能力相等。

| 操作 | Notion | Confluence | Coda | Nuclino |
| --- | --- | --- | --- | --- |
| 阅读 | 在 Notion 中，&#x27;Can view&#x27; 权限级别的人可以阅读页面上的内容，但无法评论、编辑或分享。；套餐未核实 [source:raw-source-a41315254e16772120b6] | 在 Confluence 中，Viewer 角色可以查看内容；该规则未注明适用套餐，且需满足 Confluence 管理员可为默认角色不支持的重复访问需求创建自定义角色这一前提。；套餐未核实 [source:raw-source-3cae2348b7b4e2333bc3] | 外部用户对文件夹内文档的读取权限取决于其被授予的级别：根据级别不同，他们可以编辑、评论或查看文件夹内的所有文档。；套餐未核实、角色未核实 [source:raw-source-7081f50e8908d1f4ba36] | Nuclino 的 read 操作：在 Full access、Comment-only、Read-only 三种角色下均可查看内容（View content 均为 ✅）；其中 Comment-only 与 Read-only 角色在付费套餐（paid plans）提供，Full access 的套餐条件未在捕获内容中说明。；套餐未核实 [source:raw-source-c74689c8b2b6337622ab] |
| 评论 | 在 Notion 中，你可以对页面的特定部分发表评论，以提出意见或提问。；套餐未核实、角色未核实 [source:raw-source-f519a063702b100008cd] | 在 Confluence 中，Viewer 角色可以查看和评论内容；该规则未注明适用套餐，且需满足 Confluence 管理员可为默认角色不支持的重复访问需求创建自定义角色这一前提。；套餐未核实 [source:raw-source-3cae2348b7b4e2333bc3] | 外部用户对文件夹内文档的评论权限取决于其被授予的级别：根据级别不同，他们可以编辑、评论或查看文件夹内的所有文档。；套餐未核实、角色未核实 [source:raw-source-7081f50e8908d1f4ba36] | 未取得已审核观察，需定向补证 |
| 编辑 | 在 Notion 中，你可以与不限数量的人同时编辑同一页面。；套餐未核实、角色未核实 [source:raw-source-0327738cc6fc5b196547] | Confluence 允许你邀请他人编辑、留下反馈并分享链接，使工作触达合适的受众。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-1f4d27ce28ed8cf6408f] | 在 Team/Business 或 Enterprise 套餐下，拥有 Can manage access 权限的用户可以邀请外部用户加入文件夹，但外部用户只能获得编辑、评论或查看权限，不能获得 manage access 权限。；套餐未核实、角色未核实 [source:raw-source-7081f50e8908d1f4ba36] | Nuclino 的 edit 操作：在工作区层面可决定哪些成员可以添加或编辑内容；comment-only 与 read-only 工作区角色在付费套餐（paid plans）提供，捕获内容未指明具体角色与套餐以外的条件。；套餐未核实、角色未核实 [source:raw-source-c74689c8b2b6337622ab] |
| 创建 | 在 Notion 中，&#x27;Can create&#x27; 权限级别仅存在于数据库页面，且在 Business 和 Enterprise 套餐中可用；该级别的人可以在数据库内创建新页面，但无法查看或编辑未被单独授予访问权限的现有页面。 [source:raw-source-a41315254e16772120b6] | 在 Confluence 中，创建页面或博客文章需要该空间的 Add content 权限；该规则未注明适用角色和套餐。；套餐未核实、角色未核实 [source:raw-source-1f4d27ce28ed8cf6408f] | 外部用户不能创建新文档、不能将文档移入或移出文件夹、不能删除文档，也不能邀请他人。；套餐未核实、角色未核实 [source:raw-source-7081f50e8908d1f4ba36] | 未取得已审核观察，需定向补证 |
| 分享 | 未取得已审核观察，需定向补证 | Confluence 允许你邀请他人编辑、留下反馈并分享链接，使工作触达合适的受众。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-1f4d27ce28ed8cf6408f] | 未取得已审核观察，需定向补证 | Nuclino 的 share 操作：可将 item 分享给不属于你的团队、工作区或没有 Nuclino 账号的用户；仅拥有 full access 的工作区成员可以分享 item，团队所有者和管理员可通过高级安全控制禁用公开 item 分享；该功能在所有套餐（all plans）提供。；角色未核实 [source:raw-source-bfd5ea3104e90ec11fb6] |
| 权限管理 | 在 Notion 中，对于每个你共享页面的个人、群组或团队空间，你可以分配不同的权限级别。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-a41315254e16772120b6] | 在 Confluence 中，你可以管理访问权限，例如在“Open”状态下将空间内任何人的权限从“Can edit”改为“Can view”；该规则未注明适用角色和套餐，且需满足先为内容项的常规访问添加限制、再添加个人或群组这一前提。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-dfb0525ca752f8f7e8de] | 在 Team/Business 或 Enterprise 套餐下，拥有 Can manage access 权限的用户可以邀请外部用户加入文件夹，但外部用户只能获得编辑、评论或查看权限，不能获得 manage access 权限。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-7081f50e8908d1f4ba36] | Nuclino 的 manage_access 操作：仅拥有 full access 的工作区成员可以更改工作区默认访问级别；该功能在付费套餐（paid plans）提供；默认访问设置包含 Comment-only（成员默认只能评论）与 Read-only（成员默认只能阅读）等选项。 [source:raw-source-a8193807fddd80a85094] |

### 功能

### Notion — 功能

- 在 Notion 中，&#x27;Can create&#x27; 权限级别仅存在于数据库页面，且在 Business 和 Enterprise 套餐中可用；该级别的人可以在数据库内创建新页面，但无法查看或编辑未被单独授予访问权限的现有页面。 [source:raw-source-a41315254e16772120b6]

- 在 Notion 中，对于每个你共享页面的个人、群组或团队空间，你可以分配不同的权限级别。 [source:raw-source-a41315254e16772120b6]

- 在 Notion 中，你可以对页面的特定部分发表评论，以提出意见或提问。 [source:raw-source-f519a063702b100008cd]

- 在 Notion 中，你可以与不限数量的人同时编辑同一页面。 [source:raw-source-0327738cc6fc5b196547]

- 在 Notion 中，&#x27;Can view&#x27; 权限级别的人可以阅读页面上的内容，但无法评论、编辑或分享。 [source:raw-source-a41315254e16772120b6]

- 本段待核验或缺口：已采资料超出本段上下文，未全部选入

### Confluence — 功能

- Confluence 允许你邀请他人编辑、留下反馈并分享链接，使工作触达合适的受众。 [source:raw-source-1f4d27ce28ed8cf6408f]

- 在 Confluence 中，Viewer 角色可以查看和评论内容；该规则未注明适用套餐，且需满足 Confluence 管理员可为默认角色不支持的重复访问需求创建自定义角色这一前提。 [source:raw-source-3cae2348b7b4e2333bc3]

- 在 Confluence 中，Viewer 角色可以查看内容；该规则未注明适用套餐，且需满足 Confluence 管理员可为默认角色不支持的重复访问需求创建自定义角色这一前提。 [source:raw-source-3cae2348b7b4e2333bc3]

- 在 Confluence 中，创建页面或博客文章需要该空间的 Add content 权限；该规则未注明适用角色和套餐。 [source:raw-source-1f4d27ce28ed8cf6408f]

- 在 Confluence 中，你可以管理访问权限，例如在“Open”状态下将空间内任何人的权限从“Can edit”改为“Can view”；该规则未注明适用角色和套餐，且需满足先为内容项的常规访问添加限制、再添加个人或群组这一前提。 [source:raw-source-dfb0525ca752f8f7e8de]

- 本段待核验或缺口：已采资料超出本段上下文，未全部选入、重复或偏离本次操作的观察未发表

### Coda — 功能

- 在 Team/Business 或 Enterprise 套餐下，拥有 Can manage access 权限的用户可以邀请外部用户加入文件夹，但外部用户只能获得编辑、评论或查看权限，不能获得 manage access 权限。 [source:raw-source-7081f50e8908d1f4ba36]

- 外部用户对文件夹内文档的读取权限取决于其被授予的级别：根据级别不同，他们可以编辑、评论或查看文件夹内的所有文档。 [source:raw-source-7081f50e8908d1f4ba36]

- 外部用户对文件夹内文档的评论权限取决于其被授予的级别：根据级别不同，他们可以编辑、评论或查看文件夹内的所有文档。 [source:raw-source-7081f50e8908d1f4ba36]

- 外部用户不能创建新文档、不能将文档移入或移出文件夹、不能删除文档，也不能邀请他人。 [source:raw-source-7081f50e8908d1f4ba36]

- 本段待核验或缺口：已采资料超出本段上下文，未全部选入、重复或偏离本次操作的观察未发表

### Nuclino — 功能

- Nuclino 的 read 操作：在 Full access、Comment-only、Read-only 三种角色下均可查看内容（View content 均为 ✅）；其中 Comment-only 与 Read-only 角色在付费套餐（paid plans）提供，Full access 的套餐条件未在捕获内容中说明。 [source:raw-source-c74689c8b2b6337622ab]

- Nuclino 的 edit 操作：在工作区层面可决定哪些成员可以添加或编辑内容；comment-only 与 read-only 工作区角色在付费套餐（paid plans）提供，捕获内容未指明具体角色与套餐以外的条件。 [source:raw-source-c74689c8b2b6337622ab]

- Nuclino 的 share 操作：可将 item 分享给不属于你的团队、工作区或没有 Nuclino 账号的用户；仅拥有 full access 的工作区成员可以分享 item，团队所有者和管理员可通过高级安全控制禁用公开 item 分享；该功能在所有套餐（all plans）提供。 [source:raw-source-bfd5ea3104e90ec11fb6]

- Nuclino 的 manage_access 操作：仅拥有 full access 的工作区成员可以更改工作区默认访问级别；该功能在付费套餐（paid plans）提供；默认访问设置包含 Comment-only（成员默认只能评论）与 Read-only（成员默认只能阅读）等选项。 [source:raw-source-a8193807fddd80a85094]

- 本段待核验或缺口：已采资料超出本段上下文，未全部选入、重复或偏离本次操作的观察未发表


## 产品机会与验证
- 待验证机会假设：探索与用户任务相关的产品改进，用户任务：共同维护产品文档和团队知识；验证动作：让目标用户完成同一任务并记录阻碍；成功信号：六种操作分别说明证据、角色、套餐、范围与待补条件。用户简报仅作为输入上下文，竞品差异与用户需求仍待验证。

## 置信度说明

已审核只表示绑定证据在本次模型审核中支持该观察，不代表人工验收或产品总体质量。未发布的主张保留在审核记录中。下一步：核验相同任务的同轴能力，并补齐报价条件及完整账单。

## 证据附录

- Notion：Collaborate with people in Notion | Notion Help – Notion Help Center [source:raw-source-0327738cc6fc5b196547]
- Notion：Sharing &amp; permissions settings in Notion | Notion Help – Notion Help Center [source:raw-source-a41315254e16772120b6]
- Notion：Comments, mentions &amp; reactions in Notion | Notion Help – Notion Help Center [source:raw-source-f519a063702b100008cd]
- Confluence：Create, update, and manage written content | Confluence Cloud | Atlassian Support [source:raw-source-1f4d27ce28ed8cf6408f]
- Confluence：FAQ: Role-based access in Confluence | Confluence Cloud | Atlassian Support [source:raw-source-3cae2348b7b4e2333bc3]
- Confluence：Change who can find content and what they can do with it | Confluence Cloud | Atlassian Support [source:raw-source-dfb0525ca752f8f7e8de]
- Coda：Share folders and the docs within – Superhuman Help Center [source:raw-source-7081f50e8908d1f4ba36]
- Nuclino：Change the workspace access setting [source:raw-source-a8193807fddd80a85094]
- Nuclino：Share an item [source:raw-source-bfd5ea3104e90ec11fb6]
- Nuclino：Roles and permissions [source:raw-source-c74689c8b2b6337622ab]
