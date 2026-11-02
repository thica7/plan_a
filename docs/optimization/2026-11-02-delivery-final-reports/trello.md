# 局部调研报告

## 执行摘要

仅展示通过逐条审核的资料观察；未完成问题仍待核实，不能据此排名。

## 竞争发现

### 功能

### Trello — 功能

- 仅当本看板启用卡片投票时 Observer 看板成员才可投票。 [source:raw-source-033d8ca615035ad47a36]

- Observer 看板成员可下载卡片附件。 [source:raw-source-033d8ca615035ad47a36]

- Observer 看板成员可导出看板。 [source:raw-source-033d8ca615035ad47a36]

- 目前无法在 Workspace 层级将用户设为 observer。 [source:raw-source-033d8ca615035ad47a36]

- 每个 observer 按成员逐看板单独设置。 [source:raw-source-033d8ca615035ad47a36]

- 只有 Workspace 管理员和看板管理员有权把看板现有成员的状态改为 Observer。 [source:raw-source-033d8ca615035ad47a36]

- observer 可对应已列的可计费 Workspace 成员或多看板访客身份。 [source:raw-source-033d8ca615035ad47a36]

- 条件推断：题设 A 已禁用投票时该项投票许可不生效。 [source:raw-source-033d8ca615035ad47a36]

- 条件推断：在题设 B 已启用投票且该用户具有 Observer 角色的条件下可投票。 [source:raw-source-033d8ca615035ad47a36]

- 条件推断：这条 Observer 投票许可本身不构成必须投票的依据。 [source:raw-source-033d8ca615035ad47a36]

- 条件推断：根据逐成员逐看板配置规则对 A 的角色设置不决定 B 的角色。B 的实际角色仍须单独核实。 [source:raw-source-033d8ca615035ad47a36]

- 条件推断：仅凭 observer 权限标签无法核实实际收费身份。需另行核实实际成员身份及适用计费规则；这里不推定免费或具体收费。 [source:raw-source-033d8ca615035ad47a36]

#### 问题回答情况

- Trello: 假设 Trello Workspace 已订阅 Premium，小林已分别被设为看板 A 和 B 的 Observer；A 未启用卡片投票，B 已启用且允许该 Observer 投票。仅依据所给官方页面，逐项判断：小林能在 A、B 投票吗？ — 已回答
  结论：需按条件判断
  - 投票（A） — 否
  - 投票（B） — 是
  仅当本看板启用卡片投票时 Observer 看板成员才可投票。 仅当本看板启用卡片投票时 Observer 看板成员才可投票。 仅当本看板启用卡片投票时 Observer 看板成员才可投票。 题设 A 已禁用投票时该项投票许可不生效。 在题设 B 已启用投票且该用户具有 Observer 角色的条件下可投票。 [source:raw-source-033d8ca615035ad47a36]
- 他能下载 A 的卡片附件并导出 A 吗？ — 已回答
  结论：是
  - 下载卡片附件（A） — 是
  - 导出看板（A） — 是
  Observer 看板成员可下载卡片附件。 Observer 看板成员可导出看板。 [source:raw-source-033d8ca615035ad47a36]
- B 允许投票，是否意味着他必须给每张卡片投票？ 请将可以执行的操作、启用条件与是否存在强制义务分别说明。 — 已回答
  结论：否
  仅当本看板启用卡片投票时 Observer 看板成员才可投票。 这条 Observer 投票许可本身不构成必须投票的依据。 [source:raw-source-033d8ca615035ad47a36]
- Trello: 假设某 Trello Workspace 已订阅 Premium，管理员把看板 A 上现有协作者小周的权限改成了 Observer。同一 Workspace 另有看板 B，但题设没有说明小周是否加入 B、在 B 上的权限，或他属于 Workspace 成员还是哪一种 guest。仅依据所给页面，逐项回答：能否在 Workspace 层级把他统一设置成 Observer，A 上这次改权是否自动决定他在 B 的权限；谁有权把 A 的现有成员改为 Observer；只凭 A 上的 Observer 标签，能否确定他一定免费或一定计费？不要推定题设未说明的成员资格。 — 部分回答
  结论：需按条件判断
  - 能否在 Workspace 层级把他统一设置成 Observer — 否
  - A 上这次改权是否自动决定他在 B 的权限 — 否
  - 能否确定他一定免费或一定计费？ — 否
  目前无法在 Workspace 层级将用户设为 observer。 每个 observer 按成员逐看板单独设置。 只有 Workspace 管理员和看板管理员有权把看板现有成员的状态改为 Observer。 observer 可对应已列的可计费 Workspace 成员或多看板访客身份。 根据逐成员逐看板配置规则对 A 的角色设置不决定 B 的角色。B 的实际角色仍须单独核实。 仅凭 observer 权限标签无法核实实际收费身份。需另行核实实际成员身份及适用计费规则；这里不推定免费或具体收费。 [source:raw-source-033d8ca615035ad47a36]

## 置信度说明

已审核只表示绑定证据在本次模型审核中支持该观察，不代表人工验收或产品总体质量。未发布的主张保留在审核记录中。下一步：核验相同任务的操作、角色与条件。

## 证据附录

- Trello：Add an observer to a board | Trello | Atlassian Support [source:raw-source-033d8ca615035ad47a36]
