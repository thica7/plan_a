# Collector 正文与 Writer 截断修复：工程验证通过，报告尚未达标

阶段标识 2026-10-21，最终汇总于 2026-10-22。基线 `603cff19a817ee3c488132f68726c1870d7ea716`，分支 `codex/pastoral-desktop`。新四题参考边界已获用户认可，报告尚未获用户验收。未训练模型、未修改真实环境配置、未执行 Docker。

## 结论

最终离线后端 **6833 通过、1 跳过**，新增 **184 项**。变更 Ruff E9/F、OpenAPI 与已提交基线对比、前端 TypeScript/生产构建及恢复后的独立代码审查通过。

同一冻结源码的六组首次模型运行：旧八题正文与保存回答均为 **6 正确、0 事实错误、2 遗漏**；新四题均为 **4 遗漏**。发表 claim ID **9/10 完整绑定、6/10 单谓词**。但报告仍未达标：问答区存在结论与引用不相干、未发表关键前提及服务器事实漏绑。纳入全部可见事实、结论支持和原子性后，严格局部资格旧组 **0/4**、新组 **0/2**，不是完整系统失败率。

“0 事实错误”不表示报告没有错误。Trello 的下载/导出 bare「是」与官方事实一致，实际引用却只谈投票；这是明确的支持错误。此题还遗漏其他子问，因此按 case 记遗漏。[结构化结果](2026-10-21-collector-input-writer-results.json)分开保留事实内容、引用、原子性和最终结论。

## 三项修复与实测

1. **Trello 正文进入提取**：从同一清理后、范围唯一的可见 DOM 重放完整文本，重验标题身份、顺序与哈希；导航、隐藏内容、歧义披露和表格仍保守处理。实抓 **2452 字符、4 个标题**，记录 `visible_dom_replay_after_unbound_boundary`；实际语义提取输入也是 **2452 字符**。空窗口现在会在模型调用前跳过并记录缺口。正文输入已修复，完整回答仍有遗漏。
2. **Cloudflare 转义引文恢复**：仅 provider Markdown 的纯标点转义差异，允许唯一完整原行/段恢复为 raw 引文，保留原始坐标。CommonMark token map 排除代码与未知结构；任何 raw HTML 文档整体关闭新非精确恢复，原 exact 路径保持。原五条失败提案的离线夹具可准入两条完整角色规则，其余半段/条件容量拒绝保留。本轮实抓走 basic HTTP HTML 表格，Cache Domain Purge 具体行已入库并进入四个核心 Agent；纯转义修复收益只由旧失败夹具证明，不把实抓路径变化当受控 A/B。最终正文仍只发表 generic domain scope，缺具体角色和动作到否定结论的支持投影。
3. **Bitwarden 紧凑写作**：feature 逐题写作返回短 `support_refs`；服务器以最后实际发送的 canonical 全行和支持候选恢复完整绑定，再走原 parser、审核、保存及最终 QA。单 operation 或合法例外 span 对可用，任意混合不接受；legacy、一轮写作、**1600 cap**、预算与重试保持。Bitwarden 实际 `finish_reason=stop`，限额否定和离职澄清已进入正文，未再截断；其他三组 Writer 也正常 stop。短引用身份合法不代表语义正确，BW/Trello 原始返回仍超过8个 atom，服务端继续执行上限与审核。未证明长 ID 是历史 length 的唯一原因，也未建立真实 token 效率改善。

仅四个生产 Python 文件、一个依赖 manifest、三个新测试和一份原失败夹具变化；既有测试未改。`markdown-it-py==4.2.0` 仅作本地语法解析，不渲染 HTML，不下载模型权重。良性 HTML 文档也不获得新非精确恢复，是明确的保守边界。

## 六组首次结果

| 产品 | 正文 正确/事实错误/遗漏 | claim ID 完整绑定 | 单谓词 | 实际 QA blocker |
| --- | --- | --- | --- | --- |
| Bitwarden | 2/0/0 | 4/4 | 3/4 | 2 |
| 1Password | 2/0/0 | 3/3 | 1/3 | 2 |
| Dropbox | 0/0/2 | 0/0 | 0/0 | 1 |
| Cloudflare | 2/0/0 | 1/1 | 1/1 | 2 |
| Trello | 0/0/2 | 1/2 | 1/2 | 4 |
| Miro | 0/0/2 | 0/0 | 0/0 | 1 |

保存回答统计与正文一致。0/0 表示没有发表主张，不能按空集算绑定通过。新四个 case 拆成七个内部 question ID，仍按四题计数；缺价答复不是准确金额正例，空报告不是合理拒答。所有样本均已曝光，不是盲测或泛化准确率。

Bitwarden、1Password、Cloudflare、Trello 的 Analyst、Comparator、Reflector、Writer 都实际调用模型，核心模块无回退。Dropbox 无合格正文，Miro403，两组在准入前阻断，没有下游模型调用，确定性 QA 仍有记录。单产品 Comparator 执行不代表多产品同口径比较已验收。实际模型输入中有事实也不代表完整使用：BW 部分删除/归属事实仍在上游预算中省略，Writer 中部分原文缺可引用 span，错误绑定被拦，最终保留澄清。

## 下一步优先级

1. **问题级结论支持**：Trello 首轮覆盖评估把下载/导出判为 unanswered，复审却改成 answered 并使用投票 claim。逐子问核对动作、对象、角色、前提和所选支持，阻断“ID 合法但结论无关”。
2. **完整支持到正文的投影**：1Password 的 Private vault 否定、CF 的具体 Cache Domain Purge 跨域否定缺已发表前提；不能从“可升级”推出“当前访客不能”，也不能仅用 generic scope 证明具体角色。区分已采、已发送、可引用和已发表。
3. **全部断言与原子性**：三条旧组复合主张仍被模型原子性审核放行；Trello 计费推断所选窄 span 不含计费分支；CF CPU 服务器短句有 snapshot 依据，却没有逐断言精确绑定。服务器文字也应进入同一审核合同。
4. **抓取与独立验收**：解决 Dropbox 导航壳及 Miro403后的合格正文获取；另验全 Graph/发布、Planner 自动发现、跨产品比较与生产语义 RAG。当前先修支持与投影，暂不训练。

## 工程、费用与验收边界

- 恢复阶段重新执行全后端：6833 passed / 1 skipped / 212 warnings；新三文件独立184 passed。OpenAPI 与已提交 JSON 基线一致，TypeScript 由前端生产构建验证；丢失的原独立旧 TS 夹具未假称重放。
- 每组原额度24调用/80000 token/2048输出上限/重试0，Writer实际1600。六组共 **50次模型调用、171070个 provider token、usage未知0**；另有 **4次Web API请求、2次成功响应**，固定URL测试未做Search发现。API成功不等于合格正文，工具计费估计不是发票，无受控A/B不宣称效率改善。
- 实际 QA 共 **12 blocker**（旧7、新5）。阶段 runner 固定 `deliverable=False`，未走完整 Graph 发布，不从此字段推导完整系统0/6交付。
- 当前 **749个冻结源码/输入、76个解析依赖文件**均匹配。11份捕获导出哈希可核验，无正文脱敏占位；六份导出与保存 run 内容一致，末尾换行差异单列。参考答案未进入运行输入；参考认可不等于报告人审。
- 实际检索为 degraded_lexical，诊断存储关闭语义索引；生产 dense RAG 未验收。模型标签为 deepseek-flash，没有独立1017权重版本证明。未训练、未赋奖励、未下载模型权重、未执行Docker、未合并main。

## 中断后的证据恢复说明

中断后 `/tmp/plan_a_v35_*` 不再存在：原辅助启动脚本、初版 SPEC/QUALITY/累计报告、失败日志、中间源码快照及2191历史文件SHA清单未能恢复。会话中曾记录这些检查通过，但**不据此冒称它们当前仍可重放或已归档**。原 `freeze.json` 保持不改；临时路径不可用状态另记 `verification/recovery/evidence-loss-and-current-integrity.json`。

仓库源码、新增回归测试、原始六组 run/trace/inputs/snapshot/captures 和冻结清单仍在。恢复阶段没有重新调用模型，重新做独立代码审查、旧八题/新四题隔离审读、完整离线回归与构建。新证据直接保存在项目忽略目录 `data/artifacts/collector-input-writer-2026-10-21/verification/recovery/`。旧组恢复初版误将 body 限于竞争发现 bullets，v2 改为完整 report.md 含问题回答段；v1及差异说明保留，保存答案、原始产物、绑定与严格资格不变。该修正不是为匹配旧标签。

私有原始产物不提交Git。公开提交代码、测试及摘要文档；`verification/proof-index.json` 索引现存证据，提交后 `verification/git-delivery.json` 记录实际远端SHA。密钥扫描覆盖当前配置凭据字面量、公开文本、构建产物及本轮证据，不输出凭据值；不是Git全历史审计。
