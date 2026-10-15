# 已验证事实投影与完整报告验收计划

> 用户已确认实施顺序；沿用当前 codex/pastoral-desktop 工作区，保留历史未提交修改。本轮使用 brainstorming 收敛既定设计、writing-plans 记录任务、TDD 实施、完成前验证及只读审查。当前会话直接执行，不另开任务。

**目标：** 正式事实决定矩阵、套餐及报价正文，补齐三家文档协作共同轴与价格条件，重新运行真实生产工作流并分别判定流程完成与内容交付。

**设计：** 现有封存证据和消费凭据继续负责范围与回放。价格和功能矩阵值从当前消费视图生成；模型解释不能覆盖价格、人数、套餐等正式字段。价格分析与写作采用显式有界预算，按套餐和账期保留观察。能力对照由审核通过的正文主张及其事实绑定生成，未知项保留。公开来源采集仍受网络和累计额度限制。

## 1. 定价与矩阵投影

涉及 `agents/analysts/logic.py`、`agents/comparator/logic.py`、`agents/comparator/context.py`，新增 `research/evidence/projection.py` 和 `tests/unit/test_fact_projection.py`。

- [x] 红测试：正式 Standard/Premium 行取代模型 Team/重复 Pro；年付/月付同名套餐保留为不同观察；矩阵共享编辑保持“你和最多29名队友”原文，不改写成29人。
- [x] 优先使用当前产品维度的已准入价格字段重建套餐；没有结构化事实的旧记录保留原兼容路径。
- [x] 矩阵用消费视图内的完整原文和条件生成单元格，事实摘要采用引用，消除重复的知识文本上下文。
- [x] 运行 `PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_fact_projection.py backend/tests/unit/test_comparator_context.py -q`。

## 2. 报价覆盖与共同轴正文

涉及 `orchestrator/evidence_context.py`、`agents/writer/dimension_writer.py`、`research/evidence/capabilities.py`、`tests/unit/test_dimension_writer.py`、`tests/unit/test_capability_alignment.py`。

- [x] 红测试：五条 Coda 价格全部进入同产品定价段；报价与完整条件不截断；权限中的其他禁止动作不抹掉已支持评论；正文三方表格只引用已审核主张。
- [x] 定价分支预算使用明确上限，比较汇总按各有效生产者分支预算求和；本地 QA 预算保持原回放语义。
- [x] 价格草稿仍需逐条核对金额、计费单位和账期；未知币种不推测。共同轴分别展示共享编辑、评论及权限限制，缺证不能标为产品不支持。
- [x] 运行对应写作、能力和证据工作流回归，确认跨产品、冲突、身份及旧凭据兼容检查仍有效。

## 3. 定向官方补证

涉及 `business_intel/entity_resolver.py`、`agents/collectors/logic.py`、公开浏览器采集与定价条件提取。

- [x] 验证 Coda 共享编辑与分享权限、Notion 分享权限、Confluence 内容权限的官方入口，保留结构与角色前提。
- [x] 根据实际采集失败和累计额度允许有限补证；不依赖页面数代替共同轴覆盖，不登录或绕过挑战。
- [x] 核实动态价格选择的币种、人数、账期；无法证实的条件明确留作缺口，仍展示已核实的采集观察。

## 4. 真实流程与交付验收

- [x] 先离线回放上一轮来源，确认没有重复套餐、价格漏项和人数改写，再进行实际联网采集、模型分析、比较、写作及 QA。
- [x] 后端完整回归、必要 OpenAPI/前端验证、独立只读审查。
- [x] 人工检查三方共同轴、完整已采报价、条件与引用，真实草稿原样保存；记录调用、token、费用估算、健康依赖和未通过项。

验收要求：矩阵不制造套餐和人数结论；已采年付/月付报价不因短上下文遗漏；每个共同轴有三方已审核观察或明确补证缺口；只有满足用户要求覆盖及主张审核的报告才能称为可交付，工作流 completed 不能替代人工判定。

执行完成；基础覆盖通过、采购交付尚未通过。详见同日 fact-projection-results.md，勾选表示执行过该步骤，不表示所有交付条件通过。
