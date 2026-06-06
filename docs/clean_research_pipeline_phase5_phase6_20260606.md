# Clean Research Pipeline Phase 5/6 收口记录

日期：2026-06-06

## 背景

本次修改用于纠正前一轮推进中的结构偏差：`research/` 已有 typed models、discovery、capture、extraction、evaluation、repair 模块，但主链路只生成 `RepairTask`，没有执行二次补证；旧 collector 也仍然承担 discovery/capture/extraction/admission 的主职责。

本次不继续在旧 collector 中追加 URL 特例或 if/else 规则，而是按 `clean_research_pipeline_rewrite_plan.md` 收口：

```text
Discover -> Capture -> Extract -> Admit -> Assemble -> Evaluate -> Repair
```

## 本次完成

### 1. Phase 5：Repair 成为真实闭环

修改文件：

- `backend/packages/research/models.py`
- `backend/packages/research/pipeline.py`

变化：

- `ResearchBrief` 增加 `max_repair_rounds`，默认允许 1 轮定向修复。
- `run_research_pipeline()` 拆出内部 `ResearchPass`。
- 第一轮 evaluation 产出 `QualityGap` 后，pipeline 会生成 `RepairTask`。
- RepairTask 会重新进入 targeted discovery/capture/extraction。
- 合并二次结果后重新计算 `EvidenceItem`、`QualityGap`、`RepairTask` 和 assembly。
- metrics 增加：
  - `initial_gap_count`
  - `remaining_gap_count`
  - `repair_round_count`
  - `repair_task_count`
  - `repair_candidate_count`
  - `repair_capture_count`
  - `gap_resolution_rate`

这意味着 QA warning/gap 不再只是“提示”，而是可被 pipeline 消费的 typed repair input。

### 2. Phase 6：Collector 主路径切到 Research Pipeline

修改文件：

- `backend/packages/agents/collectors/logic.py`

变化：

- `_collect_competitor_with_web_search()` 变成 clean pipeline adapter。
- 新增 `_collect_competitor_with_research_pipeline()`：
  - 将当前 run branch 转成 `ResearchBrief`。
  - 将 `self._trace_search()` 注入为 pipeline search provider。
  - 将 `self._trace_fetch()` 注入为 pipeline fetch provider。
  - 调用 `run_research_pipeline()`。
- 新增 `_raw_sources_from_research_result()`：
  - 只把有 accepted `EvidenceItem` 的 captured page 投影成 `RawSource`。
  - 保留 current system 需要的 `RawSource`，但数据来源由 clean pipeline 决定。
- `_real_collector_branch_step()` 的主收集顺序调整为：

```text
Clean Research Pipeline
-> ReAct fallback
-> skill tools fallback
-> LLM fallback
```

旧 `_collect_official_sources()`、`_collect_from_source_candidates()`、`_source_from_search_result()` 等方法仍保留，用于兼容和兜底，不再是单竞品分支的主研究链路。

## 测试覆盖

新增/调整：

- `backend/tests/unit/test_research_pipeline.py`
  - 新增 `test_run_research_pipeline_executes_gap_driven_repair_round`
  - 验证第一轮 evidence 不足时，`QualityGap -> RepairTask -> targeted search/fetch/extract` 能补回字段。
- `backend/tests/unit/test_run_service.py`
  - 更新旧 official-first 断言为 clean research pipeline adapter 断言。

已执行：

```text
ruff check backend/packages/research/pipeline.py backend/packages/research/models.py backend/packages/agents/collectors/logic.py backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py
pytest backend/tests/unit/test_research_pipeline.py -q
pytest backend/tests/unit/test_run_service.py -q
```

结果：

```text
ruff: passed
test_research_pipeline.py: 16 passed
test_run_service.py: 110 passed
```

## 仍保留的边界

本次没有删除旧 collector 内所有历史方法。原因是旧方法仍被部分 ReAct、skill fallback、测试工具和兼容路径使用。当前正确边界是：

```text
主路径：research.pipeline
兼容/兜底：legacy collector methods
```

后续如果继续收口，应做“删减旧 collector 逻辑”的独立提交，而不是在本提交中混合大规模删除。
