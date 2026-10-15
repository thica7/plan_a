# 操作投影与真实缺口补证计划

> 使用 executing-plans 在当前已隔离工作树内执行。用户已批准本轮方案与真实测试；沿用既有交付目录，不重复确认。保留所有此前未提交改动，本轮不合并或推送。

**Goal:** 修复Notion创建遗漏、纠正Coda分享误分类并采集真实规则，再检查四家六项操作的角色、套餐、对象与访问前提和报告交付状态。

**Architecture:** 继续共用原文绑定的操作解析器，中文主张与原文操作使用相同动作边界。补证先使用已抓资料，再依据实际缺失操作及字段选择官方资料；不将共享UI名当动作、不借其它角色套餐，不放松准入及逐条审核。

**Tech Stack:** Python、Pydantic、LangGraph、pytest、现有DeepSeek/search/fetch。

## 已确认根因与设计选择

上一轮Notion事实明确分配create/edit目标，正文“创建和编辑数据库内的页面”只匹配edit。Coda选中的quote只描述修改访问权限，`sharing dialog`误匹配share，导致模型用相同权限主张填两个目标后被去重。

扩大全部中文关键词会引入UI和接收者误判；增加模型字段涉及存储和历史协议。采用局部有界动作规则修正，并用原文真实分享规则补证。未知条件仍显示未知；不把来源数、completed或非空字段作为准确率。

## Task 1：先修操作边界

修改：`backend/packages/research/evidence/operations.py`；新增测试：`backend/tests/unit/test_operation_projection.py`。

- [x] 写失败测试并确认红：

```python
assert operation_matches_text('create', '成员可以创建和编辑数据库内的页面。')
assert not operation_matches_text('share', 'You can change a user’s access on the doc by modifying their access directly from the sharing dialog')
```

- [x] 中文create仅接受有界数据库/文件夹/工作区限定语与页面/文档/内容对象；协调编辑/删除句先保留create动作。排除创建权限、模板、评论以及未知对象。
- [x] 原文share忽略sharing dialog/settings/menu/button名及UI操作，保留同句中独立明确的share权限动作；英文与中文正反例回归。
- [x] 通过审核主张+原文fact重放Notion创建矩阵格；共享UI权限规则不得填分享格，明确分享动作及否定按同一准入回归。
- [ ] Coda真实联网分享规则进入审核和矩阵；当前网页抓取失败，本轮不能记为已关闭。

Run：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_operation_projection.py backend/tests/unit/test_operation_comparison.py backend/tests/unit/test_operation_coverage.py`。预期：新测试先出现对应断言失败，修复后全通过。

## Task 2：已采资料与真实缺口

涉及：`backend/packages/research/extraction/semantic.py`、`backend/packages/research/evidence/operations.py`、`backend/packages/research/capture/selection.py`、`backend/packages/research/repair/strategies.py`、`backend/packages/research/pipeline.py`；必要时更新`backend/packages/business_intel/entity_resolver.py`内已核实官方入口。

- [x] 将原始捕获与模型输入逐层核对，区分未抓、未准入、未选入、未审核和未投影。
- [x] 核实Nuclino创建、Confluence角色/评论/阅读和Coda分享原文；保留来源URL、hash与时间。网页失败不得当成功。
- [x] 为已确认的新增结构/选段问题先写原文失败测试；只改导致资料遗漏的规则，保留角色专属条件、否定、套餐分支及父级要求。没有官方套餐依据时保持未知。
- [x] 基于操作缺口选择剩余官方候选与查询，优先缺operation_evidence，再针对未知角色/套餐/前提，不用所有操作拼一个宽泛查询；总fetch/candidate/search/token/call上限不增加。

## Task 3：完整复验与交付判断

- [x] 相关回归、完整后端测试和独立代码审查；发现具体反例再补回归。
- [x] 执行固定四家完整真实流程：

```sh
PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python backend/scripts/eval_live_products.py --cases eval/operation-comparison-v1.jsonl --case operations-four-products --output /tmp/plan_a_operation_projection_live_v1 --timeout 600 --live
```

- [x] 核对24格的原文、角色、套餐、对象、允许/禁止及前提，审核支持与真实可比较分别记录。保留原200000 token/60调用，报告仍有缺口时如实判未交付。
- [x] 保存脱敏summary/24格/审查/代码SHA及原始草稿；扫描实际凭据、检查diff。记录Temporal/Qdrant HTTP/生产服务未验收。

不新增前端、训练或模型下载，不靠手工填写厂商答案使验收通过。

## 实施补充与复验状态

已实现两列角色定义、第三人称动作、已采明确权限规则选段、核心完整操作优先、同操作且同对象的套餐容量分支、缺少操作证据优先的补证与末尾metadata保留。新增Nuclino创建、Confluence角色FAQ和Coda分享控制官方入口。独立审查发现的跨doc/page套餐借用、末尾补证目标丢失及真实sharing动词遗漏均以反例先红后绿修复；真实v2另外发现相邻角色条件污染与接收者share从句误判，已修复原文条件与动作边界。

勾选表示实现、补证尝试和验收工作已执行，不表示全部证据缺口已关闭。四家v4发现高级抓取正文丢失角色章节，Nuclino阅读/评论证据未准入；追加修复与审查后以最终v7验收记录为准。最终后端3623 passed / 1 skipped / 152 warnings。

### 验收中发现的高级抓取结构问题

高级抓取依赖BeautifulSoup，但后端依赖未声明且当前虚拟环境缺少该包。清洗选段又可能删除原HTML章节标题。补齐后端依赖，并在高级抓取的每个候选正文中，仅依据唯一匹配的原HTML内容块恢复标题。重复或缺失锚点不恢复，导航/页脚标题不恢复，不扩大无章节条件池和证据准入上限。保留表格及正文原文，并用角色页真实抓取、完整后端回归、独立审查和最终四家v5验证。

v5继续发现同分时更长的逐节点正文胜过清洗表格。修复同分清洗方法优先级，更高质量正文仍优先。独立审查另外复现单行多章节错位、原HTML重复而正文去重、隐藏标题/隐藏祖先等问题；basic和advanced恢复改为原HTML与正文双重唯一，按精确锚点插入，排除显式hidden/aria-hidden/display:none/visibility:hidden标题。相关反例先红后绿，最终四家v7使用补丁后同一SHA，避免混合代码版本。
