# 角色、套餐与访问条件绑定实施计划

> 本轮按 executing-plans 内联执行。用户已批准“先修条件抽取绑定、资料投影，再补真实缺口并完整复验”；复用当前工作树，保留此前未提交改动。已使用 brainstorming 审核实现选择：仅扩大关键词会漏章节/表格；扩大上下文与模型额度增加成本且不解决归属；采用可验证章节、原文条件和角色表的通用解析，并无损去重写作输入。

**Goal:** 让已采官方资料中的行动角色、适用套餐、操作对象与访问前提进入同一证据链，减少矩阵与正文遗漏，并据四家真实流程判断是否可交付。

**Architecture:** 清洗保留能唯一定位的官方标题，提取仅使用当前章节及原文角色表。结构化条件与原文引文同源且在准入重算；矩阵、写作和补证使用同一操作观察。对重复引文/条件采用无损引用，不扩大单任务200000 token/60调用。

**Tech Stack:** Python、lxml/trafilatura、Pydantic、LangGraph、DeepSeek、pytest。

## 1. 清洗与原文结构

文件：`backend/packages/tools/fetch_page.py`、`backend/packages/research/extraction/semantic.py`；测试 `backend/tests/unit/test_qualified_operations.py`。

- [x] 重放上一轮Nuclino原始模型输入与实际官方HTML标题：6条模型节选全部未准入，body中0个标题，章节定位为None。
- [x] 先写标题保留失败测试：正文含前后两角色章节，标题应回到对应唯一正文锚点之前，不混入导航或给重复锚点猜位置。
- [x] 清洗仅插入有唯一正文锚点的原始标题；quote偏移仍针对最终捕获正文验证。
- [x] 加入角色/权限规则及连续角色表的确定性节选，通过同一semantic准入；不能只因为官方域名就接收任意内容。

## 2. 条件解析与绑定

文件：`backend/packages/research/evidence/operations.py`，必要时新增同目录有界辅助模块；测试 `test_qualified_operations.py`、`test_operation_comparison.py`、`test_semantic_extraction.py`。

- [x] 失败样本：`⭐️ Available on all plans.`须为相邻功能绑定套餐；其它角色专属套餐不可补到本角色。
- [x] 失败样本：Can create/Can manage、Doc Makers、角色表列头、套餐枚举、item/document/folder对象、shared/parent access及否定各自保留原文。
- [x] 角色表只消费同一连续表格内的列头/行与明确允许或禁止标记，保留单元格限制与脚注；未知或坏列数保持未知。
- [x] 新准入与snapshot消费都重算结构，注入role/plan/前提、篡改位置仍拒绝。

## 3. 矩阵和正文投影

文件：`backend/packages/agents/writer/dimension_writer.py`、`backend/packages/agents/collectors/logic.py`、`backend/packages/research/pipeline.py`；测试 `test_qualified_operations.py`、`test_dimension_writer.py`、`test_report_claim_audit.py`。

- [x] 写作输入对同事实重复引文/条件使用无损引用，在原14000字节内选入更多不同操作；审核能还原完整条件，不截断原文。
- [x] 保留服务端操作目标及对象/行动角色绑定；角色名与评论UI不能冒充操作。条件未知、源有但正文未发表分别显示缺口。
- [x] 已采规则先确定性入库，剩余语义调用选择仍缺的页；已有条件不重复搜索，补证按实际缺口执行。

## 4. 验收与交付记录

- [x] 先红后绿，相关回归与独立代码审查。
- [x] 完整后端回归与固定四家standard/feature真实流程；同原200000 token/60调用。
- [x] 核对24格的来源、正文、角色/套餐/对象/前提、肯定/否定与审核状态。不能用completed或单元测试通过代替语义交付。
- [x] 保存脱敏结果、原始草稿、代码SHA；扫描凭据、检查diff；记录Temporal/Qdrant HTTP/生产部署未验收。

测试命令前缀统一为 `PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest`。

## 最终验收记录

后端3567 passed / 1 skipped / 152 warnings，独立最终审查300 passed。已执行三轮四家真实完整流程；最终来源观察20/24、矩阵审核观察18/24、核心字段完整8/24（允许观察7格）。完整同口径比较仍未通过：4个来源缺口、2个投影遗漏及角色/套餐/访问条件待核实。清单完成表示实现、尝试补证和验收记录已执行，不表示所有缺口已关闭或报告可交付。详见`2026-10-13-qualified-operations-results.md`及JSON。
