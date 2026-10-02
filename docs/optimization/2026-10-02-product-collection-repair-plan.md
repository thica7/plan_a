# 产品采集根因修复计划

用户已确认先解决上一轮实测问题。本轮执行已确认的采集修复方向；新增语义模型部署、RAG 两套接口合并及草稿交互另列设计，避免同时改变检索和发布规则。

**目标：** 减少无关搜索与正文噪声，使采集覆盖以已准入产品事实判定；复验真实非 AI 产品报告，并给出当前 RAG 的实际能力、局限和升级方案。

**架构：** 保留现有 SearchClient、ResearchBrief、EvidenceItem 与发布门禁。查询只描述当前采集主体，HTML 抓取复用已有正文抽取依赖，保留段落与规格行。产品分支覆盖检查要求匹配主体、维度、成功抓取页和 accepted 事实。

**技术：** Python / pytest / trafilatura / 已有 DeepSeek 搜索与运行预算。当前隔离工作区使用 executing-plans 顺序执行。

## 任务 1：查询主体与产品范围

修改 `research/discovery/planner.py`、`community/query_planner.py`、`agents/collectors/logic.py`、`agents/collectors/kb_bridge.py`；测试 `tests/unit/test_product_query_scope.py`。

- [x] 先写并运行失败测试：Steam Deck OLED 的功能查询不得携带 Nintendo Switch 2 调研标题；产品社区查询不得含 context window / agent mode；产品 KB 查询不得拼入编码工具 skill 描述。
- [x] 产品功能首查询采用当前主体 + official specifications features；价格 / 用户场景分别使用 pricing purchase cost / customers use cases。后续查询可补类别与市场，但不拼入其他产品名的任务标题。
- [x] `build_community_queries` 新增可选 `product_category`；有产品类别时使用通用购买、使用、功能限制与用户评价意图。产品存在但类别为空时采用通用产品意图；旧未指定产品的 AI 模板保留兼容。
- [x] 采集器和 KB 查询使用同一产品查询；产品分支搜索提供 en / zh 偏好，并保留 trace 中软过滤说明。
- [x] 回归上述新测试及已有 community / target_product / research_modes 测试；通过独立规格与质量审查。

## 任务 2：正文结构

修改 `tools/fetch_page.py`；测试 `tests/unit/test_product_page_text.py` 以及已有 webfetch / SSRF / evidence_fetch 测试。

- [x] 失败测试使用 nav + main + table + footer HTML：正文不含导航与页脚，屏幕和存储规格保持不同段落。
- [x] HTML 转文本优先使用既有 trafilatura 的正文和表格抽取；抽取为空时保留现有安全文本回退，不修改 HTTP、SSRF、重定向和 PDF 处理。
- [x] 正文哈希按实际抽取结果生成，不用旧正文哈希冒充新版本。
- [x] 验证短 HTML 回退、规格文本、长导航 / 页脚、XHTML 声明、深层 DOM 和异步响应及已有抓取安全测试；独立规格和质量复审通过。

## 任务 3：产品事实覆盖

修改 `research/coverage_contract.py`、必要的 CandidateIntent 类型及 `research/capture/selection.py` 的产品候选选择；测试 `tests/unit/test_product_fact_coverage.py` 及 research_pipeline。

- [x] 先复现错误：成功抓取的功能页、零 accepted EvidenceItem 当前 passed=True。
- [x] 产品非价格分支以匹配 competitor / dimension 的 accepted 事实及其成功抓取页计数；要求至少 target_source_count 个独立来源。拒绝其他产品、其他维度和失败页的事实计入覆盖。
- [x] coverage 返回明确缺口及定向补采提示；沿用现有修复流程，不降低最终发布门禁。
- [x] 正例验证来源数达到目标才通过，负例验证重复同页、错误主体与拒绝事实不能通过；同 URL / 同正文的关联重复合并，排列顺序不改变结果。
- [x] 产品非价格分支建立目标来源数的首批和候选上限内 overflow 队列，沿用 pipeline 已有补抓循环按实际网络抓取执行预算；验证首批无事实会补抓、达到事实覆盖停止、抓取预算耗尽停止。旧未指定产品分支和价格选择保持原行为；独立规格与质量复审通过。

## 任务 4：RAG 核查、回归与真实验收

- [x] 保存当前 provider 状态；不输出凭据，不把 hash 向量描述成已启用语义模型。
- [x] 运行固定 14 条 RAG 基准，记录关键词、混合、重排各模式 Recall@3 / MRR / nDCG、误用过期信息、引用正确性和权限范围；说明小型构造数据的适用范围。
- [x] 后端完整回归；前端未修改时使用上一轮同版本构建结果，不把旧结果标为新执行。
- [x] 使用本轮已批准非 AI 产品方向进行一次有预算的真实任务；终态失败，具体原因和预算已记录。修复后的完整联网到报告闭环仍待复验，本轮不追加付费任务。
- [x] 依 requesting-code-review 做独立代码复审，再运行受影响用例。
- [x] 保存修复验收和 RAG 升级设计：证据分层、实体 / 型号 / 时间过滤、语义模型及重排、统一检索、有限补采、可回查引用、各 Agent 的共享证据版本契约与评测。

## 实测与最终审查新增修复

这些是已授权采集和 Workflow 修复的具体阻断，不扩大到新的语义模型部署。

- [x] 产品非价格分支的 repair pass 使用累计候选与页面、原全局来源目标评估覆盖，初批按剩余缺口选择；新页与旧页重复时继续补抓，指标只计本轮新增。修改 `research/pipeline.py`，补同一产品覆盖测试中的跨轮场景。
- [x] 修复读取 journal 快照替换本进程活动 RunDetail 对象的问题，避免 Planner 写旧对象而 Collector 读空范围；修改 `orchestrator/service.py`，新增 `tests/unit/test_active_run_journal.py`。活动图执行时维持当前内存记录，非活动和其他进程的观察者仍能刷新 journal；异常 / 取消 / interrupt 后释放保护。
- [x] 离线回放自动发现后的并发 GET / 列表 / 事件读取，确认 Planner 消息与 Collector 调度范围一致；执行相关 journal / HITL / 跨进程观察用例及最终后端回归。
- [x] 缓存 URL 别名命中只计 cache_hits，不计网络抓取；保留候选队列，由实际网络次数限制补采，避免缓存吞掉剩余抓取槽。新增失败反例后修复，覆盖契约与 pipeline 94 项通过。
- [x] 独立规格与质量审查上述新增修复，无未决 P1 / P2。本轮唯一真实任务已失败，记录准确终态和费用；不追加付费任务，完整联网到报告闭环仍待复验。

验证命令：

```sh
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_product_query_scope.py backend/tests/unit/test_product_page_text.py backend/tests/unit/test_product_fact_coverage.py backend/tests/unit/test_active_run_journal.py -q --tb=short
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python -m packages.knowledge.benchmark --output /private/tmp/plan-a-rag-audit-2026-10-02.json
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests -q --tb=short
```
