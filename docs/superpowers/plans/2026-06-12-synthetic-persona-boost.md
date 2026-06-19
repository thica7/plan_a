# Synthetic Persona Boost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise generated simulated survey/interview confidence and content depth so persona-heavy reports have richer user-research material.

**Architecture:** Keep the change inside the existing `SurveyInterviewAgentMixin` pipeline. Generated sources remain synthetic through metadata, but their confidence and deterministic snippets become strong enough for comparator and writer to use them more assertively.

**Tech Stack:** Python, Pydantic DTOs, pytest, existing `RunService` unit test harness.

---

## File Structure

- Modify `backend/packages/agents/survey/logic.py`
  - Owns generated survey/interview bundles, source confidence, synthetic metadata, and knowledge projection.
  - Add module-level confidence constants and richer deterministic text helpers.
- Modify `backend/packages/tools/survey_simulator.py`
  - Owns the compact synthetic interview record returned to survey enrichment.
  - Expand the deterministic interview summary with respondent archetypes and concrete adoption themes.
- Modify `backend/tests/unit/test_survey_interview_agent.py`
  - Owns focused assertions for generated survey/interview sources and synthetic metadata.
  - Update confidence expectations and add snippet richness assertions.
- Modify `backend/tests/unit/test_run_service.py`
  - Owns integration-style assertions for survey/interview enrichment, comparator confidence caps, and collect QA behavior.
  - Update only assertions that intentionally encode generated synthetic confidence.

---

### Task 1: Add Failing Tests For Boosted Survey/Interview Sources

**Files:**
- Modify: `backend/tests/unit/test_survey_interview_agent.py:81-110`
- Test: `backend/tests/unit/test_survey_interview_agent.py`

- [ ] **Step 1: Update the focused enrichment test with the new confidence and richness contract**

In `test_survey_interview_enrichment_adds_typed_research_evidence`, replace the confidence and snippet assertions around the generated sources with:

```python
    assert "target users" in survey_source.snippet
    assert "buyer personas" in survey_source.snippet
    assert "adoption blockers" in survey_source.snippet
    assert "switching triggers" in survey_source.snippet
    assert "buying criteria" in survey_source.snippet
    assert survey_source.confidence == 0.76
    assert survey_source.metadata["fallback_synthetic"] is True
    assert survey_source.metadata["survey_interview_synthetic"] is True
    assert survey_source.metadata["source_role"] == "survey"

    assert interview_source.competitor == "Acme"
    assert interview_source.dimension == "persona"
    assert "pain points" in interview_source.snippet
    assert "individual developer" in interview_source.snippet
    assert "team technical lead" in interview_source.snippet
    assert "enterprise platform buyer" in interview_source.snippet
    assert interview_source.confidence == 0.82
    assert interview_source.metadata["fallback_synthetic"] is True
    assert interview_source.metadata["survey_interview_synthetic"] is True
    assert interview_source.metadata["source_role"] == "interview"
```

- [ ] **Step 2: Add knowledge claim confidence assertions**

In the same test, after `assert "workflow fit" in knowledge.user_personas.summary_claims[0].claim`, add:

```python
    assert knowledge.user_personas.summary_claims[0].confidence == 0.8
    assert knowledge.user_personas.segments[0].claims[0].confidence == 0.8
    assert "adoption risk" in knowledge.user_personas.summary_claims[0].claim
    assert "buying criteria" in knowledge.user_personas.summary_claims[0].claim
```

- [ ] **Step 3: Run the focused test and verify it fails before implementation**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_survey_interview_agent.py::test_survey_interview_enrichment_adds_typed_research_evidence -q
```

Expected: FAIL because generated survey confidence is still `0.58`, generated interview confidence is still `0.62`, and snippets do not yet include the new richness terms.

---

### Task 2: Implement Boosted Synthetic Persona Generation

**Files:**
- Modify: `backend/packages/agents/survey/logic.py:36-58`
- Modify: `backend/packages/agents/survey/logic.py:225-342`
- Modify: `backend/packages/agents/survey/logic.py:430-560`
- Modify: `backend/packages/tools/survey_simulator.py:21-35`
- Test: `backend/tests/unit/test_survey_interview_agent.py`

- [ ] **Step 1: Add explicit confidence constants**

Near the top of `backend/packages/agents/survey/logic.py`, below `USER_RESEARCH_SOURCE_TYPES`, add:

```python
SYNTHETIC_SURVEY_CONFIDENCE = 0.76
SYNTHETIC_INTERVIEW_CONFIDENCE = 0.82
SYNTHETIC_PERSONA_CLAIM_CONFIDENCE = 0.80
```

- [ ] **Step 2: Replace the generic survey response text**

In `_build_survey_interview_bundle`, replace the `answers` free-text value and `quote` with deterministic richer text:

```python
                    questions[1].id: self._redact_research_text(
                        (
                            "Proxy respondents evaluate adoption blockers across onboarding "
                            "effort, workflow fit, migration cost, governance/security review, "
                            "budget approval, and team habit change. Switching triggers include "
                            "incumbent tool limitations, context quality gaps, pull request "
                            "pressure, cost pressure, and enterprise rollout needs."
                        ),
                        redaction_counts,
                    ),
```

```python
                quote=self._redact_research_text(
                    (
                        f"{competitor} is evaluated through buying criteria such as code "
                        "quality, context handling, workflow integration, security controls, "
                        "admin visibility, and learning curve."
                    ),
                    redaction_counts,
                ),
```

- [ ] **Step 3: Replace generic synthesized interview pain points and use cases**

In the `InterviewSynthesis` construction, replace `pain_points` and `use_cases` with:

```python
                pain_points=[
                    "workflow fit uncertainty",
                    "onboarding effort",
                    "migration cost",
                    "governance and security review",
                    "budget approval friction",
                    "team habit change",
                ],
                use_cases=[
                    f"{redacted_topic} evaluation",
                    f"{redacted_dimension} buying criteria review",
                    "individual developer productivity trial",
                    "team pull request workflow rollout",
                    "enterprise platform governance review",
                ],
```

- [ ] **Step 4: Raise the bundle confidence**

In the `SurveyEvidenceBundle` constructor, replace:

```python
            confidence=0.58,
```

with:

```python
            confidence=SYNTHETIC_SURVEY_CONFIDENCE,
```

- [ ] **Step 5: Raise generated interview source confidence**

In `_sources_from_survey_bundle`, replace:

```python
                    confidence=max(bundle.confidence, 0.62),
```

with:

```python
                    confidence=SYNTHETIC_INTERVIEW_CONFIDENCE,
```

- [ ] **Step 6: Expand the survey evidence summary**

Replace `_survey_evidence_summary` return value with:

```python
        return (
            f"Simulated survey and interview research for {competitor} in {detail.topic}: "
            f"target users, customers, enterprise teams, and buyer personas evaluate "
            f"{dimension} through adoption blockers, switching triggers, and buying criteria. "
            "Adoption blockers include onboarding effort, workflow fit, migration cost, "
            "governance/security review, budget approval, and team habit change. "
            "Switching triggers include incumbent tool limitations, context quality gaps, "
            "pull request pressure, cost pressure, and enterprise rollout needs. "
            "Buying criteria include code quality, context handling, workflow integration, "
            f"security controls, admin visibility, and learning curve. {interview_summary} {quote}"
        )
```

- [ ] **Step 7: Expand the interview evidence summary**

Replace `_interview_evidence_summary` return value with:

```python
        return (
            f"Synthetic interview record for {competitor} in {detail.topic}: "
            "proxy respondents include an individual developer, a team technical lead, "
            "and an enterprise platform buyer. "
            f"Respondents discussed {dimension} pain points "
            f"({', '.join(pain_points) or 'none'}) and use cases "
            f"({', '.join(use_cases) or 'none'}). {summaries}"
        )
```

- [ ] **Step 8: Raise generated persona claim confidence and enrich the claim**

In `_apply_survey_bundle_to_knowledge`, replace the `KnowledgeClaim` block with:

```python
        claim = KnowledgeClaim(
            claim=(
                f"{bundle.competitor} simulated user research indicates {bundle.dimension} "
                "decisions are shaped by workflow fit, onboarding effort, adoption risk, "
                "switching cost, governance/security review, budget approval, team habit "
                "change, and buying criteria such as code quality, context handling, "
                "workflow integration, admin visibility, and learning curve."
            ),
            source_ids=source_ids,
            confidence=SYNTHETIC_PERSONA_CLAIM_CONFIDENCE,
        )
```

- [ ] **Step 9: Expand the fallback persona segment defaults**

In the `UserPersonaSegment` construction, replace the fallback `pain_points` and `use_cases` lists with:

```python
            or [
                "workflow fit uncertainty",
                "onboarding effort",
                "migration cost",
                "governance and security review",
                "budget approval friction",
                "team habit change",
            ],
```

```python
            or [
                f"{bundle.topic} evaluation",
                "individual developer productivity trial",
                "team pull request workflow rollout",
                "enterprise platform governance review",
            ],
```

- [ ] **Step 10: Expand the simulator summary**

In `backend/packages/tools/survey_simulator.py`, replace the `summary = (...)` block with:

```python
    summary = (
        f"Synthetic interview note for {competitor} in {topic}: proxy respondents include "
        "an individual developer testing daily productivity, a team technical lead planning "
        "pull request workflow rollout, and an enterprise platform buyer reviewing governance. "
        f"They evaluate {dimension} through workflow fit, onboarding effort, migration cost, "
        "security controls, budget approval, context quality, and switching risk."
        f"{feedback_hint}"
    )
```

- [ ] **Step 11: Run the focused test and verify it passes**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_survey_interview_agent.py::test_survey_interview_enrichment_adds_typed_research_evidence -q
```

Expected: PASS.

---

### Task 3: Update Integration Assertions For New Persona Confidence

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Update generated survey/interview payload assertions**

In `test_survey_interview_enrichment_emits_research_evidence_payload`, update any assertions for generated `survey_simulated` and generated `interview_record` confidence to:

```python
    assert survey_source.confidence == 0.76
    assert interview_source.confidence == 0.82
```

Keep assertions for manually constructed fixture sources at `0.58` or `0.62` unchanged unless the test is explicitly asserting generated enrichment output.

- [ ] **Step 2: Update generated synthetic metadata assertions**

In generated enrichment tests, assert both synthetic metadata flags:

```python
    assert survey_source.metadata["fallback_synthetic"] is True
    assert survey_source.metadata["survey_interview_synthetic"] is True
    assert interview_source.metadata["fallback_synthetic"] is True
    assert interview_source.metadata["survey_interview_synthetic"] is True
```

- [ ] **Step 3: Update persona matrix confidence tests only where the fixture intends generated synthetic confidence**

For tests that construct a `ComparisonMatrix` from fixture sources, keep fixture values if the test is validating low-confidence cap behavior. For tests that use generated enrichment output, assert the raised cap:

```python
    assert matrix.cells[0].confidence == pytest.approx(0.76)
```

Use `0.76` when both generated survey and generated interview are related sources, because comparator caps persona confidence to the minimum user-research source confidence.

- [ ] **Step 4: Run the impacted run-service tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -q
```

Expected: PASS.

---

### Task 4: Run Focused Quality Suite And Commit

**Files:**
- Modify: no new files beyond Tasks 1-3
- Test: `backend/tests/unit/test_survey_interview_agent.py`
- Test: `backend/tests/unit/test_run_service.py`
- Test: `backend/tests/unit/test_report_quality.py`
- Test: `backend/tests/unit/test_review_theme_summary.py`

- [ ] **Step 1: Run the focused survey/interview suite**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_survey_interview_agent.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the focused report-quality safety suite**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py backend\tests\unit\test_review_theme_summary.py -q
```

Expected: PASS.

- [ ] **Step 3: Run lint on changed files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\survey\logic.py backend\packages\tools\survey_simulator.py backend\tests\unit\test_survey_interview_agent.py backend\tests\unit\test_run_service.py
```

Expected: PASS.

- [ ] **Step 4: Check staged diff hygiene**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only the intended survey/simulator/test files are modified, plus existing unrelated untracked files remain untracked.

- [ ] **Step 5: Commit implementation**

Run:

```powershell
git add -- backend/packages/agents/survey/logic.py backend/packages/tools/survey_simulator.py backend/tests/unit/test_survey_interview_agent.py backend/tests/unit/test_run_service.py
git commit -m "feat: boost synthetic persona research"
```

Expected: commit succeeds.

---

## Self-Review Notes

- Spec coverage: Task 2 raises confidence, enriches content, preserves metadata, and raises persona claim confidence. Tasks 1 and 3 encode those requirements in focused and integration tests. Task 4 verifies affected quality suites.
- Scope control: The plan does not alter pricing/feature collection, collector skip logic, writer repair logic, or synthetic provenance flags.
- Type consistency: Constants are simple floats used only inside `SurveyInterviewAgentMixin`; test assertions match the exact values from the design spec.
