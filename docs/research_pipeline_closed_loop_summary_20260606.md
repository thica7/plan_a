# Research Pipeline Closed Loop Summary

Date: 2026-06-06

## Result

The clean research pipeline is now closed at the architecture level:

```text
Discover
  -> Capture
  -> Extract
  -> Field-level Evidence Admission
  -> Assemble Branch Evidence Summary
  -> Evaluate Quality Gaps
  -> Plan Repair Tasks
  -> Convert Repair Tasks To Scoped Redo
  -> Feed Release Gate Blockers Back Into Auto Redo
```

This does not replace LangGraph or Temporal. LangGraph still runs the agent
graph. Temporal still wraps the enterprise long-running workflow. The new
pipeline standardizes the research/evidence contract used inside that graph.

## What Was Completed

### 1. Typed Research Contracts

Added stable typed contracts:

- `ResearchBrief`
- `SourceCandidate`
- `CapturedPage`
- `ExtractionResult`
- `EvidenceItem`
- `QualityGap`
- `RepairTask`
- `ResearchResult`

IDs are stable and prefixed:

- `source-candidate-*`
- `captured-page-*`
- `extraction-*`
- `evidence-item-*`
- `quality-gap-*`
- `repair-task-*`

Canonical report citations still use `RawSource.id` generated through
`compute_raw_source_id()`.

### 2. Clean Stage Boundaries

Implemented modules:

```text
packages.research.discovery
packages.research.capture
packages.research.extraction
packages.research.evidence
packages.research.assembly
packages.research.evaluation
packages.research.repair
packages.research.pipeline
```

The collector now calls the research layer for candidate discovery, capture
normalization, RawSource lineage, and source quality admission.

### 3. Extraction And Field-Level Evidence Admission

Implemented extraction for:

- pricing model
- feature slot matrix
- persona schema

Implemented field-level evidence admission:

- accepted fields become `EvidenceItem(status="accepted")`
- low-confidence fields become `EvidenceItem(status="rejected")`
- rejection reason is explicit and structured

### 4. QA-Warning/GAP-Driven Repair

Implemented:

```text
ExtractionResult[]
  -> quality_gaps_from_extractions()
  -> QualityGap[]
  -> repair_tasks_from_gaps()
  -> RepairTask[]
```

This means repair no longer depends on unstructured warning text.

### 5. Release Gate Backflow

Implemented release-gate closure:

```text
ReportReleaseGate.issues
  -> quality_gaps_from_release_gate()
  -> RepairTask[]
  -> RedoScope[]
  -> RunDetail.qa_findings
  -> existing scoped redo
```

Real runs can now auto-redo blocked release gates through the same scoped redo
mechanism already used by QA. Demo runs still surface
`completed_with_blockers` for review/demo visibility.

### 6. Capture Cache And Source Saturation

Implemented:

- `CaptureCache`
- URL-level fetch reuse
- candidate lineage rebinding on cache hit
- pipeline metrics:
  - `capture_cache_hits`
  - `capture_fetch_count`
  - `accepted_evidence_item_count`
  - `source_saturation_reached`

### 7. Assembly Output

Implemented branch-level assembly:

```text
assemble_research_summary()
```

`ResearchResult.assembly` now contains accepted field summaries, rejected
counts, gap IDs, repair task IDs, branch key, competitor, and dimension.

## What Is Intentionally Not Replaced

The refactor does not rewrite:

- LangGraph orchestration
- Temporal workflow shell
- existing analyst/comparator/writer agents
- enterprise projection storage
- report UI

Those layers now have a cleaner research contract to consume, but their public
responsibilities stay intact.

## Validation

Final validation commands:

```powershell
conda run -n bd-competiscope-v2 ruff check backend/packages/agents/collectors backend/packages/orchestrator/service.py backend/packages/research backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py
conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q
conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_enterprise_store.py::test_run_service_records_release_gate_notification_for_weak_report -q
```

The final run passed:

```text
All checks passed.
123 passed for research + run_service.
1 passed for release-gate notification regression.
```

## Commit Sequence

The closed-loop work after the first pipeline skeleton is:

```text
fde00b5 feat(research): bridge release gate gaps to redo tasks
60567ff feat(orchestrator): auto redo blocked release gates
c7de5f8 feat(research): add field admission and capture cache
4b95ffc feat(research): assemble branch evidence summaries
```
