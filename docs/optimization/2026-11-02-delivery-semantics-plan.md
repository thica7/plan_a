# 问题交付语义与证据发表实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development，单作者逐项实施，独立规格审查通过后再进行质量审查。

**Goal:** 修复合理澄清／缺项答复的 QA 误判，使权限及并列操作的已采事实完整发表，并补齐 1Password 当前官方报价规则证据，再如实验收四家报告。

**Architecture:** 继续使用已有逐任务源审和版本化结论集合，统一问题交付判定与最终正文，不放松事实支持要求。源事实未知、需要用户输入与真正未回答分别记录；有限权限／数量关系由已审核原文和独立标记的题设推导。旧派送、receipt、SYSTEM、缓存身份和历史文件保持可重放，新增语义须有显式版本／新缓存依据。

**Tech Stack:** Python、现有 Agent/QA contracts、httpx/lxml、pytest、RunJournal、原生 PostgreSQL；无 Docker、Kafka 或模型训练。

## 已确认根因与边界

- 基线为 `e177d38a`，前轮真实报告严格 QA 0/4；独立文本 1/4，原题 3/8，必要分支 12/22。旧 artifact 不覆盖。
- Bitwarden 的必要澄清通过 source/support 验证，但最终模型把等待澄清后才可回答的产品结果当作本轮漏答。Cloudflare 的 `billing_input_gap` 通过结论 authority，却仍进入通用完整事实审核；旧价格 verifier 和维度 context gate 又否定该结论。
- Trello / 1Password 多项独立源审已支持的句子，在服务器逐子句审核中被判混合或不独立；Cloudflare 的真实 GEN 又因中文谓词表达被拒。不能简单清除审核或扩充措辞补丁。
- Trello 下载／导出虽已分 task，却共用复合问题作子标题，导致整体“是”和“未知”并列。每个操作只投影自己的结论，父题仍覆盖全部必要任务。
- 本轮已通过真实生产 HTTP 抓取 `https://1password.com/pricing`：200，登记来源认证通过；完整答案在实际 HTML 中，但图标按钮无正文、问题在相邻 h3，现有 disclosure 提取返回 `empty_disclosure_question`。须通用修复精确 DOM 绑定，不能用网页搜索摘要冒充入库事实。

## Task 1：统一交付判定与 QA

文件：`backend/packages/agents/qa/{question_context,question_reconciliation,independent_question_review,evidence_alignment}.py`；必要时新增同目录小型交付判定模块；`backend/tests/unit/` 和 `backend/tests/integration/` 相应自包含测试。

- [x] 先红测实际语义：必要的操作／所有权澄清可以完整交付，但密码留存事实仍未知；已支持 CPU 计费依赖和真实缺项答复可以完整交付，但精确金额仍未知。
- [x] 统一 `question_delivery_complete`、`_answer_support` 与维度 citation/context gate，依据同一已验证 authority、最终可见内容和 task scope。
- [x] 独立 QA 的审核目标明确区分直接回答、必要澄清、有证限制和真正漏答；绑定新协议／缓存身份。不能要求模型将未知事实标记为已知，也不能接受删掉必要澄清字段的回答。
- [x] 保持反例阻断：原输入已给、缺源规则、伪造 authority、未发表 observation、遗漏权限分支、混合／未绑定历史 finding、源错绑。修 CF 计费不清掉跨域权限真缺口。
- [x] 针对性红→绿及旧协议 raw/replay、坏 JSON、QA 缓存、真漏答反例回归；单作者停写后先规格再质量审查。

Task 1 已经规格与质量复核通过：作者最终矩阵 286 通过；质量发现的 binding version 漏检已红→绿修复，受影响测试 162 通过，质量独立复核 86 通过。旧协议与负面审核保持，尚未执行四家模型验收。

验收断言（使用真实测试工厂，不伪造业务 verifier 成功）：

```python
assert clarification_delivery.complete is True
assert clarification_delivery.fact_status == "unknown"
assert billing_gap_delivery.complete is True
assert omitted_permission_delivery.complete is False
```

## Task 2：权限、并列操作和完整报价证据

文件：`backend/packages/agents/writer/{structured_conclusions,conclusion_publication,selected_task_delivery,task_answer_outcomes,atomic_question_projection}.py` 及真正必要的源审绑定模块；`backend/packages/tools/fetch_page.py`；必要的 `backend/packages/research/extraction/` 报价规则适配；单元与业务接线集成测试。

- [x] 先复现失败：所选完整原文已含权限／访问上限，但自由复合句被逐子句 gate 拒；不能靠取消 gate 让复合主张通过。
- [x] 在现有明确版本分支内使用有限、服务器构造的单关系候选：每条操作／资源／权限规则独立，候选只来自真实 SELECT 和原文。模型选择候选、独立源审规则、服务器结合唯一题设得出有界结论，保留完整引用和条件。
- [x] 当前可访问一个 vault 的规则只推出同时两个不满足；不将“邀请一次”或其他单位当当前访问基数。域级权限不自动推出同账户其他域权限。可以、必须和计费分别回答，不互相推导。
- [x] 子问显示其实际操作标签／quote；复合父题全部必要子问完成才可整体肯定。unknown 不被一个已回答 sibling 掩盖；既有纯 AND 单个已证反例否定保持原语义。
- [x] 通用 FAQ 恢复仅接受精确控制器／panel 与可证明关联的相邻标题，唯一 DOM 身份、可见祖先及范围检查均保留。空／重复／歧义／跨 main／隐藏祖先反例继续拒绝。不从 aria-label 自造原文问题。
- [x] 用已捕获真实 HTML 离线重提取完整官方问题和答案，保存新 hash、完整 question+answer、offset、来源认证；随后按生产 capture/extract/qualify 入库，不人工塞 snapshot 或取消缺口。新 1Password 证据与旧 10 月固定资料区别记录。
- [x] 报价只发表有证的定制报价性质和官方销售下一步；没有金额时仍拒绝精确人民币含税总额，不能制造汇率／税费或套餐价格。
- [x] 红→绿、自包含真实接线、负例、冷重建、旧合同隔离测试后，先规格 APP 再质量 APP；不修改旧验收标准。


Task 2 经独立规格与同一质量审查者复核通过；质量原反例及必要正例 12 项、权限集成文件 60 项通过。原失败记录保留。最终源码清单与 ZIP 已冻结；真实流程结果仍待验收。

## Task 3：最终验收与发布

- [x] 冻结最终源码清单、ZIP及运行脚本后停止代码写入；验证源码前后相同。全后端 pytest，原生 PostgreSQL 临时实例由既有测试流程启动，生产演示服务不停止。
- [x] 四家同 8 原题／22 必要分支、同模型配置、temperature=0、retry=0、每品 64 调用／240000 tokens／配置 0.25 美元、最多两家并行。新 1Password 定价资料明确标记，不声称完全同输入因果比较。
- [x] 最终 QA 统计 planned/sent/valid/unsent/timeout；如超窗真实保留失败。记录实际调用与 token，不把离线 mock 算真实效果。
- [x] 独立按最终可见正文评分：原题／分支覆盖、引用支持、原子性、严格 QA 四口径分别报告；不得用已入库未发表事实替正文补答。
- [x] README、各 Agent 执行说明、交付报告、脱敏统计和四份原样报告更新。明确剩余问题及下一步，不宣称已达标，除非独立正文及系统 QA 都通过。
发布检查：精确暂存与实际凭据扫描（不输出密钥）。按既有授权 normal commit / push 当前 `codex/pastoral-desktop`，以最终远端核验为发布依据；不 force、不合并 main。

## 运行命令与不可变记录

### 首轮验收后的定点续修

首轮源码和全部原件已冻结，四家模型共 122 次传输、466744 已知 token，未知用量 0。全后端 9704 通过／15 失败／1 跳过，源码前后不变，不能发布为通过。

续修按真实失败执行，不扩大产品规则覆盖、不借未选证据、不抬高 14000 字节／19702 最终 QA 预留或全局 240000 token 限额：

1. 先修复全量暴露的旧路径／合同兼容性。逐项区分真实回归、测试 double 签名及旧协议夹具，保留原负面安全断言。
2. 将问题级 QA 的可见观察限制为当前问题实际发表的结论。Bitwarden 两项澄清已全交付，但 Q1 观察混入 Q2，两次响应缺 typed gaps 后耗尽审核尝试。全局主张审核继续覆盖整份正文，不能通过漏给当前题真实事实绕过审核；新输入语义使用明确身份并保留已有合同重放。
3. 按任务要求完整选择角色、操作和范围；缺必要关系时走有界重选，不借同页未选事实。Cloudflare 首轮只选范围规则，随后应用结论的回答超窗；修复重复上下文并核对实际 ANSWER 派送。
4. 校正 SELECT 与 ANSWER 的真实上下文和联合预留。Trello 谁可改权、成员身份两任务在 SELECT 前被 107129 token 的交付预留阻断；不能把未派送说成模型不支持。按实际有界任务包计算，仍保留最终 QA 额度及未知任务。
5. 只读定位 1Password 双 vault 漏答的真实链路，再最小修复；新报价证据已成功发表，保留缺精确人民币含税金额的事实边界。
6. 单作者停写后依次规格、质量复核；冻结第二候选及新运行目录，重跑受影响测试、全后端和四家真实流程。首轮原件、失败、金标与模型配置不覆盖。

```bash
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=backend:backend/tests:backend/tests/unit:backend/tests/integration \
../plan_a/.venv/bin/python -m pytest <本任务明确测试文件> -q --tb=short
```

新私有证据目录为 `data/artifacts/delivery-semantics-2026-11-02`。真实 batch 仅由现有私有配置加载凭据（不打印）；固定网页模型流程不冒充新联网发现、生产 RAG 全覆盖或 Docker 部署验收。

本计划沿用用户本轮已批准的修复顺序与验收目标，继续执行，无需再次请求流程选择。

最终内容为8/8原题、22/22分支完整，当前QA4/4、严格系统QA2/4；工程最终9766通过／1跳过，残留真实限制及完整统计见[交付文档](2026-11-02-delivery-semantics.md)。原失败不覆盖，两个实验默认开关继续关闭。
