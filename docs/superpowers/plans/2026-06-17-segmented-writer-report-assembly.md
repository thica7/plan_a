# Segmented Writer Report Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make segmented writer output assemble into one coherent, section-complete competitive-intelligence report without duplicate core sections, misplaced support sections, or avoidable full rewrites.

**Architecture:** Add explicit segment contracts, deterministic report assembly, final structural preflight, and redo routing before changing the source-rich evidence pack. Then convert budget-split writer calls into evidence shards that feed one canonical section writer per report area.

**Tech Stack:** Python, dataclasses, existing pytest suite, existing `RunDetail` schema, existing `report_label()` localization, existing writer evidence-pack and report-quality helpers.

---

## Context

The current code already has strong evidence-pack and citation work, but report assembly is still too loose:

- `backend/packages/agents/writer/evidence_pack.py::segment_inputs()` splits large inputs by source, group, dimension, and fact, but each returned dict is still treated as a Markdown-writing segment.
- `backend/packages/agents/writer/logic.py::_writer_segmented_report_markdown()` loops over `segment_inputs()`, validates citations, then joins segment Markdown with `"\n\n".join(...)`.
- `backend/packages/agents/writer/logic.py::_normalize_report_section_order()` reorders known headings but does not merge duplicate H2 sections or enforce the core/support boundary strongly enough.
- `backend/packages/agents/writer/repair.py::build_writer_repair_plan()` currently maps `release_gate.report_depth_required` to `mode="full"` before checking whether the root cause is deterministic structure damage.
- `backend/packages/business_intel/report_quality.py` scores report quality after the final report is built; it already exposes the failure signals the writer path needs to preflight earlier.

The run that exposed the failure shape was `run-fd5b86355cff04844d92f1a15e197bfe`. It produced 10 writer segments, duplicate `## Decision Summary`, duplicate support sections, and competitor deep dives after support material.

## File Map

- Create `backend/packages/agents/writer/segment_contract.py`
  - Own segment kind, allowed heading, forbidden heading, and contract validation logic.
- Create `backend/tests/unit/test_writer_segment_contract.py`
  - Unit tests for segment heading contracts without requiring the run service.
- Create `backend/packages/agents/writer/assembler.py`
  - Own deterministic H2 parsing, canonical section keys, duplicate merge, ordering, and assembly telemetry.
- Create `backend/tests/unit/test_writer_report_assembler.py`
  - Unit tests for run-fd-shaped duplicate and support-order repair.
- Create `backend/packages/agents/writer/quality_preflight.py`
  - Own final writer structural preflight before QA/release gate.
- Create `backend/tests/unit/test_writer_quality_preflight.py`
  - Unit tests for duplicate, support-order, and required-core checks.
- Modify `backend/packages/agents/writer/evidence_pack.py`
  - Add segment metadata fields and evidence-shard planning helpers.
- Modify `backend/packages/agents/writer/logic.py`
  - Validate segment contracts, call assembler, run preflight, route assembler repair, and tighten segment prompts.
- Modify `backend/packages/agents/writer/repair.py`
  - Add `assemble` repair mode and deterministic report-structure routing.
- Modify `backend/tests/unit/test_run_service.py`
  - Add integration-style regressions around segment retry, assembly, events, and redo routing.
- Keep generated artifacts, DB files, output reports, and untracked packaging files out of commits.

## Shared Test Fixtures

When adding segmented-writer tests to `backend/tests/unit/test_run_service.py`, add these helpers once near the existing writer tests if equivalent helpers are not already present:

Add this import near the existing imports:

```python
from packages.identity.source_resolver import source_tokens
```

```python
class _SegmentedWriterFakeMetrics:
    segmented_writer_required = True


class _SegmentedWriterFakePack:
    metrics = _SegmentedWriterFakeMetrics()

    def __init__(self, segments: list[dict[str, object]]) -> None:
        self._segments = segments

    def telemetry_payload(self) -> dict[str, object]:
        return {
            "raw_source_count": len(
                {
                    source_id
                    for segment in self._segments
                    for source_id in segment.get("allowed_source_ids", [])
                }
            ),
            "represented_source_count": len(
                {
                    source_id
                    for segment in self._segments
                    for source_id in segment.get("allowed_source_ids", [])
                }
            ),
            "dropped_source_count": 0,
            "segmented_writer_required": True,
        }

    def preflight_errors(self) -> list[str]:
        return []

    def to_prompt_json(self) -> str:
        raise AssertionError("segmented writer tests must not serialize the full pack")

    def segment_inputs(self) -> list[dict[str, object]]:
        return list(self._segments)

    def validate_segment_citations(
        self,
        markdown: str,
        *,
        allowed_source_ids: set[str],
    ) -> list[str]:
        cited = source_tokens(markdown)
        return sorted(token for token in cited if token not in allowed_source_ids)

    def sanitize_segment_citations(
        self,
        markdown: str,
        *,
        allowed_source_ids: set[str],
    ) -> str:
        return markdown


def _segmented_writer_service() -> RunService:
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=10,
        ),
    )


def _segmented_writer_detail(
    *,
    run_id: str = "run-segmented-writer-test",
    competitors: list[str] | None = None,
    report_md: str | None = None,
) -> RunDetail:
    return RunDetail(
        id=run_id,
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        created_at=_now(),
        updated_at=_now(),
        output_language="en-US",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=competitors or ["Cursor"],
            dimensions=["feature", "pricing", "persona"],
        ),
        raw_sources=[],
        report_md=report_md,
    )


def _segmented_writer_record(
    service: RunService,
    *,
    competitors: list[str] | None = None,
    report_md: str | None = None,
) -> RunRecord:
    detail = _segmented_writer_detail(competitors=competitors, report_md=report_md)
    record = RunRecord(detail=detail)
    service._runs[detail.id] = record
    return record


def _qc_issue(field_path: str, problem: str) -> QCIssue:
    return QCIssue(
        id=f"issue-{field_path.replace('.', '-')}",
        severity="blocker",
        detected_by="release_gate",
        target_agent="writer",
        field_path=field_path,
        problem=problem,
    )
```

## Acceptance Criteria

- A budget-split `decision_summary` no longer creates multiple final `## Decision Summary` sections.
- `competitor_deep_dives` content appears before the first support/audit section.
- Support/audit sections do not hide core analysis before the release gate sees it.
- Segment output that violates its heading contract is retried once with a precise error.
- Segment output that still violates an essential contract fails with a clear writer exception.
- Deterministic duplicate/support-order issues route to `assemble`, not `full`, in writer redo.
- Final preflight emits telemetry explaining duplicate count, missing core sections, core-after-support sections, and routing.
- Existing citation sanitizer behavior remains strict: legal source IDs are normalized, unknown IDs still fail.
- Full tests listed in Task 10 pass in conda env `bd-competiscope-v2`.

## Task 1: Segment Contract Module

**Files:**
- Create: `backend/packages/agents/writer/segment_contract.py`
- Create: `backend/tests/unit/test_writer_segment_contract.py`

- [ ] **Step 1: Write failing contract tests**

Create `backend/tests/unit/test_writer_segment_contract.py` with this content:

```python
from __future__ import annotations

from packages.agents.writer.segment_contract import (
    SegmentContract,
    segment_contract_for,
    validate_segment_contract,
)


def test_decision_summary_contract_rejects_support_heading() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "decision_summary",
            "segment_kind": "section_fragment",
            "section_id": "decision_summary",
            "output_language": "en-US",
        }
    )

    result = validate_segment_contract(
        "## Decision Summary\nKeep.\n\n## Evidence and QA Support\nWrong place.",
        contract,
    )

    assert result.status == "retry"
    assert result.forbidden_headings == ["Evidence and QA Support"]
    assert "evidence_support" in result.forbidden_heading_keys


def test_competitor_deep_dive_contract_rejects_full_report_heading() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "competitor_deep_dives",
            "segment_kind": "section_fragment",
            "section_id": "competitor_deep_dives",
            "segment_competitor": "Cursor",
            "output_language": "en-US",
        }
    )

    result = validate_segment_contract(
        "## Decision Summary\nWrong.\n\n## Competitor Deep Dives\n### Cursor\nCorrect.",
        contract,
    )

    assert result.status == "retry"
    assert result.forbidden_headings == ["Decision Summary"]
    assert "decision_summary" in result.forbidden_heading_keys


def test_support_contract_rejects_core_deep_dive_heading() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "support_appendix",
            "segment_kind": "support_fragment",
            "section_id": "evidence_support",
            "output_language": "en-US",
        }
    )

    result = validate_segment_contract(
        "## Evidence and QA Support\nUseful.\n\n## Competitor Deep Dives\nWrong.",
        contract,
    )

    assert result.status == "retry"
    assert result.forbidden_headings == ["Competitor Deep Dives"]
    assert "competitor_deep_dives" in result.forbidden_heading_keys


def test_evidence_shard_contract_rejects_any_h2() -> None:
    contract = SegmentContract(
        segment_name="decision_summary:sources:1",
        segment_kind="evidence_shard",
        section_id="decision_summary",
        output_language="en-US",
        allowed_heading_keys=(),
        forbidden_heading_keys=(),
        allow_h2=False,
        essential=True,
    )

    result = validate_segment_contract("## Decision Summary\nNot allowed.", contract)

    assert result.status == "retry"
    assert result.h2_headings == ["Decision Summary"]
    assert result.errors == ["evidence_shard must not contain H2 headings"]


def test_valid_user_research_contract_passes_localized_heading() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "user_research",
            "segment_kind": "section_fragment",
            "section_id": "review_theme_summary",
            "output_language": "zh-CN",
        }
    )

    result = validate_segment_contract(
        "## 用户评价整理\n- 采用障碍来自价格和 IDE 迁移成本 [source:raw-source-a].",
        contract,
    )

    assert result.status == "pass"
    assert result.h2_headings == ["用户评价整理"]
    assert result.forbidden_headings == []
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_segment_contract.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'packages.agents.writer.segment_contract'`.

- [ ] **Step 3: Implement `segment_contract.py`**

Create `backend/packages/agents/writer/segment_contract.py` with this content:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Mapping

from packages.i18n.language import report_label

SegmentKind = Literal["evidence_shard", "section_fragment", "support_fragment", "final_report"]
SegmentValidationStatus = Literal["pass", "retry", "fail"]

H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")

CORE_HEADING_KEYS: tuple[str, ...] = (
    "executive_summary",
    "executive_takeaway",
    "decision_summary",
    "competitive_findings",
    "review_theme_summary",
    "competitor_deep_dives",
    "comparison_matrix",
    "side_by_side_matrix",
    "swot_analysis",
    "battlecard",
    "community_evidence_triangulation",
    "workflow_enterprise_risk",
    "market_landscape",
    "business_implications",
)

SUPPORT_HEADING_KEYS: tuple[str, ...] = (
    "evidence_support",
    "source_quality",
    "memory_context",
    "user_research_evidence",
    "rag_gap_fill",
    "scenario_checklist",
    "claim_risk",
    "next_collection",
    "evidence_appendix",
    "generation_notes",
)

SECTION_ALLOWED_KEYS: dict[str, tuple[str, ...]] = {
    "decision_summary": (
        "executive_summary",
        "executive_takeaway",
        "decision_summary",
        "competitive_findings",
    ),
    "competitive_findings": ("competitive_findings",),
    "review_theme_summary": (
        "review_theme_summary",
        "community_evidence_triangulation",
    ),
    "competitor_deep_dives": ("competitor_deep_dives",),
    "swot_matrix": (
        "comparison_matrix",
        "side_by_side_matrix",
        "swot_analysis",
        "battlecard",
        "workflow_enterprise_risk",
        "market_landscape",
        "business_implications",
    ),
    "evidence_support": SUPPORT_HEADING_KEYS,
}

HEADING_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "executive_summary": ("executive summary", "执行摘要"),
    "executive_takeaway": ("executive takeaway", "管理层要点"),
    "decision_summary": ("decision summary", "决策摘要"),
    "competitive_findings": ("competitive findings", "竞争发现"),
    "review_theme_summary": ("user review themes", "review theme summary", "用户评价整理"),
    "competitor_deep_dives": ("competitor deep dives", "竞品深挖"),
    "comparison_matrix": ("comparison matrix", "对比矩阵"),
    "side_by_side_matrix": ("side-by-side decision matrix", "side by side decision matrix", "横向决策矩阵"),
    "swot_analysis": ("swot analysis", "swot 分析"),
    "battlecard": ("battlecard", "战报"),
    "community_evidence_triangulation": ("community evidence triangulation", "社区证据交叉验证"),
    "workflow_enterprise_risk": ("workflow and enterprise risk", "workflow enterprise risk", "工作流与企业风险"),
    "market_landscape": ("market landscape", "市场格局"),
    "business_implications": ("business implications", "商业影响"),
    "evidence_support": ("evidence and qa support", "证据与 qa 支撑"),
    "source_quality": ("source quality and coverage", "来源质量与覆盖"),
    "memory_context": ("memory context", "记忆上下文"),
    "user_research_evidence": ("user research evidence", "用户研究证据"),
    "rag_gap_fill": ("rag gap fill", "rag 缺口补齐"),
    "scenario_checklist": ("scenario qa checklist", "场景 qa 清单"),
    "claim_risk": ("claim validation and evidence risk", "声明验证与证据风险"),
    "next_collection": ("next collection and validation plan", "下一步采集与验证计划"),
    "evidence_appendix": ("evidence appendix", "证据附录"),
    "generation_notes": ("generation notes", "生成说明"),
}


@dataclass(frozen=True)
class SegmentContract:
    segment_name: str
    segment_kind: SegmentKind
    section_id: str
    output_language: str
    allowed_heading_keys: tuple[str, ...] = field(default_factory=tuple)
    forbidden_heading_keys: tuple[str, ...] = field(default_factory=tuple)
    allow_h2: bool = True
    essential: bool = True


@dataclass(frozen=True)
class SegmentValidationResult:
    status: SegmentValidationStatus
    errors: list[str] = field(default_factory=list)
    h2_headings: list[str] = field(default_factory=list)
    forbidden_headings: list[str] = field(default_factory=list)
    forbidden_heading_keys: list[str] = field(default_factory=list)
    invalid_heading_keys: list[str] = field(default_factory=list)


def segment_contract_for(segment: Mapping[str, object]) -> SegmentContract:
    segment_name = str(segment.get("segment_name") or "")
    segment_kind = _segment_kind(segment)
    section_id = _section_id(segment_name, segment)
    output_language = str(segment.get("output_language") or "en-US")
    essential = bool(segment.get("segment_essential", True))

    if segment_kind == "evidence_shard":
        return SegmentContract(
            segment_name=segment_name,
            segment_kind=segment_kind,
            section_id=section_id,
            output_language=output_language,
            allowed_heading_keys=(),
            forbidden_heading_keys=(),
            allow_h2=False,
            essential=essential,
        )

    allowed = SECTION_ALLOWED_KEYS.get(section_id, SECTION_ALLOWED_KEYS.get(segment_name, (section_id,)))
    forbidden_source = SUPPORT_HEADING_KEYS if section_id in CORE_HEADING_KEYS else CORE_HEADING_KEYS
    forbidden = tuple(key for key in forbidden_source if key not in allowed)
    return SegmentContract(
        segment_name=segment_name,
        segment_kind=segment_kind,
        section_id=section_id,
        output_language=output_language,
        allowed_heading_keys=allowed,
        forbidden_heading_keys=forbidden,
        allow_h2=True,
        essential=essential,
    )


def validate_segment_contract(markdown: str, contract: SegmentContract) -> SegmentValidationResult:
    headings = _h2_headings(markdown)
    if not markdown.strip():
        return SegmentValidationResult(status="fail", errors=["segment output is empty"])
    if not contract.allow_h2 and headings:
        return SegmentValidationResult(
            status="retry",
            errors=[f"{contract.segment_kind} must not contain H2 headings"],
            h2_headings=headings,
        )

    forbidden_headings: list[str] = []
    forbidden_keys: list[str] = []
    invalid_keys: list[str] = []
    allowed = set(contract.allowed_heading_keys)
    forbidden = set(contract.forbidden_heading_keys)

    for heading in headings:
        key = heading_key_for(heading, contract.output_language)
        if key in forbidden:
            forbidden_headings.append(heading)
            forbidden_keys.append(key)
        elif key and allowed and key not in allowed and contract.segment_kind != "final_report":
            invalid_keys.append(key)

    errors: list[str] = []
    if forbidden_headings:
        errors.append("segment contains forbidden H2 headings")
    if invalid_keys:
        errors.append("segment contains H2 headings outside its allowed contract")
    if errors:
        return SegmentValidationResult(
            status="retry",
            errors=errors,
            h2_headings=headings,
            forbidden_headings=forbidden_headings,
            forbidden_heading_keys=forbidden_keys,
            invalid_heading_keys=invalid_keys,
        )
    return SegmentValidationResult(status="pass", h2_headings=headings)


def heading_key_for(heading: str, output_language: str) -> str | None:
    normalized = _normalize_heading(heading)
    for key, aliases in HEADING_KEY_ALIASES.items():
        localized = _normalize_heading(report_label(output_language, key))
        if normalized == localized:
            return key
        for alias in aliases:
            if normalized == _normalize_heading(alias):
                return key
    return None


def _segment_kind(segment: Mapping[str, object]) -> SegmentKind:
    raw = str(segment.get("segment_kind") or "")
    if raw in {"evidence_shard", "section_fragment", "support_fragment", "final_report"}:
        return raw  # type: ignore[return-value]
    if str(segment.get("segment_name") or "") == "support_appendix":
        return "support_fragment"
    return "section_fragment"


def _section_id(segment_name: str, segment: Mapping[str, object]) -> str:
    explicit = str(segment.get("section_id") or "")
    if explicit:
        return explicit
    if segment_name == "user_research":
        return "review_theme_summary"
    if segment_name == "support_appendix":
        return "evidence_support"
    return segment_name


def _h2_headings(markdown: str) -> list[str]:
    return [match.group(1).strip() for match in H2_RE.finditer(markdown)]


def _normalize_heading(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip().lower())
    return text.replace("—", "-").replace("–", "-")
```

- [ ] **Step 4: Run the contract tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_segment_contract.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add backend/packages/agents/writer/segment_contract.py backend/tests/unit/test_writer_segment_contract.py
git commit -m "feat: add writer segment contracts"
```

Expected: commit succeeds and generated artifacts remain untracked.

## Task 2: Segment Contract Integration

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/packages/agents/writer/evidence_pack.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing run-service tests for segment contract retry**

Add tests near existing segmented-writer tests in `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_segmented_writer_retries_when_segment_uses_forbidden_heading(monkeypatch):
    service = _segmented_writer_service()
    record = _segmented_writer_record(service, competitors=["Cursor"])
    pack = _SegmentedWriterFakePack(
        [
            {
                "segment_name": "competitor_deep_dives",
                "segment_kind": "section_fragment",
                "section_id": "competitor_deep_dives",
                "output_language": "en-US",
                "segment_competitor": "Cursor",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-a"],
                "groups": [],
                "sources": [],
            }
        ]
    )
    calls = []

    async def fake_segment_writer(*args, **kwargs):
        calls.append(kwargs["retry_count"])
        if kwargs["retry_count"] == 0:
            return "## Decision Summary\nWrong.\n\n## Competitor Deep Dives\n### Cursor\nThin [source:raw-source-a]."
        return "## Competitor Deep Dives\n### Cursor\nFixed [source:raw-source-a]."

    monkeypatch.setattr(service, "_writer_segment_markdown", fake_segment_writer)

    report = await service._writer_segmented_report_markdown(
        record,
        evidence_pack_result=pack,
        timeout_seconds=60,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
    )

    assert calls == [0, 1]
    assert "## Decision Summary" not in report
    assert "## Competitor Deep Dives" in report
    assert "Fixed [source:raw-source-a]" in report


@pytest.mark.asyncio
async def test_segmented_writer_fails_when_contract_retry_still_invalid(monkeypatch):
    service = _segmented_writer_service()
    record = _segmented_writer_record(service, competitors=["Cursor"])
    pack = _SegmentedWriterFakePack(
        [
            {
                "segment_name": "support_appendix",
                "segment_kind": "support_fragment",
                "section_id": "evidence_support",
                "output_language": "en-US",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-a"],
                "groups": [],
                "sources": [],
            }
        ]
    )

    async def fake_segment_writer(*args, **kwargs):
        return "## Evidence and QA Support\nSupport.\n\n## Competitor Deep Dives\nWrong [source:raw-source-a]."

    monkeypatch.setattr(service, "_writer_segment_markdown", fake_segment_writer)

    with pytest.raises(RuntimeError, match="Writer segment violated heading contract after retry"):
        await service._writer_segmented_report_markdown(
            record,
            evidence_pack_result=pack,
            timeout_seconds=60,
            language_guidance="",
            memory_context="",
            layer_context="",
            required_sections="",
        )
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_run_service.py::test_segmented_writer_retries_when_segment_uses_forbidden_heading tests/unit/test_run_service.py::test_segmented_writer_fails_when_contract_retry_still_invalid -q
```

Expected: fails because `_writer_segmented_report_markdown()` does not validate segment heading contracts.

- [ ] **Step 3: Add segment metadata to evidence-pack segments**

Modify segment builders in `backend/packages/agents/writer/evidence_pack.py` so every segment dict includes these keys:

```python
"segment_kind": "section_fragment",
"section_id": "decision_summary",
"output_language": self.detail.output_language,
"segment_essential": True,
```

Use this mapping:

```python
SEGMENT_SECTION_IDS = {
    "decision_summary": "decision_summary",
    "user_research": "review_theme_summary",
    "competitor_deep_dives": "competitor_deep_dives",
    "swot_matrix": "swot_matrix",
    "support_appendix": "evidence_support",
}
```

For `support_appendix`, set:

```python
"segment_kind": "support_fragment",
"segment_essential": False,
```

For all current source-batched splits in this task, keep `segment_kind="section_fragment"`. Task 8 changes budget-split branches to `evidence_shard`.

- [ ] **Step 4: Wire contract validation into segmented writer**

Modify imports in `backend/packages/agents/writer/logic.py`:

```python
from packages.agents.writer.segment_contract import (
    segment_contract_for,
    validate_segment_contract,
)
```

In `_writer_segmented_report_markdown()`, after citation validation succeeds and before `sections.append(...)`, add:

```python
contract = segment_contract_for(segment)
validation = validate_segment_contract(segment_md, contract)
await self.emit(
    detail.id,
    "writer_segment_validated",
    "writer",
    None,
    f"Writer segment validated: {segment['segment_name']}",
    {
        "segment_name": segment["segment_name"],
        "segment_kind": contract.segment_kind,
        "section_id": contract.section_id,
        "validation_status": validation.status,
        "validation_errors": validation.errors,
        "h2_headings": validation.h2_headings,
        "forbidden_headings": validation.forbidden_headings,
        "forbidden_heading_keys": validation.forbidden_heading_keys,
        "invalid_heading_keys": validation.invalid_heading_keys,
        "segment_retry_count": 0,
    },
)
if validation.status != "pass":
    segment_md = await self._writer_segment_markdown(
        record,
        segment=segment,
        timeout_seconds=timeout_seconds,
        language_guidance=language_guidance,
        memory_context=memory_context,
        layer_context=layer_context,
        required_sections=required_sections,
        retry_count=1,
        contract_errors=validation.errors,
        contract_forbidden_headings=validation.forbidden_headings,
    )
    segment_md = self._sanitize_writer_segment_citations(
        evidence_pack_result,
        segment_md,
        allowed_source_ids=allowed_source_ids,
    )
    invalid_sources = evidence_pack_result.validate_segment_citations(
        segment_md,
        allowed_source_ids=allowed_source_ids,
    )
    if invalid_sources:
        raise RuntimeError(
            "Writer segment cited invalid source IDs after contract retry: "
            f"{', '.join(invalid_sources)}"
        )
    validation = validate_segment_contract(segment_md, contract)
    if validation.status != "pass":
        raise RuntimeError(
            "Writer segment violated heading contract after retry: "
            f"{segment['segment_name']}: {', '.join(validation.errors)}"
        )
```

Extend `_writer_segment_markdown()` signature with:

```python
contract_errors: list[str] | None = None,
contract_forbidden_headings: list[str] | None = None,
```

Build `contract_warning` before the LLM call:

```python
contract_warning = ""
if contract_errors:
    forbidden = ", ".join(contract_forbidden_headings or [])
    contract_warning = (
        "Previous segment violated its heading contract: "
        f"{'; '.join(contract_errors)}. "
        f"Forbidden H2 headings found: {forbidden or 'none'}. "
        "Rewrite only this segment and obey the segment contract exactly.\n"
    )
```

Add `contract_warning` to the user prompt next to `citation_warning`.

- [ ] **Step 5: Tighten segment prompt contract text**

In `_writer_segment_markdown()`, include these explicit lines in the user prompt:

```python
f"segment_kind={segment.get('segment_kind', 'section_fragment')}\n"
f"section_id={segment.get('section_id', segment['segment_name'])}\n"
"Do not write headings outside this segment's contract. "
"Do not write support or appendix sections unless segment_kind=support_fragment. "
"If segment_kind=evidence_shard, do not write any ## H2 headings.\n"
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_segment_contract.py tests/unit/test_run_service.py::test_segmented_writer_retries_when_segment_uses_forbidden_heading tests/unit/test_run_service.py::test_segmented_writer_fails_when_contract_retry_still_invalid -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
git add backend/packages/agents/writer/evidence_pack.py backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: validate writer segment contracts"
```

Expected: commit succeeds and untracked generated artifacts remain untracked.

## Task 3: Deterministic Report Assembler

**Files:**
- Create: `backend/packages/agents/writer/assembler.py`
- Create: `backend/tests/unit/test_writer_report_assembler.py`

- [ ] **Step 1: Write failing assembler tests**

Create `backend/tests/unit/test_writer_report_assembler.py`:

```python
from __future__ import annotations

from packages.agents.writer.assembler import assemble_report_sections
from packages.i18n.language import report_label


def test_assembler_merges_duplicate_sections_and_moves_support_after_core() -> None:
    sections = [
        "## Decision Summary\nFirst decision [source:raw-source-a].",
        "## Evidence and QA Support\nSupport first [source:raw-source-b].",
        "## Decision Summary\nSecond decision [source:raw-source-c].",
        "## Competitor Deep Dives\n### GitHub Copilot\nDeep dive [source:raw-source-d].",
        "## Evidence and QA Support\nSupport second [source:raw-source-e].",
        "## SWOT Analysis\nStrengths and risks [source:raw-source-f].",
    ]

    assembled = assemble_report_sections(
        sections,
        output_language="en-US",
        competitors=["GitHub Copilot"],
    )

    report = assembled.markdown
    assert report.count("## Decision Summary") == 1
    assert report.count("## Evidence and QA Support") == 1
    assert report.index("## Competitor Deep Dives") < report.index("## Evidence and QA Support")
    assert report.index("## SWOT Analysis") < report.index("## Evidence and QA Support")
    assert "First decision [source:raw-source-a]." in report
    assert "Second decision [source:raw-source-c]." in report
    assert assembled.telemetry["duplicate_section_count_before"] == 2
    assert assembled.telemetry["duplicate_section_count_after"] == 0
    assert "decision_summary" in assembled.telemetry["merged_section_keys"]
    assert "evidence_support" in assembled.telemetry["merged_section_keys"]


def test_assembler_preserves_unknown_core_before_support() -> None:
    sections = [
        "## Custom Core Insight\nA useful custom section [source:raw-source-a].",
        "## Evidence Appendix\nAppendix [source:raw-source-b].",
    ]

    assembled = assemble_report_sections(
        sections,
        output_language="en-US",
        competitors=[],
    )

    assert assembled.markdown.index("## Custom Core Insight") < assembled.markdown.index("## Evidence Appendix")
    assert assembled.telemetry["unknown_core_section_count"] == 1


def test_assembler_handles_zh_labels() -> None:
    decision = report_label("zh-CN", "decision_summary")
    support = report_label("zh-CN", "evidence_support")
    deep_dive = report_label("zh-CN", "competitor_deep_dives")

    assembled = assemble_report_sections(
        [
            f"## {support}\n支撑材料 [source:raw-source-b].",
            f"## {deep_dive}\n### Cursor\n深挖 [source:raw-source-c].",
            f"## {decision}\n决策 [source:raw-source-a].",
        ],
        output_language="zh-CN",
        competitors=["Cursor"],
    )

    assert assembled.markdown.index(f"## {decision}") < assembled.markdown.index(f"## {support}")
    assert assembled.markdown.index(f"## {deep_dive}") < assembled.markdown.index(f"## {support}")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_report_assembler.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'packages.agents.writer.assembler'`.

- [ ] **Step 3: Implement assembler module**

Create `backend/packages/agents/writer/assembler.py` with deterministic parsing and ordering:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from packages.agents.writer.segment_contract import (
    SUPPORT_HEADING_KEYS,
    heading_key_for,
)
from packages.i18n.language import report_label

H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")

CANONICAL_REPORT_ORDER: tuple[str, ...] = (
    "executive_summary",
    "executive_takeaway",
    "decision_summary",
    "competitive_findings",
    "review_theme_summary",
    "competitor_deep_dives",
    "comparison_matrix",
    "side_by_side_matrix",
    "swot_analysis",
    "battlecard",
    "community_evidence_triangulation",
    "workflow_enterprise_risk",
    "market_landscape",
    "business_implications",
    "evidence_support",
    "source_quality",
    "memory_context",
    "user_research_evidence",
    "rag_gap_fill",
    "scenario_checklist",
    "claim_risk",
    "next_collection",
    "evidence_appendix",
    "generation_notes",
)


@dataclass(frozen=True)
class AssembledReport:
    markdown: str
    telemetry: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MarkdownBlock:
    heading: str | None
    key: str | None
    body: str
    ordinal: int


def assemble_report_sections(
    markdown_sections: Sequence[str],
    *,
    output_language: object,
    competitors: Sequence[str],
) -> AssembledReport:
    blocks = _parse_blocks(markdown_sections, str(output_language))
    intro_blocks = [block for block in blocks if block.heading is None and block.body.strip()]
    known_by_key: dict[str, list[MarkdownBlock]] = {}
    unknown_core: list[MarkdownBlock] = []
    unknown_support: list[MarkdownBlock] = []

    for block in blocks:
        if block.heading is None:
            continue
        if block.key:
            known_by_key.setdefault(block.key, []).append(block)
        elif _looks_like_support(block.heading):
            unknown_support.append(block)
        else:
            unknown_core.append(block)

    ordered_blocks: list[MarkdownBlock] = []
    ordered_blocks.extend(intro_blocks)
    ordered_blocks.extend(unknown_core)
    for key in CANONICAL_REPORT_ORDER:
        ordered_blocks.extend(_merge_known_blocks(key, known_by_key.get(key, []), str(output_language)))
    ordered_blocks.extend(unknown_support)

    rendered = "\n\n".join(_render_block(block) for block in ordered_blocks if block.body.strip()).strip()
    duplicate_before = sum(max(len(items) - 1, 0) for items in known_by_key.values())
    duplicate_after = _duplicate_count(_parse_blocks([rendered], str(output_language)))
    telemetry: dict[str, object] = {
        "input_fragment_count": len(markdown_sections),
        "output_section_count": len([block for block in ordered_blocks if block.heading]),
        "duplicate_section_count_before": duplicate_before,
        "duplicate_section_count_after": duplicate_after,
        "merged_section_keys": sorted(key for key, items in known_by_key.items() if len(items) > 1),
        "unknown_core_section_count": len(unknown_core),
        "unknown_support_section_count": len(unknown_support),
        "competitors": list(competitors),
        "first_support_key": _first_support_key(_parse_blocks([rendered], str(output_language))),
    }
    return AssembledReport(markdown=rendered, telemetry=telemetry)


def _parse_blocks(markdown_sections: Sequence[str], output_language: str) -> list[MarkdownBlock]:
    blocks: list[MarkdownBlock] = []
    ordinal = 0
    for markdown in markdown_sections:
        text = markdown.strip()
        if not text:
            continue
        matches = list(H2_RE.finditer(text))
        if not matches:
            blocks.append(MarkdownBlock(heading=None, key=None, body=text, ordinal=ordinal))
            ordinal += 1
            continue
        first = matches[0]
        if first.start() > 0:
            intro = text[: first.start()].strip()
            if intro:
                blocks.append(MarkdownBlock(heading=None, key=None, body=intro, ordinal=ordinal))
                ordinal += 1
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            heading = match.group(1).strip()
            body = text[match.end() : end].strip()
            blocks.append(
                MarkdownBlock(
                    heading=heading,
                    key=heading_key_for(heading, output_language),
                    body=body,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    return blocks


def _merge_known_blocks(key: str, blocks: list[MarkdownBlock], output_language: str) -> list[MarkdownBlock]:
    if not blocks:
        return []
    heading = report_label(output_language, key)
    body_parts = [block.body.strip() for block in sorted(blocks, key=lambda item: item.ordinal) if block.body.strip()]
    return [MarkdownBlock(heading=heading, key=key, body="\n\n".join(body_parts).strip(), ordinal=blocks[0].ordinal)]


def _render_block(block: MarkdownBlock) -> str:
    if block.heading is None:
        return block.body.strip()
    if block.body.strip():
        return f"## {block.heading}\n{block.body.strip()}".strip()
    return f"## {block.heading}".strip()


def _looks_like_support(heading: str) -> bool:
    normalized = heading.strip().lower()
    support_needles = ("evidence", "source", "qa", "appendix", "risk", "collection", "rag", "memory", "证据", "来源", "附录", "风险")
    return any(needle in normalized for needle in support_needles)


def _first_support_key(blocks: list[MarkdownBlock]) -> str | None:
    for block in blocks:
        if block.key in SUPPORT_HEADING_KEYS:
            return block.key
    return None


def _duplicate_count(blocks: list[MarkdownBlock]) -> int:
    counts: dict[str, int] = {}
    for block in blocks:
        if block.key:
            counts[block.key] = counts.get(block.key, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)
```

- [ ] **Step 4: Run assembler tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_report_assembler.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add backend/packages/agents/writer/assembler.py backend/tests/unit/test_writer_report_assembler.py
git commit -m "feat: assemble segmented writer reports"
```

Expected: commit succeeds.

## Task 4: Wire Assembler Into Segmented Writer

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing segmented assembly regression**

Add this test to `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_segmented_writer_assembles_duplicate_sections_before_return(monkeypatch):
    service = _segmented_writer_service()
    record = _segmented_writer_record(service, competitors=["Cursor"])
    pack = _SegmentedWriterFakePack(
        [
            {
                "segment_name": "decision_summary",
                "segment_kind": "section_fragment",
                "section_id": "decision_summary",
                "output_language": "en-US",
                "segment_batch": "sources:1",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-a"],
                "groups": [],
                "sources": [],
            },
            {
                "segment_name": "decision_summary",
                "segment_kind": "section_fragment",
                "section_id": "decision_summary",
                "output_language": "en-US",
                "segment_batch": "sources:2",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-b"],
                "groups": [],
                "sources": [],
            },
            {
                "segment_name": "support_appendix",
                "segment_kind": "support_fragment",
                "section_id": "evidence_support",
                "output_language": "en-US",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-c"],
                "groups": [],
                "sources": [],
            },
            {
                "segment_name": "competitor_deep_dives",
                "segment_kind": "section_fragment",
                "section_id": "competitor_deep_dives",
                "segment_competitor": "Cursor",
                "output_language": "en-US",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-d"],
                "groups": [],
                "sources": [],
            },
        ]
    )

    async def fake_segment_writer(*args, **kwargs):
        segment = kwargs["segment"]
        if segment["segment_name"] == "decision_summary":
            return f"## Decision Summary\nDecision from {segment['segment_batch']} [source:{segment['allowed_source_ids'][0]}]."
        if segment["segment_name"] == "support_appendix":
            return "## Evidence and QA Support\nSupport [source:raw-source-c]."
        return "## Competitor Deep Dives\n### Cursor\nDeep dive [source:raw-source-d]."

    monkeypatch.setattr(service, "_writer_segment_markdown", fake_segment_writer)

    report = await service._writer_segmented_report_markdown(
        record,
        evidence_pack_result=pack,
        timeout_seconds=60,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
    )

    assert report.count("## Decision Summary") == 1
    assert report.index("## Competitor Deep Dives") < report.index("## Evidence and QA Support")
    assert "Decision from sources:1 [source:raw-source-a]." in report
    assert "Decision from sources:2 [source:raw-source-b]." in report
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_run_service.py::test_segmented_writer_assembles_duplicate_sections_before_return -q
```

Expected: fails because `_writer_segmented_report_markdown()` still returns raw joined sections.

- [ ] **Step 3: Call assembler from segmented writer**

Modify imports in `backend/packages/agents/writer/logic.py`:

```python
from packages.agents.writer.assembler import assemble_report_sections
```

Replace the final return in `_writer_segmented_report_markdown()`:

```python
assembled = assemble_report_sections(
    sections,
    output_language=detail.output_language,
    competitors=detail.plan.competitors,
)
await self.emit(
    detail.id,
    "writer_assembly_completed",
    "writer",
    None,
    "Writer segmented report assembled",
    assembled.telemetry,
)
return assembled.markdown
```

- [ ] **Step 4: Add assembly telemetry assertions**

Extend `test_segmented_writer_assembles_duplicate_sections_before_return` before calling `_writer_segmented_report_markdown()`:

```python
events = []

async def capture_emit(*args):
    events.append(args)

monkeypatch.setattr(service, "emit", capture_emit)
```

After the report assertions, add:

```python
assembly_payloads = [event[5] for event in events if event[1] == "writer_assembly_completed"]
assert assembly_payloads
assert assembly_payloads[0]["duplicate_section_count_before"] == 1
assert assembly_payloads[0]["duplicate_section_count_after"] == 0
assert "decision_summary" in assembly_payloads[0]["merged_section_keys"]
```

- [ ] **Step 5: Run focused integration tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_report_assembler.py tests/unit/test_run_service.py::test_segmented_writer_assembles_duplicate_sections_before_return -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: wire writer report assembler"
```

Expected: commit succeeds.

## Task 5: Final Writer Quality Preflight

**Files:**
- Create: `backend/packages/agents/writer/quality_preflight.py`
- Create: `backend/tests/unit/test_writer_quality_preflight.py`
- Modify: `backend/packages/agents/writer/logic.py`

- [ ] **Step 1: Write failing preflight tests**

Create `backend/tests/unit/test_writer_quality_preflight.py`:

```python
from __future__ import annotations

from datetime import datetime

from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.i18n.language import report_label
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan


def _detail() -> RunDetail:
    return RunDetail(
        id="run-test",
        topic="AI coding tools",
        status="running",
        execution_mode="real",
        created_at=datetime(2026, 6, 17),
        updated_at=datetime(2026, 6, 17),
        output_language="en-US",
        plan=AnalysisPlan(
            topic="AI coding tools",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["feature", "pricing", "persona"],
        ),
        raw_sources=[],
    )


def test_quality_preflight_fails_duplicate_sections() -> None:
    detail = _detail()
    markdown = "\n\n".join(
        [
            "## Decision Summary\nA.",
            "## Decision Summary\nB.",
            "## Competitive Findings\nC.",
            "## User Review Themes\nD.",
            "## Competitor Deep Dives\n### Cursor\nE.\n### GitHub Copilot\nF.",
            "## Side-by-Side Decision Matrix\nG.",
            "## SWOT Analysis\nH.",
            "## Evidence and QA Support\nI.",
        ]
    )

    result = run_writer_quality_preflight(detail, markdown)

    assert result.passed is False
    assert result.duplicate_section_count == 1
    assert "duplicate_sections" in result.failure_reasons


def test_quality_preflight_fails_core_after_support() -> None:
    detail = _detail()
    support = report_label("en-US", "evidence_support")
    deep = report_label("en-US", "competitor_deep_dives")
    markdown = f"## {support}\nSupport.\n\n## {deep}\n### Cursor\nLate."

    result = run_writer_quality_preflight(detail, markdown)

    assert result.passed is False
    assert "core_sections_after_support" in result.failure_reasons
    assert "competitor_deep_dives" in result.core_sections_after_support


def test_quality_preflight_passes_ordered_core_report() -> None:
    detail = _detail()
    markdown = "\n\n".join(
        [
            "## Decision Summary\nA.",
            "## Competitive Findings\nB.",
            "## User Review Themes\nC.",
            "## Competitor Deep Dives\n### Cursor\nD.\n### GitHub Copilot\nE.",
            "## Side-by-Side Decision Matrix\nF.",
            "## SWOT Analysis\nG.",
            "## Evidence and QA Support\nH.",
        ]
    )

    result = run_writer_quality_preflight(detail, markdown)

    assert result.passed is True
    assert result.failure_reasons == []
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_quality_preflight.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'packages.agents.writer.quality_preflight'`.

- [ ] **Step 3: Implement `quality_preflight.py`**

Create `backend/packages/agents/writer/quality_preflight.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field

from packages.agents.writer.assembler import CANONICAL_REPORT_ORDER
from packages.agents.writer.segment_contract import SUPPORT_HEADING_KEYS, heading_key_for
from packages.schema.api_dto import RunDetail

H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
REQUIRED_CORE_KEYS = (
    "decision_summary",
    "competitive_findings",
    "review_theme_summary",
    "competitor_deep_dives",
    "side_by_side_matrix",
    "swot_analysis",
)


@dataclass(frozen=True)
class WriterQualityPreflightResult:
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)
    duplicate_section_count: int = 0
    missing_core_sections: list[str] = field(default_factory=list)
    core_sections_after_support: list[str] = field(default_factory=list)
    first_support_key: str | None = None
    h2_keys: list[str] = field(default_factory=list)

    def telemetry_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failure_reasons": self.failure_reasons,
            "duplicate_section_count": self.duplicate_section_count,
            "missing_core_sections": self.missing_core_sections,
            "core_sections_after_support": self.core_sections_after_support,
            "first_support_key": self.first_support_key,
            "h2_keys": self.h2_keys,
        }


def run_writer_quality_preflight(detail: RunDetail, markdown: str) -> WriterQualityPreflightResult:
    output_language = str(detail.output_language)
    h2_keys = [
        key
        for key in (heading_key_for(heading, output_language) for heading in _h2_headings(markdown))
        if key
    ]
    duplicate_count = _duplicate_count(h2_keys)
    first_support_index = _first_support_index(h2_keys)
    first_support_key = h2_keys[first_support_index] if first_support_index is not None else None
    before_support_keys = h2_keys if first_support_index is None else h2_keys[:first_support_index]
    after_support_keys = [] if first_support_index is None else h2_keys[first_support_index + 1 :]

    missing_core = [key for key in REQUIRED_CORE_KEYS if key not in before_support_keys]
    core_after_support = [
        key
        for key in after_support_keys
        if key in REQUIRED_CORE_KEYS or (key in CANONICAL_REPORT_ORDER and key not in SUPPORT_HEADING_KEYS)
    ]

    reasons: list[str] = []
    if duplicate_count:
        reasons.append("duplicate_sections")
    if missing_core:
        reasons.append("missing_core_sections")
    if core_after_support:
        reasons.append("core_sections_after_support")

    return WriterQualityPreflightResult(
        passed=not reasons,
        failure_reasons=reasons,
        duplicate_section_count=duplicate_count,
        missing_core_sections=missing_core,
        core_sections_after_support=core_after_support,
        first_support_key=first_support_key,
        h2_keys=h2_keys,
    )


def _h2_headings(markdown: str) -> list[str]:
    return [match.group(1).strip() for match in H2_RE.finditer(markdown)]


def _duplicate_count(keys: list[str]) -> int:
    counts: dict[str, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _first_support_index(keys: list[str]) -> int | None:
    for index, key in enumerate(keys):
        if key in SUPPORT_HEADING_KEYS:
            return index
    return None
```

- [ ] **Step 4: Wire preflight after assembly**

Modify `backend/packages/agents/writer/logic.py` imports:

```python
from packages.agents.writer.quality_preflight import run_writer_quality_preflight
```

After `assemble_report_sections(...)` and before returning from `_writer_segmented_report_markdown()`, add:

```python
preflight = run_writer_quality_preflight(detail, assembled.markdown)
await self.emit(
    detail.id,
    "writer_quality_preflight",
    "writer",
    None,
    "Writer quality preflight completed",
    preflight.telemetry_payload(),
)
if not preflight.passed:
    repaired = assemble_report_sections(
        [assembled.markdown],
        output_language=detail.output_language,
        competitors=detail.plan.competitors,
    )
    repaired_preflight = run_writer_quality_preflight(detail, repaired.markdown)
    await self.emit(
        detail.id,
        "writer_quality_preflight_repair",
        "writer",
        None,
        "Writer quality preflight deterministic repair completed",
        repaired_preflight.telemetry_payload(),
    )
    if not repaired_preflight.passed:
        raise RuntimeError(
            "Writer assembled report failed quality preflight: "
            f"{', '.join(repaired_preflight.failure_reasons)}"
        )
    return repaired.markdown
return assembled.markdown
```

- [ ] **Step 5: Run preflight and segmented writer focused tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_quality_preflight.py tests/unit/test_run_service.py::test_segmented_writer_assembles_duplicate_sections_before_return -q
```

Expected: selected tests pass.

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add backend/packages/agents/writer/quality_preflight.py backend/packages/agents/writer/logic.py backend/tests/unit/test_writer_quality_preflight.py backend/tests/unit/test_run_service.py
git commit -m "feat: preflight assembled writer reports"
```

Expected: commit succeeds.

## Task 6: Redo Routing Through Assembler

**Files:**
- Modify: `backend/packages/agents/writer/repair.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing repair-router tests**

Add tests near writer repair tests:

Add this import near the existing imports:

```python
from packages.agents.writer.repair import build_writer_repair_plan
```

```python
def test_release_gate_duplicate_sections_routes_to_assemble():
    detail = _segmented_writer_detail(
        report_md="\n\n".join(
            [
                "## Decision Summary\nA.",
                "## Decision Summary\nB.",
                "## Competitive Findings\nC.",
                "## User Review Themes\nD.",
                "## Competitor Deep Dives\n### Cursor\nE.",
                "## Side-by-Side Decision Matrix\nF.",
                "## SWOT Analysis\nG.",
                "## Evidence and QA Support\nH.",
            ]
        ),
    )
    issues = [_qc_issue("release_gate.report_depth_required", "duplicate section count is nonzero")]

    plan = build_writer_repair_plan(detail, issues)

    assert plan.mode == "assemble"
    assert plan.reason == "release gate failure is deterministic report structure damage"
    assert plan.anti_regression_required is False


def test_release_gate_thin_core_without_structure_damage_routes_to_full():
    detail = _segmented_writer_detail(
        report_md="## Decision Summary\nThin.\n\n## Evidence and QA Support\nSupport."
    )
    issues = [_qc_issue("release_gate.report_depth_required", "core report sections are too thin")]

    plan = build_writer_repair_plan(detail, issues)

    assert plan.mode == "full"
```

- [ ] **Step 2: Run router tests and confirm they fail**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_run_service.py::test_release_gate_duplicate_sections_routes_to_assemble tests/unit/test_run_service.py::test_release_gate_thin_core_without_structure_damage_routes_to_full -q
```

Expected: first test fails because `WriterRepairMode` does not include `assemble`.

- [ ] **Step 3: Add `assemble` repair mode**

Modify `backend/packages/agents/writer/repair.py`:

```python
WriterRepairMode = Literal["line", "section", "assemble", "full"]
```

Add helper:

```python
def _has_deterministic_report_structure_damage(detail: RunDetail) -> bool:
    report = (detail.report_md or "").strip()
    if not report:
        return False
    quality = compare_run_quality(detail, report)
    metrics = quality.get("metrics", {}) if isinstance(quality, dict) else {}
    duplicate_count = int(metrics.get("duplicate_section_count") or 0)
    core_depth = float(metrics.get("core_section_depth_score") or 0.0)
    core_analysis_depth = float(metrics.get("core_analysis_depth_score") or 0.0)
    return duplicate_count > 0 or (core_depth == 0.0 and core_analysis_depth >= 0.6)
```

Change the `release_gate.report_depth_required` branch:

```python
if _has_release_gate_report_depth_issue(issues):
    if _has_deterministic_report_structure_damage(detail):
        return WriterRepairPlan(
            mode="assemble",
            reason="release gate failure is deterministic report structure damage",
            previous_report_protectable=True,
            anti_regression_required=False,
        )
    return WriterRepairPlan(
        mode="full",
        reason="release_gate.report_depth_required requires full core rewrite",
        previous_report_protectable=True,
        anti_regression_required=True,
    )
```

- [ ] **Step 4: Handle `assemble` in writer logic**

In `backend/packages/agents/writer/logic.py`, near the existing `line` and `section` repair branches, add:

```python
elif repair_plan is not None and repair_plan.mode == "assemble":
    assembled = assemble_report_sections(
        [previous_report_md],
        output_language=detail.output_language,
        competitors=detail.plan.competitors,
    )
    preflight = run_writer_quality_preflight(detail, assembled.markdown)
    await self.emit(
        detail.id,
        "writer_assemble_repair_completed",
        "writer",
        None,
        "Writer assembler repair completed",
        {
            **assembled.telemetry,
            "quality_preflight": preflight.telemetry_payload(),
        },
    )
    if preflight.passed:
        report_md = assembled.markdown
        writer_repair_mode = "assemble"
    else:
        repair_plan = WriterRepairPlan(
            mode="full",
            reason="assembler repair did not pass writer quality preflight",
            previous_report_protectable=True,
            anti_regression_required=True,
        )
```

Keep the existing full-rewrite branch available when assembler repair cannot fix the report.

- [ ] **Step 5: Run repair-router tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_run_service.py::test_release_gate_duplicate_sections_routes_to_assemble tests/unit/test_run_service.py::test_release_gate_thin_core_without_structure_damage_routes_to_full -q
```

Expected: selected tests pass.

- [ ] **Step 6: Commit Task 6**

Run:

```powershell
git add backend/packages/agents/writer/repair.py backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "fix: route structural writer redo through assembler"
```

Expected: commit succeeds.

## Task 7: Segment Telemetry

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add telemetry assertion test**

Extend the existing segmented writer test or add:

```python
@pytest.mark.asyncio
async def test_writer_segment_preflight_emits_contract_metadata(monkeypatch):
    service = _segmented_writer_service()
    record = _segmented_writer_record(service, competitors=["Cursor"])
    events = []

    async def capture_emit(*args):
        events.append(args)

    monkeypatch.setattr(service, "emit", capture_emit)
    pack = _SegmentedWriterFakePack(
        [
            {
                "segment_name": "decision_summary",
                "segment_kind": "section_fragment",
                "section_id": "decision_summary",
                "output_language": "en-US",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-a"],
                "groups": [],
                "sources": [],
            }
        ]
    )

    async def fake_segment_writer(*args, **kwargs):
        return "## Decision Summary\nDecision [source:raw-source-a]."

    monkeypatch.setattr(service, "_writer_segment_markdown", fake_segment_writer)

    await service._writer_segmented_report_markdown(
        record,
        evidence_pack_result=pack,
        timeout_seconds=60,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
    )

    preflight_payloads = [event[5] for event in events if event[1] == "writer_segment_preflight"]
    assert preflight_payloads
    assert preflight_payloads[0]["segment_kind"] == "section_fragment"
    assert preflight_payloads[0]["section_id"] == "decision_summary"
    assert "decision_summary" in preflight_payloads[0]["allowed_heading_keys"]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_run_service.py::test_writer_segment_preflight_emits_contract_metadata -q
```

Expected: fails because preflight payload lacks contract metadata.

- [ ] **Step 3: Add contract metadata to `writer_segment_preflight`**

In `_writer_segmented_report_markdown()`, build `contract = segment_contract_for(segment)` before `payload = {...}` and add:

```python
"segment_kind": contract.segment_kind,
"section_id": contract.section_id,
"allowed_heading_keys": list(contract.allowed_heading_keys),
"forbidden_heading_keys": list(contract.forbidden_heading_keys),
"segment_essential": contract.essential,
```

Reuse this `contract` for validation after citation validation.

- [ ] **Step 4: Run telemetry test**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_run_service.py::test_writer_segment_preflight_emits_contract_metadata -q
```

Expected: selected test passes.

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: trace writer segment contracts"
```

Expected: commit succeeds.

## Task 8: Evidence Shards for Budget-Split Inputs

**Files:**
- Modify: `backend/packages/agents/writer/evidence_pack.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing evidence-pack metadata tests**

Add tests to `backend/tests/unit/test_writer_evidence_pack.py`:

```python
def test_budget_split_decision_summary_segments_are_evidence_shards(monkeypatch):
    import packages.agents.writer.evidence_pack as evidence_pack_module

    monkeypatch.setattr(evidence_pack_module, "SEGMENT_INPUT_TARGET_CHARS", 1000)
    sources = [
        RawSource(
            id=f"cursor-pricing-{index}",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title=f"Cursor pricing {index}",
            url=f"https://example.com/cursor-pricing-{index}",
            snippet=(
                "Cursor pricing evidence for budget segmentation. "
                "This source should be represented and preserved for writer shards. "
                * 8
            ),
            content_hash=f"cursor-pricing-{index}",
            confidence=0.9,
        )
        for index in range(12)
    ]
    detail = _detail_with_sources(sources)
    result = build_writer_evidence_pack(detail)

    decision_segments = [
        segment
        for segment in result.segment_inputs()
        if segment["segment_name"] == "decision_summary"
    ]

    assert len(decision_segments) > 1
    assert all(segment["segment_kind"] == "evidence_shard" for segment in decision_segments)
    assert all(segment["section_id"] == "decision_summary" for segment in decision_segments)
    assert all(segment["segment_essential"] is True for segment in decision_segments)


def test_unsplit_user_research_segment_remains_section_fragment():
    sources = [
        RawSource(
            id=f"cursor-persona-{index}",
            competitor="Cursor",
            dimension="persona",
            source_type="interview_record",
            title=f"Cursor persona {index}",
            snippet="Interviewed buyers cite onboarding, security review, and procurement effort.",
            content_hash=f"cursor-persona-{index}",
            confidence=0.82,
        )
        for index in range(3)
    ]
    detail = _detail_with_sources(sources)
    result = build_writer_evidence_pack(detail)

    user_segments = [
        segment
        for segment in result.segment_inputs()
        if segment["segment_name"] == "user_research"
    ]

    assert len(user_segments) == 1
    assert user_segments[0]["segment_kind"] == "section_fragment"
    assert user_segments[0]["section_id"] == "review_theme_summary"
```

- [ ] **Step 2: Run tests and confirm they fail**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_evidence_pack.py::test_budget_split_decision_summary_segments_are_evidence_shards tests/unit/test_writer_evidence_pack.py::test_unsplit_user_research_segment_remains_section_fragment -q
```

Expected: first test fails because split decision-summary segments still use `section_fragment`.

- [ ] **Step 3: Mark source/fact budget splits as `evidence_shard`**

In `backend/packages/agents/writer/evidence_pack.py`, adjust split helpers so segments created only because input exceeds `SEGMENT_INPUT_TARGET_CHARS` carry:

```python
"segment_kind": "evidence_shard",
"section_id": base_section_id,
"segment_essential": True,
"shard_output_format": "structured_notes",
```

Keep unsplit logical section segments as:

```python
"segment_kind": "section_fragment",
"section_id": base_section_id,
"segment_essential": True,
```

Keep support segments as:

```python
"segment_kind": "support_fragment",
"section_id": "evidence_support",
"segment_essential": False,
```

- [ ] **Step 4: Add evidence-shard writer behavior test**

Add this test to `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_evidence_shard_outputs_notes_then_section_writer_outputs_one_h2(monkeypatch):
    service = _segmented_writer_service()
    record = _segmented_writer_record(service, competitors=["Cursor"])
    pack = _SegmentedWriterFakePack(
        [
            {
                "segment_name": "decision_summary",
                "segment_kind": "evidence_shard",
                "section_id": "decision_summary",
                "output_language": "en-US",
                "segment_batch": "sources:1",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-a"],
                "groups": [],
                "sources": [],
            },
            {
                "segment_name": "decision_summary",
                "segment_kind": "evidence_shard",
                "section_id": "decision_summary",
                "output_language": "en-US",
                "segment_batch": "sources:2",
                "segment_input_chars": 2000,
                "allowed_source_ids": ["raw-source-b"],
                "groups": [],
                "sources": [],
            },
        ]
    )
    calls = []

    async def fake_segment_writer(*args, **kwargs):
        segment = kwargs["segment"]
        calls.append(segment["segment_kind"])
        if segment["segment_kind"] == "evidence_shard":
            return f"- shard note {segment['segment_batch']} [source:{segment['allowed_source_ids'][0]}]"
        return "## Decision Summary\nMerged shard note [source:raw-source-a][source:raw-source-b]."

    monkeypatch.setattr(service, "_writer_segment_markdown", fake_segment_writer)

    report = await service._writer_segmented_report_markdown(
        record,
        evidence_pack_result=pack,
        timeout_seconds=60,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
    )

    assert calls == ["evidence_shard", "evidence_shard", "section_fragment"]
    assert report.count("## Decision Summary") == 1
    assert "Merged shard note" in report
```

- [ ] **Step 5: Implement shard-to-section writer pass**

In `_writer_segmented_report_markdown()`:

1. Collect `evidence_shard` outputs into `shards_by_section: dict[str, list[str]]`.
2. Do not append evidence shard outputs directly to `sections`.
3. After all shard segments run, synthesize one section segment per `section_id`.

Use this synthesized segment shape:

```python
section_segment = {
    "segment_name": section_id,
    "segment_kind": "section_fragment",
    "section_id": section_id,
    "output_language": detail.output_language,
    "segment_input_chars": sum(len(note) for note in shard_notes),
    "allowed_source_ids": sorted(section_allowed_source_ids[section_id]),
    "groups": [],
    "sources": [],
    "shard_notes": shard_notes,
    "segment_batch": "from_evidence_shards",
}
```

Call `_writer_segment_markdown()` once with this synthesized segment and validate it with the same citation and contract path as normal segments.

- [ ] **Step 6: Tighten evidence-shard prompt**

In `_writer_segment_markdown()`, when `segment.get("segment_kind") == "evidence_shard"`, add:

```python
"This is an evidence shard. Return compact structured notes as bullets. "
"Do not write any ## H2 heading. Do not write a final report section. "
"Preserve exact source IDs for facts that should be cited by the section writer.\n"
```

When `segment` includes `shard_notes`, add:

```python
"This section writer receives evidence shard notes in segment.shard_notes. "
"Write exactly one canonical report section or allowed section group from those notes.\n"
```

- [ ] **Step 7: Run evidence shard tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_evidence_pack.py::test_budget_split_decision_summary_segments_are_evidence_shards tests/unit/test_writer_evidence_pack.py::test_unsplit_user_research_segment_remains_section_fragment tests/unit/test_run_service.py::test_evidence_shard_outputs_notes_then_section_writer_outputs_one_h2 -q
```

Expected: selected tests pass.

- [ ] **Step 8: Commit Task 8**

Run:

```powershell
git add backend/packages/agents/writer/evidence_pack.py backend/packages/agents/writer/logic.py backend/tests/unit/test_writer_evidence_pack.py backend/tests/unit/test_run_service.py
git commit -m "feat: split writer evidence shards from sections"
```

Expected: commit succeeds.

## Task 9: Prompt and Release Gate Regression Sweep

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`

- [ ] **Step 1: Add prompt-regression assertions**

Add assertions to existing prompt-capture tests in `backend/tests/unit/test_run_service.py`:

```python
assert "segment_kind=" in captured_user_prompt
assert "section_id=" in captured_user_prompt
assert "Do not write headings outside this segment's contract" in captured_user_prompt
assert "Do not combine multiple source IDs inside one [source:...] token" in captured_system_prompt
```

- [ ] **Step 2: Run prompt tests**

Run prompt-related tests selected by pytest expression:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_run_service.py -k "writer and prompt" -q
```

Expected: prompt tests pass after updating expected strings.

- [ ] **Step 3: Add no-generated-artifact git check**

Before each commit after this task, run:

```powershell
git status --short
```

Expected: only intended tracked source/test/docs files appear as staged or modified. The following paths remain untracked and unstaged unless the user explicitly asks to commit them:

```text
STATE.md
competiscope-db-kb-package-20260610-171820(1).zip
competiscope-db-kb-package-20260610-171820/
data/artifacts/
docs/PROJECT_OVERVIEW_FOR_REVIEWERS.md
outputs/
```

- [ ] **Step 4: Commit Task 9 if prompt code changed**

Run:

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py backend/tests/unit/test_writer_evidence_pack.py
git commit -m "test: cover segmented writer prompt contracts"
```

Expected: commit succeeds when prompt/test files changed. When this task only confirms existing prompt text, record that no commit was created for Task 9.

## Task 10: Verification

**Files:**
- Verify all files touched by Tasks 1-9.

- [ ] **Step 1: Run new focused tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_segment_contract.py tests/unit/test_writer_report_assembler.py tests/unit/test_writer_quality_preflight.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run writer evidence-pack tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_writer_evidence_pack.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run run-service tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_run_service.py -q
```

Expected: all tests pass. If unrelated pre-existing failures appear, record exact failing test names and confirm the segmented-writer tests pass.

- [ ] **Step 4: Run source reconciliation regression tests**

Run:

```powershell
conda run -n bd-competiscope-v2 pytest tests/unit/test_source_reconciliation.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Check formatting-sensitive diff issues**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 6: Inspect final staged scope before final commit**

Run:

```powershell
git status --short
```

Expected: only source/test/docs changes from this plan are staged or modified. Generated artifacts remain untracked.

- [ ] **Step 7: Make final checkpoint commit if verification changed files**

Run:

```powershell
git add backend/packages/agents/writer backend/tests/unit/test_writer_segment_contract.py backend/tests/unit/test_writer_report_assembler.py backend/tests/unit/test_writer_quality_preflight.py backend/tests/unit/test_writer_evidence_pack.py backend/tests/unit/test_run_service.py
git commit -m "test: verify segmented writer report assembly"
```

Expected: commit succeeds when verification produced required source/test changes. When all changes were already committed in earlier tasks, record that no verification commit was created.

## Execution Notes

- Use conda env `bd-competiscope-v2` for Python tests.
- Do not stage untracked generated artifacts, DB packages, output reports, or `STATE.md` during this plan unless the user explicitly asks.
- Keep commits small and phase-labeled.
- If deterministic assembler repair cannot pass `run_writer_quality_preflight()`, fall back to the existing full rewrite path and emit the exact preflight failure reasons.
