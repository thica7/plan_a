# 任务语义选证、局部重写与正文／QA一致性交付

## 本轮范围

按已确认计划，修复 Trello、1Password 已采证据的语义选用，Cloudflare CPU账单依赖与运行时规则混写，以及正文、问答和最终QA的状态差异。复用现有隔离分支，不新增服务、Docker或训练。实施计划见[计划](2026-10-31-semantic-delivery-plan.md)。

两轮真实复验及独立内容审计均已完成。续修最终3/8原题完整、5部分；文本／证据／全主张原子报告各1/4，严格系统QA仍0/4，项目尚未达到整体交付标准。两个实验开关继续默认关闭。任务始于2026-10-31，本机最终验收续至2026-11-01，文件名保留任务起始日期。

## 首轮真实正文结果

8原题中1完整、6部分、1失败；22必要分支9完整、1部分、12缺失。6条唯一可见主张全部完整支持，5条严格原子；文本、文本加证据、全主张原子及严格系统QA四种报告口径均为0/4。

| 产品 | 最终正文实际交付 | 未完成内容 |
| --- | --- | --- |
| Trello | 下载、导出及完整改权角色 | A／B投票、义务、Workspace、跨板传播及计费身份 |
| Cloudflare | 给定scope通则、拒报准确账单并请求CPU输入 | 特定域权限及跨域结论、CPU独立计费依赖 |
| Bitwarden | 两项必要澄清 | 合理集合上限推论被新premise守卫误阻，容量结论未发表 |
| 1Password | 无Private vault、拒编人民币含税总价 | 两vault结果；模型两次选择已标不适用的邀请ref；报价规则原文仍缺 |

本轮112次实际模型传输、416918已知token、未知用量0；25项最终QA全部送达有效、未送审和超时均0。全后端9508通过／1跳过／250警告，测试前后源码身份相同。正确派送与单测通过不代表正文通过。

见[首轮脱敏结果](2026-10-31-semantic-initial-results.json)，原样正文：[Trello](reports/2026-10-31-semantic-initial-trello.md)、[Cloudflare](reports/2026-10-31-semantic-initial-cloudflare.md)、[Bitwarden](reports/2026-10-31-semantic-initial-bitwarden.md)、[1Password](reports/2026-10-31-semantic-initial-1password.md)。16原件与生产依赖、精确引用及真实派送／receipt均经新的独立内容审计，结果一次性封存。

## 实际接线

新鲜实验执行使用内部 `semantic-target-clauses-v2`，外层继续 `selected-task-atoms-v3`／`task-outcomes-v1`。`WRITER_TASK_EXECUTION_ENABLED` 与 `WRITER_QUESTION_ATOMIC_ENABLED` 仍默认关闭，须同时显式打开。已有Writer消费记录保留其持久化合同；旧单谓词v1、旧v1／v2／v3与历史SYSTEM不被升级。

| 阶段 | 本轮实际行为 | 仍须验证的边界 |
| --- | --- | --- |
| SELECT | 从精确任务及唯一绑定父题建立限制性语义目标；区分邀请与当前访问、计费导航与实际规则；服务端再次核所选ref | 标题／URL只能限制适用范围，不能证明产品事实；语义可选不等于已受原文支持 |
| GEN | 只处理当前任务；CPU任务聚焦账单所需CPU输入，保留完整所选原句、条件及例外 | 不复制费率／运行时清单，不把其他独立产品规则藏入premise |
| REVIEW | 逐子句检查目标、来源与原子性，再执行原引用和操作守卫 | 真正的AND条件／例外保留；整体supported或count=1不足以证明合格 |
| 局部补交 | 证据语义不合时重新SELECT；纯表述失败可认证复用原SELECT；每失败项最多一次 | 原span／输入输出哈希、快照与任务身份不变，成功peer不被覆盖 |
| ANSWER／正文 | 从实际已审核任务结论汇总；显式辅助依赖不重复算用户待答分支；必要澄清创建空事实qid | 不跨任务借复合claim填缺口，未审核或未发表结论不能提升answered |
| 最终QA | 接收同一认证发表结论及纯AND单上界反例语义 | OR、独立多问、未覆盖例外仍阻断；历史finding不自动全部清除 |

Collector、Analyst、Comparator、Reflector没有被替换；其有效分析、比较和反思产物仍实际进入Writer。请求条件保持为请求条件，来源事实仍从已准入快照读取。

## 离线发现与修复

- 同句“已接受邀请并被确认”的历史事件曾把当前访问问题误分为邀请；中英文红测后修正内部请求动作分析，原始问题与完整父题不改，真正邀请动作仍保留。
- 非字符串`atom.text`曾在失败诊断中抛异常，阻断整段写作。8种JSON值的真实mock执行均验证局部拒绝、成功peer一次、补交和认证replay；诊断只记空摘录／类型，原失败全文留在trace，不序列化大对象进入必留字段。
- SELECT／REVIEW曾收到GEN专有字段定位。新合同按阶段发送定位说明；旧三个SYSTEM及新GEN逐字节不变。
- 真实旧Cloudflare快照的新合同离线mock先复现0 GEN：初稿投影14172字节超窗。仅移除重复任务投影及未选来源限制，完整任务、所选quote、必要条件与全部上游约束保留；修后实际2 GEN＋1 REVIEW，补交wire13981字节，replay一致。此项明确是离线mock，不能计为真实模型质量提升。

完整user输入仍按`min(14000, use.max_bytes)`校验；短指令及诊断有UTF-8总界，超窗只压缩诊断摘录。压缩后仍超窗须记录真实本地延期，不截任务／证据、不伪造LLM派送，不增加全局预算或最终QA保护上限。

## 首轮工程验证

单一作者最终集中回归444项通过，变更12份Python的Ruff新增0、存量1。独立规格分轮验证259、8、5项；最终独立质量156项通过。两次初审阻断和红记录均保留，最终版本才进入全量与真实模型复验。

首轮生产Python SHA256为`1b16775b11592ead1e1c7d4aee31d3f4f92471b02fd486bb3bad572f156947ac`；源码manifest为`3c227324c9a82814f183ca145bc491494fe1956d2715b6eaa0b743da48fb3d7b`，完整源码ZIP为`5107ca14efecd7175bb14c68fab3e8b09942e866967c20875f058dad1fbd3037`。897件归档逐成员核对；全部中间候选及其冻结仍保留。

标准工具在最终源码上新生成API／TS并逐字节相同。前端260文件与先前340测试和构建的验证版本相同，本轮不把旧前端结果说成新跑通过。

## 续修：从首轮真实失败定位到的改动

首轮实际CPU任务同时收到“写额度／费率”和“只写账单依赖”；续修直接替换冲突的任务指令。精确补交反馈改为指出实际REVIEW失败的子句、作用和任务不符，完整失败运输身份继续保留。

Bitwarden的真实集合稿已获source REVIEW支持，但必要来源前提被新守卫一律拒绝。续修复用既有typed quantity witness，只为本任务、本claim实际所选原始span和唯一父题签发同单位、同上限前提资格；人数描述、OR、未核条件及独立产品规则仍不能通过。Trello“前提是……”及“在……前提下”的正常条件曾被误抓为额外能力句，新语法范围只用于新V2，闭合后的第二动作仍拒绝。

1Password两次选择邀请only引用，服务端正确拒绝；同窗已有current-access原文。续修将明确False引用移出真正正向可选目录，完整quote保留作restriction-only，neutral不代表已获支持。断言侧仅前置拒绝明确邀请谓词／新动作；过去接受邀请、邀请者等actor关系和未知措辞继续经过原独立逐子句及源审，原文和source eligibility不改。真实源审unsupported负例仍无发表。

最终续修相对首轮只改3个生产文件、2个测试文件；对Git基线累计13份Python。集中482项通过，Ruff新增0、存量1。规格对五点170项及后续9／18项增量独立核对，质量先206项、最终75项及原三例完整路径复验；初审阻断、红测和中间冻结均原样保留。

实际本轮快照的离线mock：Cloudflare故意混运行时初稿被拒后，真正补交GEN13863字节、1次REVIEW通过；1Password为2次GEN、2次REVIEW。原始run／snapshot不改，完整任务、quote、scope、请求及上游约束保持，重放claims／reviews一致。跨候选执行ID和派生hash会变化，不能把结构、SYSTEM哈希及运输字节数相同说成整个wire字节相同。这些均为离线mock，不计真实报告提升。

续修最终生产SHA256为`ba611bf40cb3155633ed4b639d838ac08b852446b70d5bfedc1e06875b67072e`，源码manifest为`81aed349234e7001c489f2c00bc4f1e533f2f809b1959372aec6f630377fb753`，完整ZIP为`68fb262429e40d2563d981aeb95d5c4efe8d8f1210f4698f367571e3b1724d85`；898件源码／测试等归档逐成员核对。822件此前原件与1364件更早原件继续锁定。最终API／TS重新生成字节一致，260前端文件未改；本候选在两审通过后才启动全量及四家真实复验。

## 最终真实正文与QA结果

| 产品 | 已实际发表的结果 | 仍缺的必要内容 | 文本／证据／原子／严格QA |
| --- | --- | --- | --- |
| Trello | A禁用投票时的否定、下载、导出、完整改权角色 | B投票、是否必须投票、Workspace统一设置、B权限、完整计费判断 | 0／0／0／0 |
| Cloudflare | 特定域角色规则、给定域scope和跨域权限否定 | CPU独立计费依赖；仅请求补CPU输入不足以回答该分支 | 0／0／0／0 |
| Bitwarden | 两集合上限否定3集合需求；操作与归属两项必要澄清 | QA仍保留早期上下文不足及coverage阻断；观察区尚未展示该推论 | 1／1／1／0 |
| 1Password | 无Private vault；拒编精确人民币含税总价 | 两vault结论、公开报价性质、有证官方报价下一步 | 0／0／0／0 |

同8题最终3完整／5部分／0失败；22支13完整／2部分／7缺失。按整答案所选两条claim的合取支持口径，10条唯一正式主张均完整支持，9条严格原子；Trello复合“是”非原子。若逐render行只允许该行单绑定支持，则9条完整、1条部分支持。两种口径均不改变原题得分或四报告交付结论，不能只取较好口径宣传。

最终113次真实模型传输、417730已知token、未知用量0；各家43／28／20／22次。29项最终QA全部实际送达有效，无未送审或超时；QA已执行不代表通过。全后端**9546通过／1跳过／250警告**，543.77秒，测试前后源码身份一致。源码无漂移、16原件及全部引用／依赖／真实SELECT-GEN-REVIEW-ANSWER receipt重建均经独立核验。

结果见[最终脱敏结果](2026-10-31-semantic-final-results.json)，四份原样正文：[Trello](reports/2026-10-31-semantic-final-trello.md)、[Cloudflare](reports/2026-10-31-semantic-final-cloudflare.md)、[Bitwarden](reports/2026-10-31-semantic-final-bitwarden.md)、[1Password](reports/2026-10-31-semantic-final-1password.md)。首轮五份公开结果、所有失败及其冻结源码不覆盖、不追溯改判。

两轮合计225次传输、834648已知token。本地历次已记录累计972次／3449959已知token，另一次历史`/models`GET单列；不是供应商账号账单，实际费用未知。相同别名、温度和资料下，上游仍重新生成且供应商权重未确认，因此不把分数差异当严格因果或降本对照。

## 实际仍未解决的交付链

1. **选证正确后仍自由复写原段。** 1Password本轮SELECT已选current-access quote，但GEN47同时写Private与容量，补交56又写成邀请上限；两稿均被拒。CPU目标冲突已去除，GEN67仍复写费率和运行时，75改写为计费条件，未交付所需依赖。这些属于生成未履约，不能归为没抓到资料或未派送。
2. **正文交付与历史问题状态仍有差距。** Bitwarden正文已给上限否定与合理澄清，QA仍保留早期“Q1／Q2上下文不足”和`answer_coverage_incomplete`阻断；观察区仍空。不能以正文合理为由批量清掉finding，也不能据这些旧状态否认已发表内容。
3. **确实缺失的资料要单独补抓。** 1Password报价原始capture不完整，需重新抓取并认证完整定价／FAQ，再入库和更新独立测试，不能借历史孤答补事实。

下一步应让GEN输出可核验的关系字段：主体、单一谓词、对象／上限、前提、来源引用；经审核后由同一已验证结论对象渲染正文、问答及QA。CPU计量输入与运行时限制、当前访问与邀请应成为不同关系；QA问题显式绑定task／question及解决它的结论ID。这样能直接验证交付契约，再继续现有8题与新样本验收。

## 内容验收范围

四家固定2026-10-21网页，8道既有暴露原题、22个必要分支，真实七生产阶段回放；每家64calls／240000tokens／配置费用上限0.25美元，温度0、重试0、最多两家并行。保留全部结果，由新的独立内容审查者按最终正文和每条实际所选quote判断。

固定资料中的1Password定价capture明确不完整，原提取返回空facts；历史FAQ诊断只有孤立答案，缺完整问题、原文绑定与正文认证。它不能作为报价规则或官方下一步入库。此类缺口继续保留，不放宽原文准入去填答案。

四家是分别启动的功能逐题回归run，未验一次四产品横向比较矩阵或其他PM维度。本轮不证明新网页抓取、2026-11-01实时性、盲测泛化、全Graph、生产语义RAG或数据库全链路。模型别名是`deepseek-flash`，未确认供应商具体权重版本。调用和token只按本地实际记录统计，供应商账单未知。未执行Docker或训练模型，本机持久化演示服务未停启。

## 离线复现

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=backend:backend/tests:backend/tests/unit:backend/tests/integration \
../plan_a/.venv/bin/python -m pytest \
  backend/tests/unit/test_task_semantics.py \
  backend/tests/unit/test_semantic_delivery_status.py \
  backend/tests/unit/test_task_clauses.py -q --tb=short
```

上述venv为本机执行路径；其他机器按README安装依赖后使用自己的Python环境。仓库测试使用自包含资料，不依赖被忽略的真实运行目录。未提交凭据、数据库、模型权重或私有运行原件。
