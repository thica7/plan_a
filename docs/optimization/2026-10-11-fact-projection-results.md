# 正式事实投影与报告验收（2026-10-11）

## 结论

**人数、套餐与报价投影修复完成；最终真实流程生成了完整的基础观察草稿。采购决策报告仍未达到交付标准。**

最终一轮耗时117.34秒，状态`completed`，12个官方网页来源，正文5003字符。9个功能主张、11条页面报价全部通过逐条模型核对及引用回放；共同能力表9个格子均有审核通过的观察。未知来源引用0，最终QA为37条覆盖警告、0条阻断。流程完成与基础覆盖通过不能替代同任务可比性和采购条件验收。

[真实报告草稿](2026-10-11-fact-projection-live-draft.md)逐字节保存最终流程输出，没有人工补写。[结构化记录](2026-10-11-fact-projection-results.json)包含八轮结果、来源、事实、矩阵、主张审计、预算及代码指纹；[首轮草稿](2026-10-11-fact-projection-first-attempt-draft.md)仅供失败回溯，不作为交付结果。

## 本轮修复

- 正式价格观察重建分析套餐，矩阵从当前产品与维度的事实及完整条件投影。Confluence保留Free/Standard/Premium；Coda的Pro和Business分别保留年付与月付，套餐×账期无重复；没有模型虚构的Team。
- 矩阵保留原文“你和最多29名队友”，正文也按此表述。已复现的29人误读、正确片段后追加错误总数、不同常用人员单位与英文总数写法均被规则拒绝，即使模型错误给出supported也不能发表。该规则覆盖已知语句，不代表能证明任意自然语言的准确性。
- 功能主张的所有引用事实必须属于同一观察；不能通过另一观察的support_level带入额外内容。审核同时检查已准入的完整原文上下文与限制，避免只看短quote而误拒同一观察的已验证内容。
- Coda只绑定已登记的Superhuman Docs精确来源路径；正文采用原文的当前产品名，运行身份仍为Coda。同域其他产品没有取得能力授权。
- 快速功能分支允许有限的3来源/4抓取/2高级抓取，语义选择最多3页；单条完整引文上限800字符，上下文1600字符、条件4096字符、偏移及归属回放保持。原来505字符的共编段落可完整准入；没有截去限制或绕过登录/网站挑战。
- 报价保留11条已采金额、单位和账期。可见账期选择控件只证明当前页面选择；Confluence同页匹配JSON-LD证实USD及页面所选300人，不能换成十人报价。`billingDuration=P1M`核对显示周期，不能否定年付折月。
- 分段写作和QA显式预占并传输1600输出token。临时并发预占不足时等待已在途调用结算；累计额度真正不足仍拒绝。模型额度不足时保留以前已审分段、标明本段缺口；缺审核的主张不发表，完整性错误和取消仍中止。
- 价格审核只省略没有显式引用、且已被价格条件重复表达的套餐/模型/账期字段；被引用价格的原文、事实值与全部条件保留。相同第七轮快照中，Notion载荷11311→4580B，Confluence12027→4202B，Coda15996→5897B。最终流程仍使用60调用/200000token的既定上限。
- 同一首轮快照的reflector视图剖析耗时149.938→2.124秒，131个事实、97811B输出保持。缓存只分类不可变事实与产品范围，不缓存消费凭据或模型结果；这是一例含剖析开销的观察，不能推广为整体端到端加速比。

## 人工验收

| 项目 | 结果 | 边界 |
| --- | --- | --- |
| 原文人数与正式套餐投影 | 通过本例与回归 | 保留你+29队友；无Team或同套餐同账期重复 |
| 共同轴基础覆盖 | 通过，9/9 | 每家共享编辑、评论、权限标签下均有已审观察 |
| 真正同任务的权限对照 | 部分通过 | Notion展示编辑/分享，Confluence展示创建内容前提，Docs展示管理角色；标签一致不足以直接可比 |
| 原文限制进入正文 | 部分通过 | 矩阵保留完整条件，但正文权限描述未完整展示Docs Full access的Enterprise/Doc Maker等前提；已采但未选入的细节仍有上下文缺口 |
| 已采报价完整展示 | 通过，11/11 | Notion0/10/20；Confluence0/5.42/10.44；Docs0/12年付/15月付/33年付/40月付，均USD页面观察 |
| 动态报价条件 | 部分通过 | 保留账期控件、币种、计费单位、Confluence300人；这不是十人团队合同报价 |
| 主张与引用回放 | 通过本例 | 20个主张supported、未知来源0；模型supported不是完成人工语义验证 |
| 完整账单与赢家 | 未通过 | 十人团队收费角色构成、适用计划、地区/税和同任务限制未齐，双方assessment均insufficient_evidence，无赢家 |
| 全流程稳定性 | 未通过稳定性验收 | 最终成功；第六轮动态价格缺证后重分析仍耗尽预算，不可凭一次成功宣称稳定 |
| 产品决策交付 | 未通过 | 当前可审阅事实摘要，尚不能作为采购或排名结论 |

## 真实运行及成本

| 轮次 | 状态 | 秒 | 计费调用 / 修复 | 累计计费token | 估算USD | 人工结论或失败原因 |
| --- | --- | --- | --- | --- | --- | --- |
| live | completed_with_blockers | 424.38 | 37 / 5 | 185914 | 0.067406 | 旧生产者凭据失效、角色和共同轴不足；未达交付 |
| final | failed | 594.85 | 26 / 0 | 173293 | 0.055645 | 受沙箱浏览器启动和视图构造性能影响；无报告 |
| verified | failed | 53.4 | 21 / 0 | 188905 | 0.068095 | 并发 token 预占误判，取消在途分支；无报告 |
| delivery | failed | 98.18 | 32 / 0 | 180151 | 0.059932 | 最后价格 QA 无法入预算，整份 writer 失败 |
| acceptance | completed | 117.64 | 34 / 0 | 177651 | 0.065838 | 11 报价展示，但人数误审、身份误拒和跨事实权限组合未过人工验收 |
| release | failed | 162.93 | 35 / 1 | 199298 | 0.065552 | 人数正文已改；动态币种缺证引发补证，重分析耗尽预算，失败草稿不得发布 |
| hardened | completed | 114.47 | 33 / 0 | 186154 | 0.060708 | 9 功能主张已审；2 家价格 QA 无法入预算，保留缺口报告 |
| compact | completed | 117.34 | 33 / 0 | 166410 | 0.050562 | 9 功能主张与11报价全审；基础覆盖通过，决策交付仍有缺口 |

最后一轮33次计费调用、0修复调用、166410累计计费token，估算0.050562 USD。八轮预算成本估算合计0.493738 USD，不是供应商实际账单。累计预算含未知用量的保守计费；各span最后一次provider用量的合计是另一口径。本轮未上传本机凭据，也未将真实模型调用替换成固定答案。

## 验证与审查

- 后端完整回归：**3442 passed，1 skipped，152 warnings，89.66秒**。
- 前端：**258 passed / 52文件**，生产构建通过。本轮没有修改前端；该结果来自本阶段先前的同工作区验证。
- 最后独立只读专项：**192 passed，15.99秒**。审查发现的人数绕过与跨观察metadata借用已先红后绿修复，最终无新增可复现P1/P2。
- 保留跨产品、范围、冲突、历史生产者凭据、完整原文条件、取消、未知用量及累计预算检查。`git diff --check`通过。
- 最终草稿和上轮失败记录均保存，不用mechanical_pass代替人工交付。

## 下一步

1. **先做真正同操作的权限对照。** 按阅读、评论、编辑、创建、分享、权限管理拆分；对每项要求同一角色、套餐、分享方式和父级访问条件。把Enterprise/Doc Maker/免费计划限制明确带入正文，不能只给三个不同权限例子。
2. **完成十人账单条件。** 查询Confluence十人页面报价，确认Notion付费成员和Docs Doc Maker/免费编辑者构成，再核对地区、账期、税费和满足共同任务的具体套餐；缺条件时不给总价排名。
3. **为QA与补证预留预算。** 根据预计的剩余分段成本约束前面搜索和分析；重新规划超限的定向补证，保存原快照和有效草稿，避免收完新证据却没有额度重新分析。增加有限的故障/波动验收，再判断稳定性。
4. **独立交付状态。** 用上述必要覆盖和条件明确显示“有缺口草稿/可交付”；当前completed加37条warn不足以表达采购交付状态。该状态设计尚未在本轮新增。

## 复现与运行边界

在仓库根目录执行固定案例：

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/plan_a_playwright PYTHONPATH=backend ../plan_a/.venv/bin/python backend/scripts/eval_live_products.py --live --cases eval/fact-projection-three-products-v1.jsonl --case notion-three-products --output /tmp/plan_a_fact_projection_recheck --timeout 600
```

需本机现有模型、搜索配置及浏览器运行时；匿名浏览器需要正常启动权限。网页和模型存在变化，重跑不保证相同输出。本次用生产LangGraph和真实模型/搜索/安全抓取，存储为内存隔离，没有验收PostgreSQL、Temporal或Qdrant HTTP生产服务，也不能证明RAG整体合格。

本机API及前端HTTP均返回200；API总体health为error，temporal_cutover=error、temporal_server=warn。本轮使用显式LangGraph验收，未把新测试run写入用户原有浏览器任务。真实草稿通过文件交付。

沿用codex/pastoral-desktop，保留原未提交修改，本轮没有提交或推送GitHub。ignored `.env`中的凭据不进入交付文档。

## 最终来源索引

| 来源ID | 产品 / 维度 | 链接 |
| --- | --- | --- |
| raw-source-1cda8c45e8876df4f36c | Notion / feature | [官方页面](https://www.notion.com/help/sharing-and-permissions) |
| raw-source-b92f96c0c5e5d2643df7 | Notion / feature | [官方页面](https://www.notion.com/help/comments-mentions-and-reminders) |
| raw-source-f7a81bf787f1e9e932e7 | Notion / feature | [官方页面](https://www.notion.com/help/collaborate-with-people) |
| raw-source-84d93774a937707e285a | Notion / pricing | [官方页面](https://www.notion.com/pricing) |
| raw-source-a5a35d9a74b6bc0454f0 | Confluence / feature | [官方页面](https://support.atlassian.com/confluence-cloud/docs/create-edit-and-publish-a-page/) |
| raw-source-940ce7ba9cc5de38d91a | Confluence / feature | [官方页面](https://support.atlassian.com/confluence-cloud/docs/add-or-remove-page-restrictions/) |
| raw-source-859c368a1a9cd092356d | Confluence / feature | [官方页面](https://www.atlassian.com/software/confluence/features) |
| raw-source-b0da424f12358e533863 | Confluence / pricing | [官方页面](https://www.atlassian.com/software/confluence/pricing) |
| raw-source-970d5d3dabcdab0bf470 | Coda / feature | [官方页面](https://help.superhuman.com/hc/en-us/articles/46210173956109-Share-your-doc) |
| raw-source-cfd5046889caadc3c3bd | Coda / feature | [官方页面](https://help.superhuman.com/hc/en-us/articles/46210367411469-Comment-on-docs) |
| raw-source-34a67281db3b66591d6c | Coda / feature | [官方页面](https://superhuman.com/docs/use-cases/collaborative-docs) |
| raw-source-2ee7fb10b23da736180d | Coda / pricing | [官方页面](https://superhuman.com/plans/docs) |
