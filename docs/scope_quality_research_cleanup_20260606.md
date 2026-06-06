# Scope, Quality, And Source Cleanup - 2026-06-06

## Purpose

This cleanup closes the inconsistencies found after `run-934308657e5c29d7593e366c94a155cf`:

- report citations resolved correctly but still exposed machine ids as the primary UI label;
- Release Gate used report scope on the run path, while approval still used project-wide scope;
- Run Quality showed raw metric values without explaining normalized score deductions;
- the clean research pipeline could still spend fetch/webfetch attempts on low-confidence guessed URLs.

## Changes

- Added `packages.enterprise.report_scope` as the single resolver for report-version competitors, evidence, and claims.
- Updated API, orchestrator, and Temporal approval paths to evaluate Release Gate against the same report scope.
- Kept RawSource ids as the internal citation identity, but rendered report citations as stable human labels such as `S1` and `S2`.
- Added normalized metric score fields to `RunQualityMetric`, and made the UI show score drivers instead of baseline-missing noise.
- Added capture candidate selection so low-confidence homepage-derived URLs and low-confidence unrelated search results are deferred when enough stronger candidates exist.
- Lowered search candidate confidence when title, URL, and snippet do not mention the target competitor.

## Verification

- `python -m pytest backend/tests/unit/test_report_quality.py backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_temporal_workflows.py backend/tests/unit/test_enterprise_store.py backend/tests/unit/test_advanced_fetch.py backend/tests/unit/test_source_reconciliation.py -q`
- `pnpm --dir frontend test ReportView`
- `pnpm --dir frontend build`
