# Persona Evidence Quality Gate and Deficit Recollection

## Context

Recent real runs exposed a gap between collection coverage and report-ready persona evidence. Runs can pass collect QA when each competitor has at least one persona source, but analyst QA later fails or produces thin report content when the only persona evidence is a low-confidence synthetic proxy note. `run-c8c6bb9712020cf65aa2922a64ff7604` and `run-978be93438d63f5b0c17d52bfb91a134` showed this clearly for Windsurf: collection technically covered persona, but the available source set was too weak to support cited review themes.

The earlier analyst fallback repair prevents empty `review_summary` themes from blocking the run when usable source text exists. This design addresses the upstream data quality problem so collector retries target weak persona evidence before analyst work begins.

## Goals

- Distinguish "covered" persona evidence from "strong enough for analysis" persona evidence.
- Route weak persona evidence back to the collector with a precise competitor and dimension scope.
- Improve persona discovery queries for customer, case-study, adoption, user review, and rebrand/alias evidence.
- Keep synthetic survey/interview evidence as a fallback, not as the sole signal that strong coverage exists.
- Preserve strict identity safeguards so Devin/Windsurf or other alias scenarios do not admit unrelated product evidence.

## Non-Goals

- Do not lower analyst QA or release-gate requirements.
- Do not make Windsurf-only special cases in QA logic.
- Do not require every persona dimension to have public review-site evidence; customer stories, official customer pages, docs with adoption signals, and qualitative research can all contribute.
- Do not block final release only because persona evidence is imperfect when the run has already completed analyst, writer, and release-gate checks. This change targets collection-phase retry decisions.

## Design

### 1. Persona Evidence Strength

Add a small scoring helper for persona-like dimensions. The helper evaluates sources for one competitor and one dimension and returns:

- `source_count`: number of accepted sources covering the competitor and dimension.
- `verified_count`: count of `webpage_verified` sources.
- `qualitative_count`: count of `survey_response`, `interview_record`, manual note, or manual transcript sources.
- `synthetic_count`: count of `survey_simulated` or synthetic proxy sources.
- `persona_signal_count`: number of sources whose title/snippet/text contains customer, user, team, developer, buyer, adoption, case-study, review, feedback, onboarding, switching, or workflow-fit signals.
- `has_independent_public_signal`: true when at least one non-synthetic public source contains persona signals.
- `is_weak`: true when source evidence is too thin for analysis.
- `reason`: stable machine-readable reason such as `single_low_confidence_synthetic`, `synthetic_only`, `no_persona_signal`, or `too_few_sources`.

Initial weak rules for real runs:

- `source_count == 0`: existing coverage blocker remains.
- `source_count == 1` and that source is synthetic or low-confidence qualitative: weak persona evidence.
- all sources are synthetic/proxy: weak persona evidence.
- no source has persona/adoption/customer/review signal: weak persona evidence.

The helper should be deterministic and unit-testable. It can live in `backend/packages/agents/qa/logic.py` if only used for QA, or in a small shared module if collector also needs the score for query planning.

### 2. Collect QA Weak Persona Issue

Extend collect QA so persona-like dimensions emit a collector-scoped issue when evidence is weak:

- `severity`: blocker for real runs when evidence is synthetic-only or single low-confidence proxy.
- `target_agent`: collector.
- `target_subagent`: persona.
- `target_competitor`: affected competitor.
- `field_path`: `raw_sources[persona][<competitor>]`.
- `problem`: concise reason, for example `Windsurf persona evidence is weak: only one low-confidence synthetic/proxy source covers persona.`
- `redo_scope`: collector/persona/competitor.

This issue should appear before analyst dispatch, causing graph phase QA to retry the collector branch instead of letting analyst fail on empty review themes.

### 3. Persona Discovery Query Ladder

For persona collection, expand query planning with a layered ladder:

1. Official/customer layer:
   - `<competitor> customers case studies developers enterprise teams official`
   - `<competitor> customer stories AI coding agent adoption`
   - homepage hints and trusted registry candidates remain first-class seeds.
2. Review/adoption layer:
   - `<competitor> user reviews developer feedback AI coding agent`
   - `<competitor> onboarding switching cost workflow fit developers`
3. Alias/rebrand layer:
   - If the entity resolver exposes aliases or rebrand terms, repeat the customer/adoption patterns with aliases.
   - For Windsurf-like scenarios this means queries can combine Windsurf, Devin Desktop, and customers/adoption/reviews without admitting unrelated Devin autonomous-agent evidence.
4. Cross-competitor fallback:
   - Use comparison pages only after official or direct persona sources are insufficient.
   - Comparison pages can supplement persona evidence but should not be the sole strong persona source unless they contain explicit adoption/user/customer signals.

The collector should keep existing identity and dimension mismatch checks. Pricing pages remain mismatched for persona unless they contain explicit buyer/persona/adoption facts beyond plan names.

### 4. Deficit-Driven Survey/Interview Enrichment

Change enrichment selection from broad plan-based enrichment to deficit-driven enrichment:

- After normalization, score persona evidence for each planned competitor.
- Generate or import survey/interview evidence for every competitor whose persona evidence is weak, including competitors without existing survey bundles.
- Mark synthetic/proxy enrichment as fallback evidence in metadata.
- Re-run collect QA after enrichment. If the competitor still has only synthetic/proxy evidence, keep a weak evidence issue so the system tries public recollection before accepting the source set as strong.

This ensures synthetic data improves analyst context but does not hide the lack of public evidence.

### 5. Acceptance Behavior

After this change, a run with weak Windsurf persona evidence should behave as follows:

1. Collector collects one weak persona proxy.
2. Collect QA emits `collector/persona/Windsurf` weak evidence issue.
3. Scoped retry runs persona collector for Windsurf.
4. Collector uses expanded official, adoption, review, and alias queries.
5. If stronger public evidence is found, collect QA passes and analyst receives enough source material.
6. If stronger evidence is not available after max collect attempts, the run fails earlier with a collection evidence reason instead of failing later as an analyst schema problem.

## Testing Plan

- Unit test persona evidence scoring:
  - one low-confidence `interview_record` is weak.
  - one verified customer page with persona signal is not weak if paired with another source.
  - synthetic-only source set is weak.
  - verified pricing page without persona signal does not satisfy persona strength.
- Unit test collect QA issue generation:
  - weak Windsurf persona creates collector blocker with `redo_scope.kind == "collector"`.
  - Cursor with customer page plus interview source does not create weak persona blocker.
- Unit test query generation:
  - persona queries include customers, case studies, adoption, reviews, onboarding, switching, and workflow fit.
  - alias/rebrand terms are included when known.
  - pricing mismatch protection still rejects persona evidence from pure pricing pages.
- Regression test graph routing:
  - weak persona issue routes through collector retry before analyst dispatch.
- Keep existing analyst fallback tests to ensure empty `review_summary` is still repaired if collection passes but analyst returns empty themes.

## Rollout

Implement behind deterministic rules, not a feature flag. The behavior only tightens collection QA for persona-like dimensions in real runs. Demo runs can keep warnings or lower severity to avoid making demo fixtures brittle.

## Risks

- More collect retries can increase runtime and search/fetch cost. Mitigation: target only weak competitor/dimension pairs and cap additional query layers.
- Public persona evidence may genuinely be unavailable. Mitigation: fail earlier with a clear collection reason rather than hiding the weakness in the report.
- Alias/rebrand expansion can admit wrong-product sources. Mitigation: keep identity checks and require persona/adoption signals.

## Open Implementation Notes

- Prefer adding small helper methods over growing large conditional blocks in QA.
- Keep issue ids stable using existing `stable_prefixed_id` patterns.
- Reuse existing `USER_RESEARCH_SOURCE_TYPES` and quality source-type constants where possible.
- Avoid changing analyst QA strictness; this design complements the analyst fallback repair.
