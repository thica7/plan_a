# 比较 Notion、Confluence、Coda（现 Superhuman Docs）、Nuclino 的文档协作能力。请固定这四家，分别核实阅读、评论、编辑、创建、分享、权限管理六种操作的角色、套餐、文档或工作区访问范围、分享及父级访问前提。相同操作才能对照，未知不等于不支持；发现缺口后定向采集官方文档。本例只验收能力比较，不研究价格；不得给采购赢家。输出极简中文分析。

## 执行摘要

本稿按产品与维度展示已审核的证据观察。证据不足以给出赢家或采购建议；采集报价不等于适用价格或完整账单。

## 竞争发现

### 同操作与条件对照

各格仅展示已审核的同操作观察；角色、套餐、分享或父级访问条件不同，不能视为能力相等。

| 操作 | Notion | Confluence | Coda | Nuclino |
| --- | --- | --- | --- | --- |
| 阅读 | 在 Notion 中，「Can view」这一访问级别下，角色为「Can view」的人可以阅读页面上的内容，其前提即为被授予该查看权限，且该级别未标注适用套餐。；套餐未核实 [source:raw-source-a41315254e16772120b6] | 未取得已审核观察，需定向补证 | 在 Coda 中，拥有“Can view”角色的用户可以查看文件夹内的所有文档，该权限仅限 Team/Business 和 Enterprise 套餐；前提是文件夹权限已共享给该用户。 [source:raw-source-7081f50e8908d1f4ba36] | Nuclino 中，完全访问、仅评论和只读三种角色均可查看内容；其中仅评论和只读工作区角色在付费套餐中可用。；套餐未核实 [source:raw-source-c74689c8b2b6337622ab] |
| 评论 | 在 Notion 中，「Can comment」这一访问级别适用于只应具备在页面上评论能力的人；该级别下角色为「Can comment」，其前提即为被授予该评论权限，且该级别未标注适用套餐。；套餐未核实 [source:raw-source-a41315254e16772120b6] | 未取得已审核观察，需定向补证 | 在 Coda 中，拥有“Can comment”角色的用户可以查看并评论文件夹内的所有文档，该权限仅限 Team/Business 和 Enterprise 套餐；前提是文件夹权限已共享给该用户。 [source:raw-source-7081f50e8908d1f4ba36] | Nuclino 中，只有拥有完全访问权限或仅评论角色的工作区成员可以对内容发表评论；该功能在所有套餐中可用。 [source:raw-source-1872723bae803e386c49] |
| 编辑 | 在 Notion 中，拥有页面「Full access」的人可以编辑该页面包含的任何内容，并可将该页面分享给任何他们想要分享的人；该权限级别未标注适用套餐。；套餐未核实 [source:raw-source-a41315254e16772120b6] | Confluence 允许你邀请他人编辑内容，该编辑操作在证据中未标注具体角色、套餐或访问范围。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-1f4d27ce28ed8cf6408f] | 在 Coda 中，拥有“Can manage”角色的用户可以对文件夹内的所有文档执行编辑操作，该权限仅限 Doc Makers；前提是文件夹权限已共享给该用户。；套餐未核实 [source:raw-source-7081f50e8908d1f4ba36] | Nuclino 中，完全访问角色默认可以阅读和编辑；该默认访问设置在付费套餐中可用，且只有拥有完全访问权限的工作区成员可以更改工作区默认访问级别。；访问范围未核实 [source:raw-source-a8193807fddd80a85094] |
| 创建 | 未取得已审核观察，需定向补证 | 未取得已审核观察，需定向补证 | 未取得已审核观察，需定向补证 | 未取得已审核观察，需定向补证 |
| 分享 | 在 Notion 中，拥有页面「Full access」的人可以编辑该页面包含的任何内容，并可将该页面分享给任何他们想要分享的人；该权限级别未标注适用套餐。；套餐未核实 [source:raw-source-a41315254e16772120b6] | Confluence 允许你分享链接，该分享操作在证据中未标注具体角色、套餐或访问范围。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-1f4d27ce28ed8cf6408f] | 未取得已审核观察，需定向补证 | Nuclino 中，只有拥有完全访问权限的工作区成员可以分享条目（items）；团队所有者和管理员可通过高级安全控制禁用公开条目分享；该功能在所有套餐中可用。 [source:raw-source-bfd5ea3104e90ec11fb6] |
| 权限管理 | 未取得已审核观察，需定向补证 | Confluence 允许你设置包含 3 种权限状态的常规访问（General access），该管理访问操作在证据中未标注具体角色、套餐或访问范围。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-dfb0525ca752f8f7e8de] | 在 Coda 中，可以授予外部用户编辑、评论或查看访问权限，但不能授予管理访问权限；外部用户不能创建新文档、将文档移入或移出文件夹、删除文档或邀请他人。；访问范围未核实、套餐未核实、角色未核实 [source:raw-source-7081f50e8908d1f4ba36] | 未取得已审核观察，需定向补证 |

### 功能

### Notion — 功能

- 在 Notion 中，「Can edit content」这一权限级别仅存在于数据库页面（database pages）；拥有该级别访问权限的人可以在数据库内创建和编辑页面，并编辑这些页面的属性值，但无法更改数据库及其属性的结构、视图、排序或筛选。 [source:raw-source-a41315254e16772120b6]

- 在 Notion 中，「Can comment」这一访问级别适用于只应具备在页面上评论能力的人；该级别下角色为「Can comment」，其前提即为被授予该评论权限，且该级别未标注适用套餐。 [source:raw-source-a41315254e16772120b6]

- 在 Notion 中，「Can view」这一访问级别下，角色为「Can view」的人可以阅读页面上的内容，其前提即为被授予该查看权限，且该级别未标注适用套餐。 [source:raw-source-a41315254e16772120b6]

- 在 Notion 中，拥有页面「Full access」的人可以编辑该页面包含的任何内容，并可将该页面分享给任何他们想要分享的人；该权限级别未标注适用套餐。 [source:raw-source-a41315254e16772120b6]

- 本段待核验或缺口：已采资料超出本段上下文，未全部选入、重复或偏离本次操作的观察未发表

### Confluence — 功能

- Confluence 允许你邀请他人编辑内容，该编辑操作在证据中未标注具体角色、套餐或访问范围。 [source:raw-source-1f4d27ce28ed8cf6408f]

- Confluence 允许你分享链接，该分享操作在证据中未标注具体角色、套餐或访问范围。 [source:raw-source-1f4d27ce28ed8cf6408f]

- Confluence 允许你设置包含 3 种权限状态的常规访问（General access），该管理访问操作在证据中未标注具体角色、套餐或访问范围。 [source:raw-source-dfb0525ca752f8f7e8de]

- 本段待核验或缺口：重复或偏离本次操作的观察未发表

### Coda — 功能

- 在 Coda 中，拥有“Can manage”角色的用户可以对文件夹内的所有文档执行编辑操作，该权限仅限 Doc Makers；前提是文件夹权限已共享给该用户。 [source:raw-source-7081f50e8908d1f4ba36]

- 在 Coda 中，拥有“Can comment”角色的用户可以查看并评论文件夹内的所有文档，该权限仅限 Team/Business 和 Enterprise 套餐；前提是文件夹权限已共享给该用户。 [source:raw-source-7081f50e8908d1f4ba36]

- 在 Coda 中，拥有“Can view”角色的用户可以查看文件夹内的所有文档，该权限仅限 Team/Business 和 Enterprise 套餐；前提是文件夹权限已共享给该用户。 [source:raw-source-7081f50e8908d1f4ba36]

- 在 Coda 中，可以授予外部用户编辑、评论或查看访问权限，但不能授予管理访问权限；外部用户不能创建新文档、将文档移入或移出文件夹、删除文档或邀请他人。 [source:raw-source-7081f50e8908d1f4ba36]

- 本段待核验或缺口：已采资料超出本段上下文，未全部选入、重复或偏离本次操作的观察未发表

### Nuclino — 功能

- Nuclino 中，只有拥有完全访问权限的工作区成员可以分享条目（items）；团队所有者和管理员可通过高级安全控制禁用公开条目分享；该功能在所有套餐中可用。 [source:raw-source-bfd5ea3104e90ec11fb6]

- Nuclino 中，完全访问、仅评论和只读三种角色均可查看内容；其中仅评论和只读工作区角色在付费套餐中可用。 [source:raw-source-c74689c8b2b6337622ab]

- Nuclino 中，只有拥有完全访问权限或仅评论角色的工作区成员可以对内容发表评论；该功能在所有套餐中可用。 [source:raw-source-1872723bae803e386c49]

- Nuclino 中，完全访问角色默认可以阅读和编辑；该默认访问设置在付费套餐中可用，且只有拥有完全访问权限的工作区成员可以更改工作区默认访问级别。 [source:raw-source-a8193807fddd80a85094]

- 本段待核验或缺口：已采资料超出本段上下文，未全部选入、重复或偏离本次操作的观察未发表


## 产品机会与验证
- 待验证机会假设：探索与用户任务相关的产品改进，用户任务：共同维护产品文档和团队知识；验证动作：让目标用户完成同一任务并记录阻碍；成功信号：六种操作分别说明证据、角色、套餐、范围与待补条件。用户简报仅作为输入上下文，竞品差异与用户需求仍待验证。

## 置信度说明

已审核只表示绑定证据在本次模型审核中支持该观察，不代表人工验收或产品总体质量。未发布的主张保留在审核记录中。下一步：核验相同任务的同轴能力，并补齐报价条件及完整账单。

## 证据附录

- Notion：Sharing &amp; permissions settings in Notion | Notion Help – Notion Help Center [source:raw-source-a41315254e16772120b6]
- Confluence：Create, update, and manage written content | Confluence Cloud | Atlassian Support [source:raw-source-1f4d27ce28ed8cf6408f]
- Confluence：Change who can find content and what they can do with it | Confluence Cloud | Atlassian Support [source:raw-source-dfb0525ca752f8f7e8de]
- Coda：Share folders and the docs within – Superhuman Help Center [source:raw-source-7081f50e8908d1f4ba36]
- Nuclino：Comment on content [source:raw-source-1872723bae803e386c49]
- Nuclino：Change the workspace access setting [source:raw-source-a8193807fddd80a85094]
- Nuclino：Share an item [source:raw-source-bfd5ea3104e90ec11fb6]
- Nuclino：Roles and permissions [source:raw-source-c74689c8b2b6337622ab]
