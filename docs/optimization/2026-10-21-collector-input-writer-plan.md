# Collector 正文交付与 Writer 截断修复计划

> **For agentic workers:** 用 subagent-driven-development 顺序执行三个任务；每项先失败回归、实施、SPEC、fresh QUALITY。用户已确认按 Trello→Cloudflare→Bitwarden 修复并复验，无需重复批准。复用现有 linked worktree、分支 `codex/pastoral-desktop`，基线 `603cff19a817ee3c488132f68726c1870d7ea716`。

**Goal:** 已抓正文能在原始身份及条件完整的前提下进入提取/入库，降低重复输出字段造成的写作截断；用同一最终代码重跑旧8题与已认可新4题，按实读判报告质量。

**Architecture:** 沿用原采集→semantic/native提案→准入→canonical/snapshot→Agent→Writer/独立审核→保存/最终QA。修原文捕获和唯一引用映射，不通过宽松蕴含或放行未知来源绕过门禁。Writer只压缩私有模型传输，保存仍为完整v3绑定。

**Tech Stack:** Python、pytest、现有 HTML DOM/Markdown 捕获、`markdown-it-py==4.2.0`（仅本地解析、不渲染）、DeepSeek 有界接口；不增加基础设施、模型训练或权重。

## 根因与设计选择

- Trello：1971字符正文存在，`heading_source_boundary_unbound` 后没有合法 anchors，`semantic_body_window` 返回空，仍消耗一次提取调用。选在捕获入口修复同一可见DOM的完整文本/标题身份，保留歧义失败；不在下游跳过标题校验。
- Cloudflare：原模型已选 Cache Domain Purge，原行末尾是 Markdown 转义句号，模型原句丢了该转义，全部5个角色提案被 `not_original` 拒绝。对 provider Markdown 仅允许完整原始行/段的纯格式转义唯一匹配，返回原行及原始offset；不改词、不去条件、不凭问题填事实。比放宽全文模糊匹配更易审计；比反复抓网页更直接。
- Bitwarden：Writer已实际收到限额，却在1600输出上限报length（组上限2048）。先压缩原子计划中重复的产品/维度和长fact/source/binding ID；短引用必须由服务器唯一映射回实际发送的同一支持候选，保留严格逐条审核。优先单次紧凑传输，避免简单增加输出额度、重试或重复全上下文分题调用。

## 任务1：Trello完整正文与标题身份

Files：`backend/packages/tools/fetch_page.py`、`backend/packages/agents/collectors/logic.py`（仅空窗诊断/避免空调用所需）、新增 `backend/tests/unit/test_collector_input_recovery.py`。

- [x] RED：匿名真实结构 HTML（h1/h2 + div/span/直接flow正文）在 `_capture_html` 保留正文、完整合法DOM anchors；多个相同标题、原条件、隐藏/导航和页外内容不能串入。
- [x] GREEN：同一已清理且范围唯一的可见DOM重放为完整文本，在重新验证标题路径与原始顺序后恢复身份，记录恢复原因；marker漂移、重复身份、歧义root等仍失败。不从仅剩text伪造DOM。
- [x] 真实Collector入口测试断言实际模型body非空、完整且来自当前capture；空窗不调用模型，留下明确local gap，不消耗提取次数。
- [x] 原标题/表格/披露/条件/Provider窗口回归及SPEC→QUALITY通过后停写冻结。

## 任务2：Cloudflare转义原句到入库

Files：`backend/packages/research/extraction/semantic.py`、新增 `backend/tests/unit/test_markdown_quote_recovery.py`，最小原始失败夹具可放 `backend/tests/unit/fixtures/collector_quote_v34.json`。

- [x] RED：原捕获和模型五条quote离线回放，精确复现 `not_original`；匿名转义角色行对照也失败。
- [x] GREEN：仅provider Markdown、仅纯标点转义差异，唯一完整连续原行/段恢复为原始quote；保留原proposal diagnostics与真实offset。重复/改词/缺前提/截半行/代码块/错误source一律不借格式恢复。
- [x] 真实 semantic→admit→RawSource→canonical→seal_snapshot→核心Agent/Writer选证验证 Cache Domain Purge 规则身份和字面原句不丢，不能仅查fact ID存在。
- [x] 原提取/价格/条件/标题/绑定测试及SPEC→QUALITY通过后停写冻结。

### 累计复核后的设计修正

最终累计审查发现 HTML `<pre>` / `<code>` / 注释内原句被新格式恢复接受。前三版局部容器扫描不足以覆盖 Markdown 语法，故 v4 改用 CommonMark token 的原始行映射统一排除代码、HTML 与不明确容器；匹配仍只恢复字面唯一的完整原文，原 exact 路径保持兼容。增加本地解析依赖及其运行文件冻结，保留所有失败版本和探针。v4 SPEC 又证实 `<code>` 跨空行时 Markdown token map 不证明 HTML 闭合，所以 v5 明确将任何 raw HTML block/inline 文档的新非精确恢复关闭；纯 Markdown 完整正文仍按 map 恢复，原 exact 路径不变。v4 新增的出 HTML 块恢复正控随设计收紧改为拒绝，原 65 项测试与既有测试不变。Task2 重新走 RED→SPEC→QUALITY→累计审查，不能沿用 v3 的批准结论。

首次全后端门禁发现紧凑 Writer prompt 漏了原有“编辑与评论分别成条”约束；保留旧测试，修复后复验。另有 `ps` 沙箱权限导致的运行脚本测试失败，须在可检查本机子进程的受控权限下重跑。

## 任务3：Bitwarden紧凑写作传输

Files：`backend/packages/agents/writer/dimension_writer.py`、必要时新增小型私有transport helper、新增 `backend/tests/unit/test_compact_claim_transport.py`。

- [x] RED：当前Writer重复长ID导致输出膨胀；测试真实Writer实际prompt及紧凑返回经过parse、独立审核、保存、final QA。用固定响应只证明传输与守卫，不当模型语义成功。
- [x] GREEN：模型返回短支持引用、text/kind及问题计划；服务器从本次实际发送的候选映射完整fact/source/span或operation，不从模型或请求补产品事实。明确保留事实/推断及其条件。公共保存合同、模型调用轮次和输出额度不扩大。
- [x] 拒绝未知/重复/跨类型/跨产品引用、未经发送的候选和混合宽松字段；旧verbose合同兼容；未完JSON不修补发表，预算/取消/依赖拒绝继续传播。
- [x] 明确size比较与正反对照，原主张/答案/预算/证据依赖回归及SPEC→QUALITY通过。

## 根代理验收

- [x] 独立代码审查、最终全后端、变更Ruff、OpenAPI基线、构建及diff通过；既有测试不改。恢复后检查与旧helper不可用项分开披露。
- [x] 同一旧8/新4输入和源码冻结，模型各组仅首次；参考不进runtime。原v35临时helper丢失，原freeze不改，恢复记录不假称helper可重放。
- [x] 同SHA六组依次各一次，未中途修源码或选最好结果；原启动预检通过仅见会话记录，原helper/日志丢失，当前无法重新重放，不冒称新验证通过。
- [x] 延用每组24调用/80000token/2048总输出上限/重试0。进程级可选Web API，实际.env不改；旧数据及密钥不提交。
- [x] fresh只读审读正文、保存、全部发表主张（含服务器事实）、完整绑定及原子性；旧8和已曝光新4分表，空稿为遗漏，报价不足不是完整实金额正例。
- [x] 真实QA阻断与内容分别计；阶段runner固定deliverable=False，完整Graph/发布/自动发现/dense RAG本轮仍未覆盖，不推导虚假0/6。
- [x] 交付/结构化结果、README/Agent说明/正式验收更新，安全扫描及当前源码冻结重验通过；提交推送按既有授权执行，其实际远端SHA与clean状态以私有Git交付回执为准（本文是提交前快照）。

## 本轮不做

不训练、不赋奖励、不下载新权重、不改真实配置、不执行Docker、不合并main。Dropbox导航壳与Miro403保留真实结果，不在本轮未经诊断扩展采集绕行。生产稠密RAG、完整Graph和全部产品经理维度单独验收。

## 2026-10-22 收尾与证据恢复

六组首次模型运行和独立审读完成；旧八题6正确／2遗漏，新四题4遗漏，严格局部报告资格均未达标。源码不再修改，后续问题写入交付文档。

中断后/tmp原审查报告、辅助脚本、失败日志、中间源码快照与2191历史SHA清单不再可用。原冻结清单和六组原始运行产物保持，恢复阶段核749源码/输入与76依赖、重做独立代码审查和两组隔离审读、全后端6833通过／1跳过、API与构建通过；不重新调用模型、不伪造原证据。恢复初版旧组body范围修正为完整report.md，v1/v2及差异均保留。新日志直接存data/artifacts/collector-input-writer-2026-10-21/verification/recovery。Git交付以verification/git-delivery.json中真实远端确认记录为准。
