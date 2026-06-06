# Clean Research Pipeline 完成记录

日期：2026-06-06

## 目标

按 `D:\codex_workspace\websearch_v2\clean_research_pipeline_rewrite_plan.md` 完成 Clean Research Pipeline 的代码边界收口，不再把 collector 当成 source discovery、capture、extraction、admission、repair 的混合模块。

## 完成的目录边界

```text
backend/packages/research/
  models.py
  pipeline.py

  discovery/
    planner.py
    providers.py
    trusted_registry.py
    ranking.py

  capture/
    fetcher.py
    webfetch_adapter.py
    cache.py
    policy.py

  extraction/
    pricing.py
    feature.py
    persona.py
    common.py

  evidence/
    admission.py
    store.py
    citations.py

  assembly/
    matrix.py
    report.py
    summary.py

  evaluation/
    qa.py
    release_gate.py
    gaps.py

  repair/
    planner.py
    strategies.py
    redos.py
```

## Phase 对照

| Phase | 要求 | 当前实现 |
|---|---|---|
| Phase 0 | typed models | `ResearchBrief`、`SourceCandidate`、`CapturedPage`、`ExtractionResult`、`EvidenceItem`、`QualityGap`、`RepairTask`、`ResearchResult` |
| Phase 1 | Discovery 迁移 | `discovery/planner.py`、`providers.py`、`trusted_registry.py`、`ranking.py` |
| Phase 2 | Capture 迁移 | `capture/fetcher.py` 调 `webfetch_adapter.py`，`selection.py` 调 `policy.py`，统一输出 `CapturedPage` |
| Phase 3 | Extraction 重做 | `pricing.py`、`feature.py`、`persona.py`、`common.py` |
| Phase 4 | Evaluation typed gaps | `evaluation/qa.py` 调 `gaps.py`，`release_gate.py` 输出 `QualityGap` |
| Phase 5 | Repair 独立阶段 | `repair/strategies.py` 生成 repair hints，`planner.py` 生成 `RepairTask`，`pipeline.py` 执行 repair round 并 re-evaluate |
| Phase 6 | Collector 变 adapter | `collectors/logic.py` 主路径调用 `run_research_pipeline()`，RawSource 投影逻辑迁入 `evidence/admission.py` |

## 主链路

当前 `run_research_pipeline()` 真实执行：

```text
Discover
-> Capture
-> Extract
-> Admit
-> Assemble
-> Evaluate
-> Repair
-> Re-evaluate
```

## Collector 边界

Collector 当前主职责：

```text
RunDetail/branch -> ResearchBrief
trace_search / trace_fetch -> pipeline provider
ResearchResult -> RawSource projection adapter
fallback to ReAct / skill tools / LLM when pipeline returns no evidence
```

旧 collector 的 source discovery/fetch helper 保留为兼容和 fallback，主路径不再依赖它们。

## 验证

已执行：

```text
python -m ruff check backend/packages/research backend/packages/agents/collectors/logic.py backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py
python -m pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q
```

结果：

```text
ruff: passed
pytest: 127 passed
```

## 说明

这次完成的是 Clean Research Pipeline 的工程边界和主链路收口。真实产品指标，例如 `release_gate_pass_rate`、`fetch_to_gap_yield`、`field_support_rate`，还需要后续真实 run 采样验证，不应只靠单元测试宣称质量已经提升。
