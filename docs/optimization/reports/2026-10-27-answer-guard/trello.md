# 局部调研报告

## 执行摘要

仅展示通过逐条审核的资料观察；未完成问题仍待核实，不能据此排名。

## 竞争发现

### 功能

### Trello — 功能

- Trello 的 Observer 是看板成员，能够导出该看板。 [source:raw-source-033d8ca615035ad47a36]

- 由于 Observer 属于看板成员权限，Trello 目前无法在 Workspace 层级将用户统一设置为 Observer，每位 Observer 需按成员、按看板逐一设置。 [source:raw-source-033d8ca615035ad47a36]

- 只有 Workspace 管理员和看板管理员才能将看板现有成员的状态改为 Observer。 [source:raw-source-033d8ca615035ad47a36]

#### 问题回答情况

- Trello: 假设 Trello Workspace 已订阅 Premium，小林已分别被设为看板 A 和 B 的 Observer；A 未启用卡片投票，B 已启用且允许该 Observer 投票。仅依据所给官方页面，逐项判断：小林能在 A、B 投票吗？ — 已回答
  结论：需按条件判断
  看板 A 未启用卡片投票，因此小林作为 A 的 Observer 不能对 A 的卡片投票。 看板 B 已启用卡片投票且允许该 Observer 投票，因此小林作为 B 的 Observer 可以对 B 的卡片投票。 [source:raw-source-033d8ca615035ad47a36]
- 他能下载 A 的卡片附件并导出 A 吗？ — 部分回答
  结论：需按条件判断
  - 他能下载 A 的卡片附件 — 结论：尚不能确定
  - 并导出 A 吗？ — 结论：是 [source:raw-source-033d8ca615035ad47a36]
  Trello 的 Observer 是看板成员，能够导出该看板。 [source:raw-source-033d8ca615035ad47a36]
- B 允许投票，是否意味着他必须给每张卡片投票？ 请将可以执行的操作、启用条件与是否存在强制义务分别说明。 — 尚未核实
  本次已审核证据尚未完整覆盖此问题。
- Trello: 假设某 Trello Workspace 已订阅 Premium，管理员把看板 A 上现有协作者小周的权限改成了 Observer。同一 Workspace 另有看板 B，但题设没有说明小周是否加入 B、在 B 上的权限，或他属于 Workspace 成员还是哪一种 guest。仅依据所给页面，逐项回答：能否在 Workspace 层级把他统一设置成 Observer，A 上这次改权是否自动决定他在 B 的权限；谁有权把 A 的现有成员改为 Observer；只凭 A 上的 Observer 标签，能否确定他一定免费或一定计费？不要推定题设未说明的成员资格。 — 部分回答
  结论：需按条件判断
  - Trello: 假设某 Trello Workspace 已订阅 Premium，管理员把看板 A 上现有协作者小周的权限改成了 Observer。同一 Workspace 另有看板 B，但题设没有说明小周是否加入 B、在 B 上的权限，或他属于 Workspace 成员还是哪一种 guest。仅依据所给页面，逐项回答：能否在 Workspace 层级把他统一设置成 Observer， — 结论：否 [source:raw-source-033d8ca615035ad47a36]
  - A 上这次改权是否自动决定他在 B 的权限； — 结论：尚不能确定
  - 谁有权把 A 的现有成员改为 Observer； — 结论：是 [source:raw-source-033d8ca615035ad47a36]
  - 只凭 A 上的 Observer 标签，能否确定他一定免费或一定计费？不要推定题设未说明的成员资格。 — 结论：尚不能确定
  由于 Observer 属于看板成员权限，Trello 目前无法在 Workspace 层级将用户统一设置为 Observer，每位 Observer 需按成员、按看板逐一设置。 只有 Workspace 管理员和看板管理员才能将看板现有成员的状态改为 Observer。 [source:raw-source-033d8ca615035ad47a36]

## 置信度说明

已审核只表示绑定证据在本次模型审核中支持该观察，不代表人工验收或产品总体质量。未发布的主张保留在审核记录中。下一步：核验相同任务的操作、角色与条件。

## 证据附录

- Trello：Add an observer to a board | Trello | Atlassian Support [source:raw-source-033d8ca615035ad47a36]
