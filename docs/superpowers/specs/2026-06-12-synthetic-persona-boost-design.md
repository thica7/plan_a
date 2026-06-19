# Synthetic Persona Boost Design

Date: 2026-06-12

## Purpose

Improve report depth for persona-heavy runs by temporarily strengthening simulated survey/interview evidence. The change should make persona, user review, SWOT, adoption blocker, switching trigger, and recommended response sections richer when real review/forum/customer voice data is sparse.

This is a tactical boost, not a replacement for later collector improvements. The system should still preserve synthetic metadata so generated evidence remains distinguishable from imported or publicly verified user research.

## Current Problem

In runs such as `run-810891b31e133f4ee49a97b979ae5554`, persona was a high-leverage dimension:

- `用户评价整理` depended on review themes, complaints, adoption blockers, switching triggers, and user persona signals.
- Public persona sources existed, but they were mostly official pages, docs, and customer pages.
- Simulated survey/interview sources were present, but low confidence values (`0.58` and `0.62`) pulled persona matrix cells down.
- Writer output became conservative, especially after writer-only repair rewrote the full report.

The user wants the first improvement to focus on simulated survey/interview quality and confidence so reports become thicker before deeper collector changes are implemented.

## Design

### Scope

Modify only the simulated survey/interview path and tests around it.

In scope:

- Raise generated survey and interview confidence enough for downstream report generation to use them more assertively.
- Enrich simulated survey/interview content with more concrete persona research material.
- Raise the structured `user_personas` claim cap so generated persona claims are not immediately flattened.
- Preserve synthetic metadata.

Out of scope:

- Changing pricing or feature collectors.
- Removing synthetic flags.
- Making generated evidence indistinguishable from imported real interviews.
- Large collector redesign for review/forum/customer voice discovery.
- Writer-only local repair changes.

### Confidence Policy

Use moderate tactical confidence values:

- `survey_simulated`: `0.76`
- generated synthetic `interview_record`: `0.82`
- generated `user_personas` claim confidence cap: `0.80`

These values are high enough to prevent persona matrix cells from collapsing to `0.58`, while still leaving room below verified public evidence and imported high-confidence real interview material.

### Synthetic Metadata

Generated survey/interview sources must continue to include:

- `fallback_synthetic: true`
- `survey_interview_synthetic: true`
- `source_role: "survey"` or `"interview"`

This keeps internal provenance intact even though the tactical confidence is raised.

### Content Enrichment

Replace the current generic simulated evidence text with a richer but deterministic persona package. The generated bundle should cover:

- proxy respondent archetypes: individual developer, team/tech lead, enterprise platform or governance buyer
- adoption blockers: onboarding effort, workflow fit, migration cost, governance/security, budget approval, team habit change
- switching triggers: incumbent tool limitations, context quality gaps, pull request pressure, cost pressure, enterprise rollout needs
- buying criteria: code quality, context handling, IDE or workflow integration, security controls, admin visibility, learning curve
- compact simulated interview summaries that mention concrete use cases and friction points

The output should remain deterministic and compact enough for tests and report generation.

### Downstream Behavior

The existing comparator behavior should naturally benefit because persona/user matrix confidence is capped by the minimum survey/interview source confidence. Raising simulated confidence should lift persona cells.

The existing writer should receive richer `raw_sources`, `competitor_kbs`, and `user_personas` claims. That should improve:

- `用户评价整理`
- persona matrix
- SWOT opportunity/threat material
- `竞品深挖`
- recommended response and battlecard sections

### Expected Trade-Offs

Benefits:

- Faster improvement to report thickness.
- Less conservative persona sections when real review data is sparse.
- Minimal changes to existing orchestration.

Risks:

- The system may be less likely to trigger persona collector redo because simulated evidence appears stronger.
- Reports may sound more confident about simulated user research than the underlying evidence deserves.
- This does not solve missing real review/forum/customer voice collection.

Mitigation:

- Keep synthetic metadata.
- Keep confidence below verified public sources.
- Add tests that assert synthetic flags remain present after the confidence increase.

## Implementation Units

1. Update `backend/packages/agents/survey/logic.py` confidence constants and generated content.
2. Update unit tests for survey/interview source confidence, metadata, and knowledge claim confidence.
3. Run focused tests:
   - `backend/tests/unit/test_survey_interview_agent.py`
   - `backend/tests/unit/test_run_service.py`
   - related report quality tests if assertions touch persona confidence or report text.

## Acceptance Criteria

- Simulated survey sources are generated at `0.76` confidence.
- Generated synthetic interview sources are generated at `0.82` confidence.
- Generated persona claims can reach `0.80` confidence.
- Synthetic metadata is still present on generated survey and interview sources.
- Simulated evidence text contains richer persona/adoption/switching/buying-criteria material.
- Existing focused unit tests pass after updates.

## Later Work

This design intentionally does not finish the broader report-depth work. Later phases should still address:

- review/forum/customer voice collector enrichment
- `cross::persona` skip quality checks
- `review_summary` richness gates
- writer-only local repair instead of full rewrite
- core report section minimum-depth QA
