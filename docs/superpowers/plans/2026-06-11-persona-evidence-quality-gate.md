# Persona Evidence Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make persona/user evidence collection fail early and retry precisely when a competitor has only weak synthetic/proxy evidence, then improve collector query breadth so real runs have a better chance of finding usable public persona evidence.

**Architecture:** Add a deterministic persona evidence strength helper in collect QA, use it to emit collector-scoped weak-evidence issues before analyst dispatch, and reuse the same helper from survey enrichment and cross-competitor collection decisions. Keep the rule generic for persona/user/review-like dimensions so it is not Windsurf-specific.

**Tech Stack:** Python 3.11 in `D:\Anaconda\envs\bd-competiscope-v2`, pytest, ruff, Pydantic models in `backend/packages/schema/models.py`, existing RunService agent mixins.

---

## File Map

- Modify `backend/packages/agents/qa/logic.py`: add persona evidence strength scoring and weak persona collect QA issues.
- Modify `backend/packages/agents/collectors/logic.py`: expand persona search terms and keep cross-competitor search from skipping when branch coverage is weak.
- Modify `backend/packages/agents/survey/logic.py`: do not let one weak existing user-research source suppress survey/interview enrichment; mark generated survey/interview evidence as fallback synthetic metadata.
- Modify `backend/tests/unit/test_run_service.py`: add collect QA, persona query, and cross-competitor regression tests.
- Modify `backend/tests/unit/test_survey_interview_agent.py`: add deficit-driven enrichment regression test.

---

### Task 1: Persona Evidence Strength Gate

**Files:**
- Modify: `backend/packages/agents/qa/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing collect QA tests**

Add these tests near the existing collect QA tests in `backend/tests/unit/test_run_service.py`.

```python
def test_collect_qa_blocks_single_low_confidence_persona_proxy() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-weak-persona",
        topic="AI coding assistant persona comparison",
        status="running",
        execution_mode="real",
        created_at="2026-06-11T00:00:00",
        updated_at="2026-06-11T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding assistant persona comparison",
            competitors=["Windsurf"],
            dimensions=["persona"],
        ),
        raw_sources=[
            RawSource(
                id="raw-source-windsurf-persona-proxy",
                competitor="Windsurf",
                covered_competitors=["Windsurf"],
                dimension="persona",
                source_type="interview_record",
                title="Windsurf persona interview proxy",
                snippet="Proxy interview mentions workflow fit, onboarding effort, and switching risk.",
                content_hash="windsurf-persona-proxy-hash",
                confidence=0.62,
                metadata={"fallback_synthetic": True},
            )
        ],
    )

    issues = service._build_collect_qa_issues(detail)

    weak_issue = next(issue for issue in issues if "persona evidence is weak" in issue.problem)
    assert weak_issue.severity == "blocker"
    assert weak_issue.target_agent == "collector"
    assert weak_issue.target_subagent == "persona"
    assert weak_issue.target_competitor == "Windsurf"
    assert weak_issue.redo_scope.kind == "collector"
    assert weak_issue.redo_scope.target_subagent == "persona"
    assert weak_issue.redo_scope.target_competitor == "Windsurf"
```

```python
def test_collect_qa_accepts_public_and_interview_persona_evidence() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-strong-persona",
        topic="AI coding assistant persona comparison",
        status="running",
        execution_mode="real",
        created_at="2026-06-11T00:00:00",
        updated_at="2026-06-11T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding assistant persona comparison",
            competitors=["Cursor"],
            dimensions=["persona"],
        ),
        raw_sources=[
            RawSource(
                id="cursor-customer-story",
                competitor="Cursor",
                covered_competitors=["Cursor"],
                dimension="persona",
                source_type="webpage_verified",
                title="Cursor customer story for engineering teams",
                url="https://www.cursor.com/customers/example",
                snippet="Engineering teams and developers adopted Cursor for workflow fit, onboarding, and AI coding use cases.",
                content_hash="cursor-customer-story-hash",
                confidence=0.92,
            ),
            RawSource(
                id="cursor-interview",
                competitor="Cursor",
                covered_competitors=["Cursor"],
                dimension="persona",
                source_type="interview_record",
                title="Cursor buyer interview",
                snippet="Developer teams cited customer adoption, switching cost, and workflow fit.",
                content_hash="cursor-interview-hash",
                confidence=0.78,
            ),
        ],
    )

    issues = service._build_collect_qa_issues(detail)

    assert not [issue for issue in issues if "persona evidence is weak" in issue.problem]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_collect_qa_blocks_single_low_confidence_persona_proxy backend\tests\unit\test_run_service.py::test_collect_qa_accepts_public_and_interview_persona_evidence -q
```

Expected: the first test fails because `_build_collect_qa_issues()` does not emit a weak persona issue.

- [ ] **Step 3: Add minimal QA implementation**

In `backend/packages/agents/qa/logic.py`, add `dataclass` and `RawSource` imports:

```python
from dataclasses import dataclass
```

```python
    RawSource,
```

Add constants after `REVIEW_SUMMARY_DIMENSION_HINTS`:

```python
PERSONA_EVIDENCE_DIMENSION_HINTS = (
    "persona",
    "user",
    "customer",
    "buyer",
    "review",
    "feedback",
    "adoption",
    "switching",
)
PERSONA_SYNTHETIC_SOURCE_TYPES = {"survey_simulated"}
PERSONA_QUALITATIVE_SOURCE_TYPES = {
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
}
PERSONA_PUBLIC_SOURCE_TYPES = {"webpage_verified"}
PERSONA_SIGNAL_TERMS = (
    "persona",
    "target user",
    "customer",
    "customers",
    "buyer",
    "developer",
    "developers",
    "engineering team",
    "enterprise team",
    "team",
    "case study",
    "customer story",
    "review",
    "feedback",
    "adoption",
    "onboarding",
    "switching",
    "workflow fit",
    "use case",
    "pain point",
)
```

Add this dataclass before `class QualityAgentMixin`:

```python
@dataclass(frozen=True)
class PersonaEvidenceStrength:
    source_count: int
    verified_count: int
    qualitative_count: int
    synthetic_count: int
    persona_signal_count: int
    has_independent_public_signal: bool
    is_weak: bool
    reason: str
```

Add helper methods inside `QualityAgentMixin`:

```python
    def _dimension_needs_persona_strength_gate(self, dimension: str) -> bool:
        normalized = dimension.casefold().replace("-", "_")
        return any(hint in normalized for hint in PERSONA_EVIDENCE_DIMENSION_HINTS)

    def _persona_source_text(self, source: RawSource) -> str:
        return " ".join([source.title, str(source.url or ""), source.snippet]).casefold()

    def _persona_source_is_synthetic(self, source: RawSource) -> bool:
        return source.source_type in PERSONA_SYNTHETIC_SOURCE_TYPES or bool(
            source.metadata.get("fallback_synthetic")
            or source.metadata.get("synthetic_fallback")
            or source.metadata.get("survey_interview_synthetic")
        )

    def _source_has_persona_signal(self, source: RawSource) -> bool:
        text = self._persona_source_text(source)
        return any(term in text for term in PERSONA_SIGNAL_TERMS)

    def _persona_evidence_strength(
        self,
        detail: RunDetail,
        dimension: str,
        competitor: str,
    ) -> PersonaEvidenceStrength:
        sources = [
            source
            for source in detail.raw_sources
            if source.dimension == dimension and self._source_matches_competitor(source, competitor)
        ]
        verified_count = sum(
            1 for source in sources if source.source_type in PERSONA_PUBLIC_SOURCE_TYPES
        )
        qualitative_count = sum(
            1 for source in sources if source.source_type in PERSONA_QUALITATIVE_SOURCE_TYPES
        )
        synthetic_count = sum(1 for source in sources if self._persona_source_is_synthetic(source))
        signal_count = sum(1 for source in sources if self._source_has_persona_signal(source))
        public_signal = any(
            source.source_type in PERSONA_PUBLIC_SOURCE_TYPES
            and not self._persona_source_is_synthetic(source)
            and self._source_has_persona_signal(source)
            for source in sources
        )
        if not sources:
            reason = "no_sources"
        elif len(sources) == 1 and self._persona_source_is_synthetic(sources[0]):
            reason = "single_low_confidence_synthetic"
        elif len(sources) == 1 and sources[0].source_type in PERSONA_QUALITATIVE_SOURCE_TYPES and sources[0].confidence < 0.7:
            reason = "single_low_confidence_qualitative"
        elif synthetic_count == len(sources):
            reason = "synthetic_only"
        elif signal_count == 0:
            reason = "no_persona_signal"
        elif not public_signal and len(sources) < 2:
            reason = "too_few_sources"
        else:
            reason = "strong"
        return PersonaEvidenceStrength(
            source_count=len(sources),
            verified_count=verified_count,
            qualitative_count=qualitative_count,
            synthetic_count=synthetic_count,
            persona_signal_count=signal_count,
            has_independent_public_signal=public_signal,
            is_weak=reason != "strong",
            reason=reason,
        )
```

Add `_build_persona_evidence_strength_issues()` and call it from `_build_collect_qa_issues()` after `_build_source_coverage_issues()`:

```python
        issues.extend(self._build_source_quality_issues(detail))
        issues.extend(self._build_source_coverage_issues(detail, missing_dimensions))
        issues.extend(self._build_persona_evidence_strength_issues(detail, missing_dimensions))
        return issues
```

```python
    def _build_persona_evidence_strength_issues(
        self,
        detail: RunDetail,
        missing_dimensions: list[str],
    ) -> list[QCIssue]:
        issues: list[QCIssue] = []
        for dimension in detail.plan.dimensions:
            if dimension in missing_dimensions:
                continue
            if not self._dimension_needs_persona_strength_gate(dimension):
                continue
            for competitor in detail.plan.competitors:
                strength = self._persona_evidence_strength(detail, dimension, competitor)
                if not strength.is_weak or strength.reason == "no_sources":
                    continue
                field_path = f"raw_sources[{dimension}][{competitor}]"
                problem = (
                    f"{competitor} {dimension} evidence is weak: {strength.reason.replace('_', ' ')} "
                    f"with {strength.source_count} source(s), {strength.verified_count} verified public "
                    f"source(s), and {strength.persona_signal_count} persona signal source(s)."
                )
                issue = QCIssue(
                    id=stable_prefixed_id(
                        "qc-issue",
                        "weak-persona-evidence",
                        dimension,
                        competitor,
                        strength.reason,
                        length=16,
                    ),
                    severity="blocker" if detail.execution_mode == "real" else "warn",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent=dimension,
                    target_competitor=competitor,
                    field_path=field_path,
                    problem=problem,
                    redo_scope=RedoScope(
                        kind="collector",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        rationale=f"Collect stronger public {dimension} evidence for {competitor}.",
                    ),
                    self_found=False,
                )
                issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
        return issues
```

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_collect_qa_blocks_single_low_confidence_persona_proxy backend\tests\unit\test_run_service.py::test_collect_qa_accepts_public_and_interview_persona_evidence -q
```

Expected: `2 passed`.

---

### Task 2: Persona Collector Query Expansion

**Files:**
- Modify: `backend/packages/agents/collectors/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing query test**

Add this test near `test_collector_rejects_pricing_pages_as_persona_evidence`.

```python
def test_persona_web_search_query_uses_customer_adoption_terms() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-persona-query",
        topic="AI coding assistant",
        status="running",
        execution_mode="real",
        created_at="2026-06-11T00:00:00",
        updated_at="2026-06-11T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding assistant",
            competitors=["Windsurf"],
            dimensions=["persona"],
        ),
    )

    query = service._web_search_query(detail, "Windsurf", "persona").casefold()

    for term in [
        "customers",
        "case studies",
        "developer adoption",
        "user reviews",
        "onboarding",
        "switching",
        "workflow fit",
    ]:
        assert term in query
```

- [ ] **Step 2: Run query test to verify RED**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_persona_web_search_query_uses_customer_adoption_terms -q
```

Expected: FAIL because the current query is only `Windsurf persona ... official source`.

- [ ] **Step 3: Expand persona query and signal terms**

In `backend/packages/agents/collectors/logic.py`, change `_web_search_query()`:

```python
        else:
            if self._dimension_needs_persona_strength_gate(dimension):
                query = (
                    f"{competitor} customers case studies developer adoption user reviews "
                    "onboarding switching workflow fit"
                )
            else:
                query = f"{competitor} {dimension}"
```

Change `_dimension_source_terms()` persona branch:

```python
        if "persona" in normalized or "user" in normalized:
            return [
                "persona",
                "customer",
                "customers",
                "user",
                "buyer",
                "case study",
                "customer story",
                "developer adoption",
                "review",
                "feedback",
                "workflow fit",
                "onboarding",
                "switching",
            ]
```

Change `_dimension_fact_terms()` persona branch:

```python
        if "persona" in normalized or "user" in normalized:
            return [
                "developer",
                "developers",
                "engineering team",
                "enterprise team",
                "customer adoption",
                "user reviews",
                "buyer persona",
                "workflow fit",
                "onboarding effort",
                "switching cost",
                "use case",
                "pain point",
            ]
```

Extend `_has_concrete_source_signal()`, `_has_dimension_specific_fact()`, `_dimension_terms_present()`, and `_cross_competitor_query()` with the same adoption/review/onboarding/switching/workflow terms.

- [ ] **Step 4: Run query and mismatch tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_persona_web_search_query_uses_customer_adoption_terms backend\tests\unit\test_run_service.py::test_collector_rejects_pricing_pages_as_persona_evidence -q
```

Expected: `2 passed`.

---

### Task 3: Cross-Competitor Search Must Not Skip Weak Persona Coverage

**Files:**
- Modify: `backend/packages/agents/collectors/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing cross-competitor test**

Add this test near existing cross-competitor tests.

```python
@pytest.mark.asyncio
async def test_cross_competitor_persona_search_runs_when_branch_coverage_is_weak() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            web_search_provider="perplexity",
            pplx_api_key="pplx-key",
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant persona comparison",
            competitors=["Cursor", "Windsurf"],
            dimensions=["persona"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources.extend(
        [
            RawSource(
                id="cursor-persona-public",
                competitor="Cursor",
                covered_competitors=["Cursor"],
                dimension="persona",
                source_type="webpage_verified",
                title="Cursor customer story",
                url="https://www.cursor.com/customers/example",
                snippet="Developer teams adopted Cursor for workflow fit and onboarding.",
                content_hash="cursor-persona-public-hash",
                confidence=0.92,
            ),
            RawSource(
                id="windsurf-persona-proxy",
                competitor="Windsurf",
                covered_competitors=["Windsurf"],
                dimension="persona",
                source_type="interview_record",
                title="Windsurf persona proxy",
                snippet="Proxy interview mentions workflow fit and switching risk.",
                content_hash="windsurf-persona-proxy-hash",
                confidence=0.62,
                metadata={"fallback_synthetic": True},
            ),
        ]
    )
    search_queries: list[str] = []

    async def fake_trace_search(*args, **kwargs):  # noqa: ANN202
        search_queries.append(kwargs["query"])
        return [
            SearchResult(
                title="Cursor vs Windsurf user adoption comparison",
                url="https://example.com/adoption-comparison",
                snippet="Cursor and Windsurf are compared by developer adoption, workflow fit, onboarding, and switching risk.",
            )
        ]

    async def fake_source_from_search_result(*args, **kwargs):  # noqa: ANN202
        return RawSource(
            id="persona-compare",
            competitor="Cross-model all 2 competitors",
            dimension="persona",
            source_type="webpage_verified",
            title="Cursor vs Windsurf user adoption comparison",
            url="https://example.com/adoption-comparison",
            snippet="Cursor and Windsurf developer adoption, workflow fit, onboarding, and switching risk are compared.",
            content_hash="persona-compare-hash",
            confidence=0.9,
        )

    service._trace_search = fake_trace_search  # type: ignore[method-assign]
    service._source_from_search_result = fake_source_from_search_result  # type: ignore[method-assign]

    await service._collect_cross_competitor_evidence(record, ["persona"])

    assert search_queries
    assert any(source.id == "persona-compare" for source in record.detail.raw_sources)
```

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_cross_competitor_persona_search_runs_when_branch_coverage_is_weak -q
```

Expected: FAIL because current branch coverage complete logic skips cross-competitor search.

- [ ] **Step 3: Change skip logic**

In `_collect_cross_competitor_evidence()`, replace the complete-coverage skip condition with this shape:

```python
            weak_persona_competitors = self._weak_persona_branch_competitors(detail, dimension)
            if len(covered_competitors) >= len(detail.plan.competitors) and not weak_persona_competitors:
                await self.emit(...)
                continue
```

Add helper:

```python
    def _weak_persona_branch_competitors(
        self,
        detail: RunDetail,
        dimension: str,
    ) -> list[str]:
        if not self._dimension_needs_persona_strength_gate(dimension):
            return []
        weak: list[str] = []
        for competitor in detail.plan.competitors:
            strength = self._persona_evidence_strength(detail, dimension, competitor)
            if strength.is_weak and strength.reason != "no_sources":
                weak.append(competitor)
        return weak
```

Include `weak_persona_competitors` in the skipped event payload only when skipping:

```python
"weak_persona_competitors": weak_persona_competitors,
```

- [ ] **Step 4: Run cross-competitor tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_cross_competitor_persona_search_runs_when_branch_coverage_is_weak backend\tests\unit\test_run_service.py::test_cross_competitor_search_marks_only_mentioned_competitors -q
```

Expected: `2 passed`.

---

### Task 4: Deficit-Driven Survey/Interview Enrichment

**Files:**
- Modify: `backend/packages/agents/survey/logic.py`
- Test: `backend/tests/unit/test_survey_interview_agent.py`

- [ ] **Step 1: Write failing enrichment test**

Add this test after `test_survey_interview_enrichment_reuses_attached_user_research()`.

```python
@pytest.mark.asyncio
async def test_survey_interview_enrichment_runs_for_weak_existing_persona_source() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant user adoption comparison",
            competitors=["Windsurf"],
            dimensions=["persona"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources.append(
        RawSource(
            id="windsurf-persona-proxy",
            competitor="Windsurf",
            covered_competitors=["Windsurf"],
            dimension="persona",
            source_type="interview_record",
            title="Windsurf persona proxy",
            snippet="Proxy interview mentions workflow fit and switching risk.",
            content_hash="windsurf-persona-proxy-hash",
            confidence=0.62,
            metadata={"fallback_synthetic": True},
        )
    )

    await service._run_survey_interview_enrichment(record, ["persona"], ["Windsurf"])

    assert len(record.detail.raw_sources) == 3
    added = [source for source in record.detail.raw_sources if source.id != "windsurf-persona-proxy"]
    assert {source.source_type for source in added} == {"survey_simulated", "interview_record"}
    assert all(source.metadata["fallback_synthetic"] is True for source in added)
```

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_survey_interview_agent.py::test_survey_interview_enrichment_runs_for_weak_existing_persona_source -q
```

Expected: FAIL because `_has_user_research_source()` currently skips enrichment as soon as one user-research source exists.

- [ ] **Step 3: Change enrichment skip rule**

In `_run_survey_interview_enrichment()`, replace:

```python
                if self._has_user_research_source(detail, dimension, competitor):
                    continue
```

with:

```python
                if self._has_strong_user_research_source(detail, dimension, competitor):
                    continue
```

Add helper:

```python
    def _has_strong_user_research_source(
        self,
        detail: RunDetail,
        dimension: str,
        competitor: str,
    ) -> bool:
        if not self._has_user_research_source(detail, dimension, competitor):
            return False
        if not self._dimension_needs_persona_strength_gate(dimension):
            return True
        return not self._persona_evidence_strength(detail, dimension, competitor).is_weak
```

In `_sources_from_survey_bundle()`, add metadata to both generated `RawSource` objects:

```python
metadata={
    "fallback_synthetic": True,
    "survey_interview_synthetic": True,
    "source_role": "survey",
},
```

and:

```python
metadata={
    "fallback_synthetic": True,
    "survey_interview_synthetic": True,
    "source_role": "interview",
},
```

- [ ] **Step 4: Run survey tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_survey_interview_agent.py::test_survey_interview_enrichment_runs_for_weak_existing_persona_source backend\tests\unit\test_survey_interview_agent.py::test_survey_interview_enrichment_reuses_attached_user_research -q
```

Expected: all parametrized cases pass, and the new weak-source test passes.

---

### Task 5: Integration Regression and Verification

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write collect QA retry regression**

Add this test near `test_collect_qa_blocks_and_retries_collector_before_analyst()`.

```python
@pytest.mark.asyncio
async def test_weak_persona_collect_qa_retries_collector_before_analyst() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )
    order: list[str] = []
    collector_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        order.append("planner")

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        nonlocal collector_calls
        collector_calls += 1
        order.append(f"collector:{collector_calls}")
        if collector_calls == 1:
            record.detail.raw_sources.append(
                RawSource(
                    id="windsurf-persona-proxy",
                    competitor=competitor,
                    covered_competitors=[competitor],
                    dimension=dimension,
                    source_type="interview_record",
                    title="Windsurf persona proxy",
                    snippet="Proxy interview mentions workflow fit and switching risk.",
                    content_hash="windsurf-persona-proxy-hash",
                    confidence=0.62,
                    metadata={"fallback_synthetic": True},
                )
            )
            return
        record.detail.raw_sources.append(
            RawSource(
                id="windsurf-persona-customer-story",
                competitor=competitor,
                covered_competitors=[competitor],
                dimension=dimension,
                source_type="webpage_verified",
                title="Windsurf customer adoption story",
                url="https://windsurf.com/customers/example",
                snippet="Developers and engineering teams adopted Windsurf for workflow fit, onboarding, and switching cost reduction.",
                content_hash="windsurf-persona-customer-story-hash",
                confidence=0.92,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append("analyst")
        service._merge_competitor_kb_slice(
            record.detail,
            competitor,
            dimension,
            ["Windsurf serves developer teams evaluating workflow fit. [source:windsurf-persona-customer-story]"],
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        order.append("comparator")
        record.detail.comparison_matrix = service._build_comparison_matrix(record.detail, {})

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        order.append("reflector")

    async def fake_writer(record):  # noqa: ANN001, ANN202
        order.append("writer")
        record.detail.report_md = "Windsurf targets developer teams. [source:windsurf-persona-customer-story]"

    async def fake_qa(record):  # noqa: ANN001, ANN202
        order.append("qa")
        record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Persona collect gate",
                competitors=["Windsurf"],
                dimensions=["persona"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        assert order == [
            "planner",
            "collector:1",
            "collector:2",
            "analyst",
            "comparator",
            "reflector",
            "writer",
            "qa",
        ]
        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.qa_findings == []
    finally:
        await service._graph_checkpointer.aclose()
```

- [ ] **Step 2: Run integration regression**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_weak_persona_collect_qa_retries_collector_before_analyst -q
```

Expected: PASS after Tasks 1-4.

- [ ] **Step 3: Run focused suites**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py backend\tests\unit\test_survey_interview_agent.py backend\tests\unit\test_review_theme_summary.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Run lint**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\qa\logic.py backend\packages\agents\collectors\logic.py backend\packages\agents\survey\logic.py backend\tests\unit\test_run_service.py backend\tests\unit\test_survey_interview_agent.py
```

Expected: `All checks passed!`

- [ ] **Step 5: Check diff**

Run:

```powershell
git diff --check -- backend/packages/agents/qa/logic.py backend/packages/agents/collectors/logic.py backend/packages/agents/survey/logic.py backend/tests/unit/test_run_service.py backend/tests/unit/test_survey_interview_agent.py
```

Expected: exit code `0`. CRLF warnings are acceptable only if they are warnings and the command exits `0`.

---

## Self-Review

- Spec coverage: Task 1 covers deterministic evidence strength and collect QA weak issue routing. Task 2 covers broader persona discovery query and signal matching. Task 3 covers cross-competitor fallback when branch coverage is weak. Task 4 covers deficit-driven survey/interview enrichment and synthetic fallback metadata. Task 5 covers graph retry behavior and verification.
- Placeholder scan: This plan avoids `TBD`, `TODO`, `implement later`, and placeholder test names. Each code-changing step includes concrete method names, snippets, and commands.
- Type consistency: `PersonaEvidenceStrength`, `_dimension_needs_persona_strength_gate()`, `_persona_evidence_strength()`, and `_weak_persona_branch_competitors()` are used consistently across QA, collector, and survey mixins. `RawSource.metadata` already exists as `dict[str, Any]`, so fallback metadata needs no schema change.
