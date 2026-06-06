# Clean Research Pipeline Completion Audit

Date: 2026-06-07

Source plan:
`D:\codex_workspace\websearch_v2\clean_research_pipeline_rewrite_plan.md`

## Scope

This audit covers only the data/research subsystem:

```text
Discover -> Capture -> Extract -> Admit -> Assemble -> Evaluate -> Repair
```

It does not claim that writer, release approval, RBAC, Temporal, or enterprise
deployment are complete. Those are larger `dev_plan_final` layers that consume
the research output.

## Phase Checklist

| Plan phase | Status | Project implementation |
| --- | --- | --- |
| Phase 0: typed models | Complete | `backend/packages/research/models.py` defines `ResearchBrief`, `SourceCandidate`, `CapturedPage`, `ExtractionResult`, `EvidenceItem`, `QualityGap`, `RepairTask`, and `ResearchResult`. |
| Phase 1: discovery | Complete | `backend/packages/research/discovery/` owns trusted registry, homepage-derived candidates, search-result candidates, query planning, ranking, and URL dedupe. |
| Phase 2: capture | Complete | `backend/packages/research/capture/` owns fetch normalization, cache, candidate selection, generic rejection policy, and webfetch/basic-fetch adapter output as `CapturedPage`. |
| Phase 3: extraction | Complete | `backend/packages/research/extraction/` owns pricing, feature-slot, and persona extractors plus dimension dispatch through `extract_page()`. |
| Phase 4: evaluation | Complete | `backend/packages/research/evaluation/` emits typed `QualityGap` objects from extraction and admitted evidence, plus release-gate issue mapping. |
| Phase 5: repair | Complete | `backend/packages/research/repair/` maps `QualityGap -> RepairTask`, produces query hints, and converts repair tasks to `RedoScope` where needed. |
| Phase 6: collector as adapter | Complete for data collection paths | Main branch collection, official-source compatibility, homepage fallback, and single search-result fallback now route through `run_research_pipeline()` or explicit demo-only fallback. |

## Boundary Rules

- Discovery outputs `SourceCandidate`; it does not fetch pages.
- Capture outputs `CapturedPage`; it does not create business claims.
- Extraction outputs `ExtractionResult`; it does not admit evidence.
- Admission outputs `EvidenceItem`; it rejects fields without accepted capture,
  adequate page quality, extraction confidence, or field quote.
- Evaluation outputs `QualityGap`; it does not mutate run state.
- Repair outputs `RepairTask`; it does not parse natural-language warning text.
- Collector builds `ResearchBrief`, calls the pipeline, and translates accepted
  research output into the existing `RawSource` run contract.

## 2026-06-07 Completion Commits

```text
a09178d feat(research): harden capture admission boundary
d61fe33 refactor(collector): narrow research pipeline adapters
4e9559f refactor(collector): route search result sources through research pipeline
fd5ed19 feat(research): expose pipeline quality metrics
```

## Quality Metrics Now Exposed

`ResearchResult.metrics` includes:

- `candidate_count`
- `captured_page_count`
- `captured_ok_count`
- `captured_rejected_count`
- `captured_failed_count`
- `capture_cache_hits`
- `capture_fetch_count`
- `extraction_count`
- `evidence_item_count`
- `accepted_evidence_item_count`
- `rejected_evidence_item_count`
- `accepted_evidence_rate`
- `field_support_rate`
- `gap_count`
- `repairable_gap_count`
- `blocking_gap_count`
- `initial_gap_count`
- `remaining_gap_count`
- `gap_resolution_rate`
- `repair_round_count`
- `source_saturation_reached`

These metrics allow real-run review to distinguish data failures from writer or
release-gate failures.

## Validation

Latest validation for this completion pass:

```powershell
conda run -n bd-competiscope-v2 ruff check backend/packages/agents/collectors backend/packages/research backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py
conda run -n bd-competiscope-v2 pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py -q
```

Result:

```text
All checks passed.
129 passed.
```

## Remaining Non-Research Work

The Clean Research Pipeline is now complete as the data collection and evidence
subsystem. Remaining product work belongs to the broader enterprise plan:

- Writer/report wording quality.
- Release Gate final publish decision behavior.
- HITL review UX.
- Temporal workflow hardening.
- RBAC/SSO/multitenancy.
- Enterprise storage and deployment packaging.

