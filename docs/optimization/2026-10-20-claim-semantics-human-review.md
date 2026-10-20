# 主张语义新候选题人审单（2026-10-20）

状态：四题均为 `candidate`，由代理准备，**尚未人审**。这组题是旧八题以外的新候选，属于已知产品与已知官方页上的新问法；不是盲测、不是训练集，未调用模型或产生奖励。请先审核题设与建议边界，再决定是否接纳为评测样本。

只依据两条登记官方 URL 的当前正文，核验于 2026-10-20 09:28:07 UTC。题内假设仅为评测条件，不表示真实账户配置。参考答案与下列建议仅供人审和评分，禁止放入运行输入或发给实现者。

## 1. Trello — claim-semantics-candidate-20261020-trello-001

**候选问题**

假设 Trello Workspace 已订阅 Premium，小林已分别被设为看板 A 和 B 的 Observer；A 未启用卡片投票，B 已启用且允许该 Observer 投票。仅依据所给官方页面，逐项判断：小林能在 A、B 投票吗？他能下载 A 的卡片附件并导出 A 吗？B 允许投票，是否意味着他必须给每张卡片投票？请将可以执行的操作、启用条件与是否存在强制义务分别说明。

**建议答案边界**

A 未启用投票，不能据 Observer 身份在 A 投票；B 已满足题设投票启用及允许条件，可以投票。页面明确列出 Observer 可以下载卡片附件并导出看板，因此可以下载 A 的附件并导出 A；不能把投票开关扩大为这两项操作的共同条件。可以投票表示能力或许可，页面没有要求 Observer 给每张卡片投票，不能将其写成必须。

**逐项核对**

- [ ] 当前讨论的是 Premium Workspace 内两个已分别赋予 Observer 权限的看板；A 与 B 的投票条件不同。
- [ ] 投票能力保留看板启用条件：题设 A 不满足、B 满足。
- [ ] Observer 可以下载卡片附件和导出看板；不能因 A 未启用投票就否定这两项能力。
- [ ] 可以投票不能改写为必须逐卡投票；来源没有给出该强制义务。

**官方来源**：[ Add an observer to a board ](https://support.atlassian.com/trello/docs/adding-observers-to-boards/)

**人审决定**：□ 接纳　□ 需修改后重新登记　□ 拒绝

**意见**：________________

## 2. Trello — claim-semantics-candidate-20261020-trello-002

**候选问题**

假设某 Trello Workspace 已订阅 Premium，管理员把看板 A 上现有协作者小周的权限改成了 Observer。同一 Workspace 另有看板 B，但题设没有说明小周是否加入 B、在 B 上的权限，或他属于 Workspace 成员还是哪一种 guest。仅依据所给页面，逐项回答：能否在 Workspace 层级把他统一设置成 Observer，A 上这次改权是否自动决定他在 B 的权限；谁有权把 A 的现有成员改为 Observer；只凭 A 上的 Observer 标签，能否确定他一定免费或一定计费？不要推定题设未说明的成员资格。

**建议答案边界**

不能在 Workspace 层级统一设置 Observer；它是逐成员、逐看板设置的权限，所以 A 的改权不能自动决定 B 的权限，B 是否有成员资格及其角色仍未说明。Workspace 管理员和该看板管理员可以把现有看板成员改为 Observer。Observer 是看板权限而不是成员类型；页面列有可能计费的 Workspace 成员或多板 guest，以及不计费的单板 guest。题设缺少实际成员类型及相关看板关系，不能只凭 A 的 Observer 标签确定一定免费或一定计费，也不能给出具体费用。

**逐项核对**

- [ ] Observer 是看板成员权限，不是 Workspace 层级可统一设置的成员类型。
- [ ] Observer 逐成员逐看板设置；A 的改权本身不能决定 B 的成员资格或权限。
- [ ] 改变 A 现有看板成员为 Observer 的主体是 Workspace 管理员或 A 的看板管理员。
- [ ] 来源存在计费与不计费的 Observer 情形；仅有 A 上角色标签不足以判断该用户的计费状态。

**官方来源**：[ Add an observer to a board ](https://support.atlassian.com/trello/docs/adding-observers-to-boards/)

**人审决定**：□ 接纳　□ 需修改后重新登记　□ 拒绝

**意见**：________________

## 3. Miro — claim-semantics-candidate-20261020-miro-001

**候选问题**

假设 Miro 团队使用 Business 套餐并已允许邀请 Guest；外部协作者小吴已注册、登录，且被明确以 Guest 身份授予看板 A 的编辑权限。仅依据所给页面，逐项判断：他能在 A 添加便签和修改文字吗；能否据此向新的人分享 A 或更改 A 的分享设置；能否创建或编辑 A 上的 Tables、Timeline widgets？请保留 Guest 身份与具体操作的边界，不要将编辑权限理解为所有管理和组件功能均可用。

**建议答案边界**

可以在受邀看板 A 添加便签、修改文字，这属于明确以编辑者身份受邀的 Guest 所能执行的内容操作。但 Guest 不能向新的人分享看板或更改看板分享设置；编辑权限不包含这些分享管理操作。页面还明确将创建或编辑 Tables、Timeline widgets 列为 Guest 不可用的功能，因此这两类操作也不能由 A 的编辑权限推出可执行。

**逐项核对**

- [ ] 题设已给出 Business、允许 Guest、注册登录、受邀看板 A 以及明确编辑权限。
- [ ] 以编辑者身份受邀的 Guest 可以在受邀板创建和修改普通内容，包含便签与文字。
- [ ] Guest 不能分享给新的人或更改看板分享设置，内容编辑权不覆盖分享管理。
- [ ] 创建或编辑 Tables、Timeline widgets 对 Guest 不可用，即使其有看板编辑权限。

**官方来源**：[ Collaboration with Guests ](https://help.miro.com/hc/en-us/articles/360021415119-Collaboration-with-Guests)

**人审决定**：□ 接纳　□ 需修改后重新登记　□ 拒绝

**意见**：________________

## 4. Miro — claim-semantics-candidate-20261020-miro-002

**候选问题**

假设 Miro Enterprise 组织中的小林在组织层级是 Member，当前尚不是团队 T 的成员，但已作为看板 Guest 访问 T 内某板；组织设置中 Team privacy 已关闭，T 的 Members can join after approval 已开启。另有外部协作者小陈，其组织角色仍为 Guest，同样的设置适用。仅依据所给页面，逐项回答：两人谁可以请求加入 T；具备请求资格是否意味着必须提交申请、会自动成为团队成员；该页面能否支持“提交后最迟 24 小时一定批准”的承诺？请区分组织角色和看板 Guest 身份。

**建议答案边界**

小林具备请求加入 T 的条件：组织角色为 Member，Team privacy 关闭，团队允许审批后加入；作为某板 Guest 的有限访问不否定题设组织 Member 身份。组织角色仍为 Guest 的外部用户小陈没有请求加入团队的选项。拥有请求选项表示可以发起申请，不能改写成必须申请或自动成为成员；题设设置还保留审批条件。页面没有提供 24 小时批准时限或必批保证，因此对该承诺资料不足，不能给出保证。

**逐项核对**

- [ ] 请求加入团队的组织角色条件是 Member；看板上的 Guest 访问与组织层级 Member 可以并存。
- [ ] 小林满足组织 Member、Team privacy 关闭、Members can join after approval 开启三项条件，可以请求加入。
- [ ] 组织角色为 Guest 的外部用户小陈没有请求加入的选项。
- [ ] 可以请求不表示必须请求、自动加入或保证批准，审批条件仍需保留。
- [ ] 页面没有给出 24 小时批准承诺，必须对这一子问明确答资料不足。

**官方来源**：[ Collaboration with Guests ](https://help.miro.com/hc/en-us/articles/360021415119-Collaboration-with-Guests)

**人审决定**：□ 接纳　□ 需修改后重新登记　□ 拒绝

**意见**：________________

## 冻结与运行约束

- 冻结文件：`data/artifacts/claim-semantics-2026-10-20/new-samples/sample-freeze.json`。
- 运行只使用同目录 `runtime-cases.jsonl`；每题只有 `id`、`product`、`question`、`sources`，每个来源只有 `id`、`title`、`url`。
- `candidate-cases.jsonl` 中的参考答案、必需事实、禁止推断，以及 `source-evidence.json` 的短节选均不得进入运行输入；不注入 fixed excerpt。
- 冻结记录只创建一次；题目和标签不随模型结果修改。人审结论应另存新记录，不覆盖本次冻结文件。
- 不据未审候选宣称已通过，不将小样本结果当作泛化结论。人审单本身不代表已获用户批准。
