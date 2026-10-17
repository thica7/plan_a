# 独立评测候选：8 题便捷审核单

8 条均为 candidate，尚未经人工审核；未运行模型测试、未训练。可回复“1–8 均认可”，或按编号修改问题、边界或类别。该回复只确认候选的语义边界，不代表接受系统输出或训练。

本批与修复工作隔离构造；代码冻结前请勿将题目或参考边界交给实现代理。独立构造不等于后续未曝光盲测。

| 编号 | 问题 | 应保留边界 | 官方依据 | 建议类别 |
| --- | --- | --- | --- | --- |
| 1 | 我们都在 2026 年新建了 Bitwarden 账户，并建立一个 Free organization，想让包括我在内的 3 个人用 3 个 collections 共享密码。这个免费组织能满足吗？ | Free organization 总共 2 人、最多 2 个 collections；新建账户范围。 | [Password Manager Plans \| Bitwarden](https://bitwarden.com/help/password-manager-plans/) | 条件回答 |
| 2 | 我们准备在 Bitwarden 里把离职同事“删掉”。他保存的那些密码之后还会留下吗？ | 先确认移除成员还是删账户，以及个人/组织数据归属；不保证统一结果。 | [Permanently Remove Access \| Bitwarden](https://bitwarden.com/help/remove-users/)；[Delete Member Accounts \| Bitwarden](https://bitwarden.com/help/delete-member-accounts/) | 需澄清 |
| 3 | 在 1Password Families 中，访客已接受邀请并被确认。他能同时加入两个共享保险库，或者拥有自己的 Private vault 吗？ | Families 的已确认 guest：同一时间 1 个库，无自己的 Private vault。 | [Share with guests in 1Password Families \| 1Password Support](https://support.1password.com/guests/) | 明确可回答 |
| 4 | 我们有 300 名员工，准备买 1Password Unified Access 一年。请仅凭公开定价页，直接给出精确的人民币含税总价，不要给区间。 | Unified Access 定制报价；人数和期限不足以推出精确人民币含税价。 | [1Password Pricing and Plans \| 1Password](https://1password.com/pricing) | 合理拒答（精确价不足） |
| 5 | 我通过邮件直接邀请别人访问 Dropbox 共享文件夹，只给了 Can view 权限，没有发共享链接。这样能阻止他下载文件夹里的文件吗？ | 直接共享的 Can view 仍能下载；不能套用共享链接的下载限制。 | [How to manage Dropbox sharing permissions - Dropbox Help](https://help.dropbox.com/share/set-file-folder-permissions) | 明确可回答 |
| 6 | 我在 Dropbox 里“取消共享”了，之前拿到文件的人现在就完全看不到了吗？ | 先确认具体取消操作、访问方式和副本；不能保证对方完全失去内容。 | [How to unshare files and folders in Dropbox - Dropbox Help](https://help.dropbox.com/share/unshare-folder) | 需澄清 |
| 7 | 同事只被授予 example.com 的 Cache Domain Purge 角色，没有任何其他角色。他能因此清除同一 Cloudflare 账户里 other.example 的边缘缓存吗？ | 仅获 example.com 的域名角色，不能扩大成账户全部域名权限。 | [Account roles · Cloudflare Fundamentals docs](https://developers.cloudflare.com/fundamentals/manage-members/roles/) | 条件回答 |
| 8 | 我们用 Cloudflare Workers Paid 的 Standard 用量模式，这个月有 1500 万次动态请求。本月账单准确是多少美元？ | 请求数不足以确定账单；仍缺 CPU 等用量，不能复制带 CPU 假设的示例总价。 | [Pricing · Cloudflare Workers docs](https://developers.cloudflare.com/workers/platform/pricing/) | 合理拒答（精确价不足） |


## 旧轨迹标签审核（T1–T3）

这是**单题**标签，不代表整份报告通过。请另回复“T1–T3 均认可”，或指出需改编号。候选标签尚未转为人审标签，也未生成训练奖励。

| 编号 | 保存的输出与问题 | 候选标签 | 请审核的范围 |
| --- | --- | --- | --- |
| T1 | Basecamp 的外部协作者能否担任 Admin：答复保留 2022-09-14 账号创建日期分支，并请求确认创建日期。 | 成功 | 仅认可这个单题的条件结论；该次整份报告仍有阻断，旧引用精度不因此放行。 |
| T2 | GitBook Chat：旧答复写成“只有 Enterprise 可以”，漏掉其他受支持套餐。 | 失败 | 将事实遗漏／过度排他结论记为失败；任务 completed 不改变标签。 |
| T3 | GitBook Enterprise：中国、人民币、月付、含税且指定日期的精确报价没有合格资料时，明确答复资料不足。 | 合理拒答 | 不用赠送额度或其他地区价格代替报价；不是把未知写成不支持。 |

对应 run、question 与报告 SHA 已保存在 `eval/agent-readiness-trajectory-review-v1-candidate.json`，原报告未修改。其余已曝光单题保留 unlabelled；不会因 QA 通过自动归为成功。

## 审核后的用途

1. 确认 1–8 题的参考边界与 T1–T3 的候选标签，仍不代表验收新生成报告。
2. 后续只把问题和官方来源身份传入 Agent，参考答案与标签留在评测侧。
3. 先比较基线与修复后的答案、条件归属、引用和成本；训练继续保持关闭。当前不需要准备显卡。
