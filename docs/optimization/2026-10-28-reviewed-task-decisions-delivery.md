# 已审核任务结论到最终答案的交付复验

状态：数量核心的正文交付已恢复，完整报告仍未达到交付标准。实验开关默认关闭，暂不训练模型。

## 本轮修复什么

原流程已能生成并审核部分正确推论，但最终答案再次套用事实专用规则，或被同分支其他无证推论连带撤回。单有 `supported` 标签不足以证明它回答了当前任务，也不足以授权发表。

本轮保留 GEN5 和 REVIEW3，在原有独立 ANSWER 调用中使用 `subquestion-premises-v6`。服务器从真实任务、当前证据、逐条审核和实际传输重建候选，核对其是否回答指定任务后签发凭证。仅支持明确数量超限和跨资源权限非蕴含；推论仍标为 inference，不改成 fact。正文、QA 和持久化重放使用相同认证路径。

新凭证不能让“另一位用户”自动变成已证实人数上限，不能将逐看板权限规则用于计费，也不能凭未提及某行为推断禁止。未知分支仍保留缺口。模型响应格式失效局部隔离；来源、任务或传输认证失败仍拒绝。

## 两轮真实失败与后续修复

| 固定资料回放 | 实际调用 | 已知 tokens | 原题通过 | 必要分支通过 | 完整报告 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 首轮合同接线 | 81 | 278394 | 2/8 | 11/22 | 0/4 |
| 紧凑候选窗口 | 85 | 292533 | 3/8 | 12/22 | 0/4 |
| 已审核数量核心投影 | 92 | 319980 | 5/8 | 16/22 | 0/4 |

三轮 usage 未知均为 0。表中完整报告要求文本和证据均合格，最终轮仅文字完整为 1/4。这是分别发生的回放，不能将调用量变化解释为降本或因果提升。

首轮 Bitwarden 的完整待审材料超过 14000 字节，未能送审。第二轮候选投影去掉重复 claim 和纯身份坐标，保留完整语义、原文和父级限定，实际输入降至 11748 字节。旧投影按原语义重放，窗口、输出上限、阶段数和预算不变。

第二轮 Bitwarden 的 collections 结论已从真实独立审核签发一张凭证，但模型同分支还选择无对应凭证的人数推论；最终整分支降格，正式答案附着凭证和正文落地均为 0。这轮证明窗口修复有效，尚未证明结论交付成功。

后续采用显式版本策略，仅对一个共同数量需求、原始完整 No、原已选择且真实认证的决定性数量推论投影核心。混合权限或计费、OR、独立多项输出、未知分支不适用。保留原选择、保留与排除 IDs；原模型输出和审核记录不改。旧无策略的记录保持原有语义。

最终轮 Bitwarden 的真实 ANSWER 输入为 12270 字节。模型批准、工厂认证、最终答案附着和正文发表均为 1：保留原分支中的 collections 核心，排除其余 3 条主张。正文明确给出“No”，依据是需要 3 个 collections，而所选官方证据的上限为 2。它不依赖被排除的人数推断。

## 最终内容验收

| 产品 | 两道原题结果 | 尚未交付完整的内容 |
| --- | --- | --- |
| Trello | 1 通过、1 部分 | 管理员未列全 Workspace admin；计费答复和所选支持不完整。 |
| Cloudflare | 1 通过、1 失败 | CPU 计费和准确账单缺项；场景推论单条所选支持仍不完整。 |
| Bitwarden | 2 通过 | 问题级 No 和合理澄清已交付，功能段仍有无充分支持的人数上限强化。 |
| 1Password | 1 通过、1 失败 | 缺公开报价性质、缺项及官方销售／报价下一步。 |

共 5 题通过、1 题部分、2 题失败；22 分支为 16 通过、3 部分、3 失败。文字完整 1/4（Bitwarden），文本与证据、全部主张原子性、严格系统 QA 三层均为 0/4。

19 条唯一可见产品主张中，17 条完整支持、2 条部分支持；10 条单谓词、9 条复合。计数包含 17 条正文主张和 2 条仅在渲染子问题行出现的独立场景 No，不能因为缺独立 claim ID 就漏算，也不拆复合句扩大分母。全部 QA 的 28 项计划均实际送达且有效，最终保留 26 项 finding，其中 11 blocker、15 warn；系统计数与独立内容评分分开。

## 如何核验

沿用四家、八道原题和二十二项必要分支，以及固定的 2026-10-21 官方页快照。只允许配置的模型接口请求，不重新搜索或抓取；不把答案和人审单交给 Agent。模型只确认配置别名 `deepseek-flash`，服务商具体权重修订未核实。

每轮单独冻结源码和运行脚本，保存原始输入、输出、实际调用、QA 和原样报告。先规格审查，再代码质量审查；工程测试、生产重放认证和独立正文质量分别判断。凭证签发、答案附着和正文发表分别计数，不能互相代替。

最终轮完整后端 8729 通过、1 跳过、212 项警告；15 份变更 Python 文件按原路径配置对照 HEAD，Ruff 新增问题为 0，现有问题 539 项（基线 542）。首轮标准 OpenAPI 导出与 TypeScript 编译通过，后两轮仅核对生成文件哈希，未重新编译。

最终回放为 92 次实际调用、319980 个已知 tokens、usage 未知 0；前后冻结清单相同。源码归档包含 831 份文件及冻结清单，凭据扫描未发现实际密钥。独立正文审计 SHA256 为 `93fb1575b453601b764a599f2ad8e77b5752b1586ea1560aacb0fe7b770fe3fc`；源码与运行证据哈希详见结构化结果。

四家实际生成、解析、消费、正文重放与完整 QA 候选／批次认证通过。28 项 QA 均送达有效，15 批，保留 19 项 keep；超时、输出截断和未送审均为 0。旧 N4／N5 八家次真实重放保持原结果，原全部推断资格守卫逐字未变。运行审计 SHA256 为 `b4b7bb5f4941366730356bee9edbb8cd5cd0f0c9727f8311d184379caa1be4ef`。

十二个分析／比较／反思阶段均有真实模型结果、无模块回退。但 Bitwarden 澄清、Cloudflare 和 1Password 报价问题仍使用服务端回退，未执行相应独立 ANSWER 审核；前者可作为必要澄清交付，后两者只显示泛化占位，未交付完整缺项答复。协议重放通过不等于这些内容已完成。

## 接下来最值得修的地方

1. **完整主张审核。** Bitwarden 的问题回答已经给出数量否定，但功能段仍把“与另一位用户共享”强化成确定人数上限。应核对整句每个谓词和模态，不能让审核通过的局部事实掩盖新增断言。
2. **子问结论与选证的完整交付。** Trello 的管理员答案只列部分角色，计费说明没有完整进入最终答复；“谁有权”的答案也不应只展示“是”。应由原子任务驱动答案内容与引用，并保留未完成项。
3. **有依据的缺项答复。** Cloudflare 的精确账单缺 CPU 计费和输入，1Password 缺公开报价性质及官方报价下一步。当前服务端提前转成缺报价回退，正文只显示未核实；应保留已有规则、具体缺项和有证据的处理途径，再审核该局部答案。

这些问题仍在当前报告中，不能把本轮数量核心交付成功扩写为所有主张、所有 Agent 或完整报告均合格。暂不训练模型。

## 各 Agent 的本轮范围

| Agent | 本轮功能与验收范围 |
| --- | --- |
| Planner | 沿用已有固定问题和范围，本轮没有重新验收竞品发现。 |
| Collector／Survey | 沿用已采官方页和已准入事实；没有新抓取、用户访谈或完整采集生命周期验收。 |
| Analyst | 使用固定输入运行实际分析阶段；传输和产物消费重放与内容准确度分别核验。 |
| Comparator | 运行实际比较阶段并核产物消费；不因阶段成功就认为矩阵和最终报告合格。 |
| Reflector | 运行实际反思阶段，保留真实问题；不替代独立最终 QA。 |
| Writer | 本轮修复重点：任务归属、真实独立审核、凭证、候选窗口、有限核心投影及持久化正文。 |
| QA | 沿用独立 QA9；重建完整当前候选、历史问题和实际批次，继续保留合法 keep／阻断。 |

这是固定资料上的真实阶段回放，不是完整 Graph 从发现、抓取、入库到交付的一次端到端验收。

## 原样报告与结果

- 首轮：[Trello](reports/2026-10-28-task-decisions-initial/trello.md)、[Cloudflare](reports/2026-10-28-task-decisions-initial/cloudflare.md)、[Bitwarden](reports/2026-10-28-task-decisions-initial/bitwarden.md)、[1Password](reports/2026-10-28-task-decisions-initial/1password.md)。
- 窗口修复轮：[Trello](reports/2026-10-28-task-decisions-window/trello.md)、[Cloudflare](reports/2026-10-28-task-decisions-window/cloudflare.md)、[Bitwarden](reports/2026-10-28-task-decisions-window/bitwarden.md)、[1Password](reports/2026-10-28-task-decisions-window/1password.md)。
- 最终轮：[Trello](reports/2026-10-28-task-decisions/trello.md)、[Cloudflare](reports/2026-10-28-task-decisions/cloudflare.md)、[Bitwarden](reports/2026-10-28-task-decisions/bitwarden.md)、[1Password](reports/2026-10-28-task-decisions/1password.md)。
- [结构化结果与证据哈希](2026-10-28-reviewed-task-decisions-results.json)。
- [实施计划与后续根因](2026-10-27-reviewed-task-decisions-plan.md)。

运行结束、工程测试通过或证据认证通过，均不代表完整报告达到交付标准。本轮未验收新抓取、盲测、全 Graph 或生产稠密 RAG，也未启用默认实验功能。

## 固定快照来源索引

来源链接取自固定页元数据，未重新联网核验。它便于核对原样报告中的 source ID，不能代替具体所选原文的支持审核。

| source ID | 官方页面 |
| --- | --- |
| raw-source-033d8ca615035ad47a36 | [Add an observer to a board ／ Trello ／ Atlassian Support](https://support.atlassian.com/trello/docs/adding-observers-to-boards/) |
| raw-source-52ba7b31b51e937245c1 | [Pricing · Cloudflare Workers docs](https://developers.cloudflare.com/workers/platform/pricing/) |
| raw-source-c71a5d8161af6e06ae53 | [Account roles · Cloudflare Fundamentals docs](https://developers.cloudflare.com/fundamentals/manage-members/roles/) |
| raw-source-476cdfef80ec06d6a285 | [Password Manager Plans ／ Bitwarden](https://bitwarden.com/help/password-manager-plans/) |
| raw-source-113cbfda74a5c2bc8f6e | [Permanently Remove Access ／ Bitwarden](https://bitwarden.com/help/remove-users/) |
| raw-source-70aef72eac936826d54c | [Delete Member Accounts ／ Bitwarden](https://bitwarden.com/help/delete-member-accounts/) |
| raw-source-9ea4b68f00a9a2851e78 | [Share with guests in 1Password Families ／ 1Password Support](https://support.1password.com/guests/) |
