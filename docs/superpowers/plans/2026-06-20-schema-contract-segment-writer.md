# Schema Contract Segment Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make real reports use natural segmented authoring under schema/publication contracts instead of the current 13-section JSON writer main path.

**Architecture:** Keep the existing evidence pack, segment writer, fail-closed real-run behavior, publication contract, and quality accounting. Add keyed segment metadata and keyed assembly, then route `writer_structured_report_enabled=True` real runs through schema-contract segmented Markdown generation plus publication validation. Keep the structured JSON writer available for diagnostics and existing focused tests, but do not use it as the default real-run authoring path.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, existing conda environment `D:\Anaconda\envs\bd-competiscope-v2\python.exe`, backend writer modules under `backend/packages/agents/writer`.

---

## Scope And Guardrails

This plan implements:

- `docs/superpowers/specs/2026-06-20-schema-contract-segment-writer-design.md`

It intentionally supersedes the older plan:

- `docs/superpowers/plans/2026-06-20-schema-first-writer-main-path-hardening.md`

Do not keep pushing the 13-section JSON writer as the real-run main path. Keep the structured JSON files and tests where useful, but route new real reports through the schema-contract segment writer.

Do not commit generated reports, run databases, output artifacts, zip files, Word docs, or local exports. The worktree already contains unrelated untracked artifacts; ignore them and stage only the exact files named in each task.

Use PowerShell commands from repository root:

```powershell
cd D:\codex_workspace\plan_a
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest ...
```

## File Structure

Modify these files:

- `backend/packages/agents/writer/assembler.py`
  - Add keyed report fragments and an assembler entry point that consumes segment metadata before falling back to heading recognition.

- `backend/packages/agents/writer/evidence_pack.py`
  - Add `section_key` and `layer` to segment payloads.

- `backend/packages/agents/writer/logic.py`
  - Add the schema-contract segment writer main path.
  - Route real runs with `writer_structured_report_enabled=True` to natural segments.
  - Run publication contract on the assembled Markdown.
  - Keep structured JSON writer available but no longer default for real authoring.

- `backend/packages/agents/writer/publication_contract.py`
  - Allow output-language-driven validation when there is no `StructuredReport` object.

- `backend/packages/agents/writer/segment_contract.py`
  - Keep existing validation but expose enough contract metadata for keyed assembly telemetry.

- `backend/packages/agents/writer/structured_repair.py`
  - Reuse existing Markdown recommendation extraction for segment recommendation delta checks.

Modify or add tests:

- `backend/tests/unit/test_writer_report_assembler.py`
- `backend/tests/unit/test_writer_evidence_pack.py`
- `backend/tests/unit/test_writer_publication_contract.py`
- `backend/tests/unit/test_run_service.py`

No frontend or database migration is part of this plan.

---

### Task 1: Add Keyed Report Fragment Assembly

**Files:**
- Modify: `backend/packages/agents/writer/assembler.py`
- Test: `backend/tests/unit/test_writer_report_assembler.py`

- [ ] **Step 1: Write failing assembler tests**

Append these tests to `backend/tests/unit/test_writer_report_assembler.py`:

```python
from packages.agents.writer.assembler import (
    ReportSectionFragment,
    assemble_report_fragments,
)


def test_keyed_assembler_uses_fragment_layer_for_unknown_sections() -> None:
    fragments = [
        ReportSectionFragment(
            markdown="## Custom Core Readout\nCore finding. [source:raw-source-a]",
            section_key="decision_summary",
            layer="core",
            segment_name="decision_summary",
        ),
        ReportSectionFragment(
            markdown="## Mystery Audit Notes\nSupport note. [source:raw-source-b]",
            section_key="evidence_support",
            layer="support",
            segment_name="support_appendix",
        ),
    ]

    assembled = assemble_report_fragments(
        fragments,
        output_language="en-US",
        competitors=["Cursor"],
    )

    assert assembled.markdown.index("## Custom Core Readout") < assembled.markdown.index(
        "## Mystery Audit Notes"
    )
    assert assembled.telemetry["unknown_core_section_count"] == 1
    assert assembled.telemetry["unknown_support_section_count"] == 1
    assert assembled.telemetry["fragment_layer_counts"] == {"core": 1, "support": 1}


def test_keyed_assembler_keeps_known_support_after_core_even_when_input_is_first() -> None:
    fragments = [
        ReportSectionFragment(
            markdown="## Evidence & QA Support\nSupport first. [source:raw-source-b]",
            section_key="evidence_support",
            layer="support",
            segment_name="support_appendix",
        ),
        ReportSectionFragment(
            markdown="## Decision Summary\nDecision second. [source:raw-source-a]",
            section_key="decision_summary",
            layer="core",
            segment_name="decision_summary",
        ),
    ]

    assembled = assemble_report_fragments(
        fragments,
        output_language="en-US",
        competitors=["Cursor"],
    )

    assert assembled.markdown.index("## Decision Summary") < assembled.markdown.index(
        "## Evidence & QA Support"
    )
    assert assembled.telemetry["input_fragment_count"] == 2
    assert assembled.telemetry["first_support_key"] == "evidence_support"
```

- [ ] **Step 2: Run the failing assembler tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_report_assembler.py::test_keyed_assembler_uses_fragment_layer_for_unknown_sections backend/tests/unit/test_writer_report_assembler.py::test_keyed_assembler_keeps_known_support_after_core_even_when_input_is_first -q
```

Expected: FAIL because `ReportSectionFragment` and `assemble_report_fragments` do not exist.

- [ ] **Step 3: Implement keyed fragment assembly**

In `backend/packages/agents/writer/assembler.py`, add this dataclass near `AssembledReport`:

```python
@dataclass(frozen=True)
class ReportSectionFragment:
    markdown: str
    section_key: str
    layer: str
    segment_name: str
    competitor: str | None = None
```

Add this function above `assemble_report_sections()`:

```python
def assemble_report_fragments(
    fragments: Sequence[ReportSectionFragment],
    *,
    output_language: object,
    competitors: Sequence[str],
) -> AssembledReport:
    markdown_sections = [fragment.markdown for fragment in fragments]
    assembled = _assemble_report_blocks(
        [
            (fragment.markdown, fragment.section_key, fragment.layer)
            for fragment in fragments
        ],
        output_language=output_language,
        competitors=competitors,
    )
    layer_counts: dict[str, int] = {}
    for fragment in fragments:
        layer_counts[fragment.layer] = layer_counts.get(fragment.layer, 0) + 1
    telemetry = {
        **assembled.telemetry,
        "input_fragment_count": len(markdown_sections),
        "fragment_layer_counts": layer_counts,
        "fragment_section_keys": [fragment.section_key for fragment in fragments],
        "fragment_segment_names": [fragment.segment_name for fragment in fragments],
    }
    return AssembledReport(markdown=assembled.markdown, telemetry=telemetry)
```

Refactor `assemble_report_sections()` so it delegates to a private helper:

```python
def assemble_report_sections(
    markdown_sections: Sequence[str],
    *,
    output_language: object,
    competitors: Sequence[str],
) -> AssembledReport:
    return _assemble_report_blocks(
        [(markdown, "", "") for markdown in markdown_sections],
        output_language=output_language,
        competitors=competitors,
    )
```

Implement `_assemble_report_blocks()` by moving the current body of `assemble_report_sections()` into it and changing the input loop to:

```python
def _assemble_report_blocks(
    fragment_inputs: Sequence[tuple[str, str, str]],
    *,
    output_language: object,
    competitors: Sequence[str],
) -> AssembledReport:
    intro_blocks: list[str] = []
    known_sections: dict[str, list[str]] = {}
    known_counts: dict[str, int] = {}
    unknown_core_sections: list[_SectionBlock] = []
    unknown_support_sections: list[_SectionBlock] = []

    output_language_text = str(output_language)
    for markdown, fragment_section_key, fragment_layer in fragment_inputs:
        intro, sections = _parse_fragment(markdown, output_language_text)
        if intro:
            intro_blocks.append(intro)
        for section in sections:
            if section.key is not None:
                known_sections.setdefault(section.key, []).append(section.body)
                known_counts[section.key] = known_counts.get(section.key, 0) + 1
            elif fragment_layer == "support" or _looks_like_support_heading(section.heading):
                unknown_support_sections.append(section)
            else:
                unknown_core_sections.append(section)
```

Keep the existing output ordering and telemetry logic inside `_assemble_report_blocks()`.

- [ ] **Step 4: Run assembler tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_report_assembler.py -q
```

Expected: all assembler tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/assembler.py backend/tests/unit/test_writer_report_assembler.py
git commit -m "feat: assemble report fragments by segment keys"
```

---

### Task 2: Add Section Key And Layer To Segment Inputs

**Files:**
- Modify: `backend/packages/agents/writer/evidence_pack.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_writer_evidence_pack.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing evidence-pack metadata test**

Append this test to `backend/tests/unit/test_writer_evidence_pack.py`:

```python
def test_segment_inputs_include_section_key_and_layer_metadata() -> None:
    sources = [
        RawSource(
            id="cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            snippet="Cursor pricing evidence.",
            content_hash="cursor-pricing-hash",
            confidence=0.96,
        )
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))
    segments_by_name = {
        str(segment["segment_name"]): segment for segment in result.segment_inputs()
    }

    assert segments_by_name["decision_summary"]["section_key"] == "decision_summary"
    assert segments_by_name["decision_summary"]["layer"] == "core"
    assert segments_by_name["user_research"]["section_key"] == "review_theme_summary"
    assert segments_by_name["user_research"]["layer"] == "core"
    assert segments_by_name["swot_matrix"]["section_key"] == "swot_matrix"
    assert segments_by_name["swot_matrix"]["layer"] == "core"
    assert segments_by_name["support_appendix"]["section_key"] == "evidence_support"
    assert segments_by_name["support_appendix"]["layer"] == "support"
```

- [ ] **Step 2: Write failing shard synthesis metadata test**

Append this test near existing segmented writer shard tests in `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_writer_section_segment_from_shards_preserves_keyed_metadata() -> None:
    service = _segmented_writer_service()
    record = _segmented_writer_record(service, competitors=["Cursor"])

    segment = service._writer_section_segment_from_shards(
        record.detail,
        section_id="competitor_deep_dives",
        segment_competitor="Cursor",
        shard_notes=["- Cursor shard note [source:raw-source-a]"],
        allowed_source_ids={"raw-source-a"},
    )

    assert segment["section_key"] == "competitor_deep_dives"
    assert segment["layer"] == "core"
    assert segment["segment_competitor"] == "Cursor"
```

- [ ] **Step 3: Run the failing metadata tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_evidence_pack.py::test_segment_inputs_include_section_key_and_layer_metadata backend/tests/unit/test_run_service.py::test_writer_section_segment_from_shards_preserves_keyed_metadata -q
```

Expected: FAIL because `section_key` and `layer` are missing.

- [ ] **Step 4: Implement segment metadata**

In `backend/packages/agents/writer/evidence_pack.py`, update `_segment_contract_metadata()`:

```python
def _segment_contract_metadata(
    segment_name: str,
    output_language: str,
) -> dict[str, object]:
    section_id_by_name = {
        "decision_summary": "decision_summary",
        "user_research": "review_theme_summary",
        "competitor_deep_dives": "competitor_deep_dives",
        "swot_matrix": "swot_matrix",
        "support_appendix": "evidence_support",
    }
    section_id = section_id_by_name.get(segment_name, segment_name)
    is_support = segment_name == "support_appendix" or section_id == "evidence_support"
    return {
        "segment_kind": "support_fragment" if is_support else "section_fragment",
        "section_id": section_id,
        "section_key": section_id,
        "layer": "support" if is_support else "core",
        "output_language": output_language,
        "segment_essential": not is_support,
    }
```

In `backend/packages/agents/writer/logic.py`, update `_writer_section_segment_from_shards()` so `section_segment` includes:

```python
"section_key": section_id,
"layer": "support" if section_id == "evidence_support" else "core",
```

- [ ] **Step 5: Run metadata tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_evidence_pack.py::test_segment_inputs_include_section_key_and_layer_metadata backend/tests/unit/test_run_service.py::test_writer_section_segment_from_shards_preserves_keyed_metadata -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/packages/agents/writer/evidence_pack.py backend/packages/agents/writer/logic.py backend/tests/unit/test_writer_evidence_pack.py backend/tests/unit/test_run_service.py
git commit -m "feat: add keyed metadata to writer segments"
```

---

### Task 3: Use Keyed Fragments In The Segmented Writer

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing keyed assembly telemetry test**

Add this assertion block to `test_segmented_writer_assembles_duplicate_sections_before_return` after the existing assembly payload assertions:

```python
    assert payload["fragment_layer_counts"] == {"core": 6, "support": 1}
    assert payload["fragment_section_keys"] == [
        "decision_summary",
        "decision_summary",
        "competitive_findings",
        "review_theme_summary",
        "competitor_deep_dives",
        "swot_matrix",
        "evidence_support",
    ]
```

- [ ] **Step 2: Run the failing keyed assembly test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_segmented_writer_assembles_duplicate_sections_before_return -q
```

Expected: FAIL because `_writer_segmented_report_markdown()` still passes plain strings to `assemble_report_sections()`.

- [ ] **Step 3: Return keyed fragments from segment generation**

In `backend/packages/agents/writer/logic.py`, import:

```python
from packages.agents.writer.assembler import (
    ReportSectionFragment,
    assemble_report_fragments,
    assemble_report_sections,
)
```

Change `_writer_segment_markdown_parts()` to build `ReportSectionFragment` objects instead of plain strings:

```python
sections: list[ReportSectionFragment] = []
```

When a non-shard segment is validated, append:

```python
sections.append(
    ReportSectionFragment(
        markdown=segment_md,
        section_key=str(segment.get("section_key") or contract.section_id),
        layer=str(segment.get("layer") or ("support" if contract.segment_kind == "support_fragment" else "core")),
        segment_name=str(segment.get("segment_name") or contract.segment_name),
        competitor=(
            str(segment.get("segment_competitor"))
            if segment.get("segment_competitor") is not None
            else None
        ),
    )
)
```

When a synthesized section from shards is validated, append a fragment with the synthesized segment metadata:

```python
sections.append(
    ReportSectionFragment(
        markdown=section_md,
        section_key=str(section_segment.get("section_key") or contract.section_id),
        layer=str(section_segment.get("layer") or "core"),
        segment_name=str(section_segment.get("segment_name") or contract.segment_name),
        competitor=segment_competitor,
    )
)
```

Update the return annotation:

```python
) -> list[ReportSectionFragment]:
```

In `_writer_segmented_report_markdown()`, replace:

```python
assembled = assemble_report_sections(
    sections,
    output_language=detail.output_language,
    competitors=detail.plan.competitors,
)
```

with:

```python
assembled = assemble_report_fragments(
    sections,
    output_language=detail.output_language,
    competitors=detail.plan.competitors,
)
```

Leave `_writer_section_repair_markdown()` using `assemble_report_sections()` until Task 6, because it joins already-rendered repair parts.

- [ ] **Step 4: Run keyed assembly test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_segmented_writer_assembles_duplicate_sections_before_return -q
```

Expected: test passes.

- [ ] **Step 5: Run segmented writer focused tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py -k "segmented_writer or writer_segment" -q
```

Expected: selected segmented writer tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: assemble segmented writer output from keyed fragments"
```

---

### Task 4: Let Publication Contract Validate Markdown Without StructuredReport

**Files:**
- Modify: `backend/packages/agents/writer/publication_contract.py`
- Test: `backend/tests/unit/test_writer_publication_contract.py`

- [ ] **Step 1: Write failing output-language publication test**

Append this test to `backend/tests/unit/test_writer_publication_contract.py`:

```python
def test_publication_contract_rejects_english_structural_heading_from_output_language() -> None:
    markdown = (
        "## 执行摘要\n"
        "建议选择 Cursor。 [source:raw-source-a]\n\n"
        "### Direct User / Community Signals\n"
        "用户信号不能使用英文结构标题。 [source:raw-source-a]\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=None,
        allowed_source_ids={"raw-source-a"},
        output_language="zh-CN",
    )

    assert not result.passed
    assert "english_structural_heading_in_zh" in result.issue_codes()
```

- [ ] **Step 2: Run the failing publication test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_publication_contract.py::test_publication_contract_rejects_english_structural_heading_from_output_language -q
```

Expected: FAIL because `validate_publication_contract()` does not accept `output_language`.

- [ ] **Step 3: Add output language support**

Update the function signature in `backend/packages/agents/writer/publication_contract.py`:

```python
def validate_publication_contract(
    markdown: str,
    *,
    structured_report: StructuredReport | None,
    allowed_source_ids: set[str],
    output_language: str | None = None,
) -> PublicationContractResult:
```

Change the `is_zh` assignment:

```python
is_zh = _is_zh_report(structured_report, output_language=output_language)
```

Update `_is_zh_report()`:

```python
def _is_zh_report(
    report: StructuredReport | None,
    *,
    output_language: str | None = None,
) -> bool:
    if report is not None:
        return report.output_language.lower().startswith("zh")
    return (output_language or "").lower().startswith("zh")
```

Existing callers do not need changes because `output_language` is optional.

- [ ] **Step 4: Run publication tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_publication_contract.py -q
```

Expected: all publication contract tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/publication_contract.py backend/tests/unit/test_writer_publication_contract.py
git commit -m "feat: validate publication contract by output language"
```

---

### Task 5: Switch Real Schema-First Runs To Schema-Contract Segments

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Replace structured-main-path test with segment-main-path test**

In `backend/tests/unit/test_run_service.py`, replace `test_real_writer_uses_structured_path_when_enabled` with:

```python
def test_real_schema_contract_writer_uses_segmented_authoring_when_enabled(
    monkeypatch,
) -> None:
    service = _segmented_writer_service()
    service._settings = replace(
        service._settings,
        writer_structured_report_enabled=True,
        writer_timeout_seconds=10,
    )
    record = _segmented_writer_record(service, competitors=["Cursor", "Windsurf"])
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()
    _attach_structured_writer_redo(record)

    async def fail_if_structured_json_writer_called(self, record, evidence_pack_result, timeout_seconds):
        raise AssertionError("13-section structured JSON writer must not be the real-run main path")

    async def fake_segmented_report(self, record, *, evidence_pack_result, timeout_seconds, language_guidance, memory_context, layer_context, required_sections):
        return (
            "## 执行摘要\n"
            "- 建议: Cursor 和 GitHub Copilot 双轨评估。 [source:raw-source-a]\n\n"
            "## 决策摘要\n"
            "核心判断来自自然 segment writer。 [source:raw-source-a]\n\n"
            "## 竞争发现\n"
            "Cursor 和 Windsurf 的证据边界不同。 [source:raw-source-b]\n\n"
            "## 用户评价整理\n"
            "用户信号需要区分社区和模拟访谈。 [source:raw-source-c]\n\n"
            "## 竞品深挖\n"
            "### Cursor\n"
            "Cursor 的采用信号更适合 IDE 内工作流。 [source:raw-source-a]\n\n"
            "### Windsurf\n"
            "Windsurf 的卖点需要继续验证。 [source:raw-source-b]\n\n"
            "## 横向决策矩阵\n"
            "| 维度 | Cursor | Windsurf |\n"
            "| --- | --- | --- |\n"
            "| pricing | 可验证 | 待验证 |\n\n"
            "## SWOT 分析\n"
            "Cursor strengths include workflow fit. [source:raw-source-a]\n\n"
            "## 战报\n"
            "- Cursor 攻击点: 强调成熟 IDE workflow。 [source:raw-source-a]\n\n"
            "## 证据与 QA 支撑\n"
            "支撑材料位于正文之后。 [source:raw-source-a]\n"
        )

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_structured_report",
        fail_if_structured_json_writer_called,
    )
    monkeypatch.setattr(service, "_writer_segmented_report_markdown", fake_segmented_report)

    asyncio.run(service._real_writer_step(record))

    event_types = [event.type for event in record.events]
    assert "writer_markdown_fallback_used" not in event_types
    assert "writer_structured_report_validated" not in event_types
    assert "writer_publication_contract_validated" in event_types
    assert "自然 segment writer" in record.detail.report_md
```

- [ ] **Step 2: Add a compatibility test for diagnostic structured JSON method**

Append this test near structured writer generation tests in `backend/tests/unit/test_run_service.py`:

```python
def test_structured_json_writer_method_remains_available_for_diagnostics(monkeypatch) -> None:
    service = _segmented_writer_service()
    service._settings = replace(
        service._settings,
        writer_structured_report_enabled=True,
        writer_timeout_seconds=10,
    )
    record = _segmented_writer_record(service, competitors=["Cursor"])
    record.detail.raw_sources = _structured_writer_raw_sources()

    assert hasattr(service, "_writer_structured_report")
```

- [ ] **Step 3: Run the failing main-path test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_real_schema_contract_writer_uses_segmented_authoring_when_enabled backend/tests/unit/test_run_service.py::test_structured_json_writer_method_remains_available_for_diagnostics -q
```

Expected: first test fails because `_real_writer_step()` still calls `_writer_structured_report()` when the flag is enabled.

- [ ] **Step 4: Implement schema-contract segmented report method**

In `backend/packages/agents/writer/logic.py`, add this method near `_writer_markdown_report_from_evidence_pack()`:

```python
    async def _writer_schema_contract_segment_report(
        self,
        record: RunRecord,
        evidence_pack_result,
        timeout_seconds: float,
    ) -> str:
        detail = record.detail
        layer_context = self._writer_layer_context(detail)
        memory_context = "\n".join(detail.plan.memory_prompt_context) or "none"
        required_sections = self._writer_required_sections(detail)
        language_guidance = language_instruction(detail.output_language)
        return await self._writer_segmented_report_markdown(
            record,
            evidence_pack_result=evidence_pack_result,
            timeout_seconds=timeout_seconds,
            language_guidance=language_guidance,
            memory_context=memory_context,
            layer_context=layer_context,
            required_sections=required_sections,
        )
```

In `_real_writer_step()`, replace the structured-enabled default path:

```python
structured_report = await self._writer_structured_report(...)
...
report_md = rendered
writer_mode = "real structured writer call"
```

with:

```python
report_md = await self._writer_schema_contract_segment_report(
    record,
    evidence_pack_result,
    timeout_seconds,
)
publication_validation = validate_publication_contract(
    report_md,
    structured_report=None,
    allowed_source_ids={source.id for source in detail.raw_sources},
    output_language=detail.output_language,
)
publication_payload = publication_validation.telemetry_payload()
await self.emit(
    detail.id,
    "writer_publication_contract_validated",
    "writer",
    None,
    "Writer publication contract validated.",
    publication_payload,
)
self._trace_local_tool(
    record,
    agent="writer",
    subagent=None,
    name="writer_publication_contract_validated",
    input_text="schema_contract_segment_report",
    output_text=json.dumps(publication_payload, ensure_ascii=False, default=str),
    metadata={
        "passed": publication_validation.passed,
        "issue_count": len(publication_validation.issues),
    },
)
if not publication_validation.passed:
    raise ValueError(
        "schema-contract segment publication contract failed: "
        + ", ".join(publication_validation.issue_codes())
    )
writer_mode = "real schema-contract segment writer call"
```

Keep the existing `except Exception as exc:` fail-closed block. Keep `_writer_structured_report()` in the file.

- [ ] **Step 5: Update structured repair selected event behavior**

Inside the new segment path, emit `writer_structured_repair_selected` only when `structured_targets` exists and the report passes publication validation:

```python
if structured_targets:
    await self.emit(
        detail.id,
        "writer_structured_repair_selected",
        "writer",
        None,
        "Structured repair targets selected for schema-contract segment report.",
        {
            "targets": list(dict.fromkeys(structured_targets)),
            "llm_required": any(target != "renderer" for target in structured_targets),
            "authoring_mode": "schema_contract_segment",
        },
    )
```

Do not emit `writer_structured_report_validated` on this path, because no `StructuredReport` object was generated.

- [ ] **Step 6: Run main-path tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_real_schema_contract_writer_uses_segmented_authoring_when_enabled backend/tests/unit/test_run_service.py::test_real_schema_first_success_does_not_emit_markdown_fallback backend/tests/unit/test_run_service.py::test_real_schema_first_writer_fails_closed_when_structured_path_fails backend/tests/unit/test_run_service.py::test_markdown_writer_still_runs_when_structured_flag_disabled -q
```

If `test_real_schema_first_success_does_not_emit_markdown_fallback` still expects `writer_structured_report_validated`, change it to assert `writer_publication_contract_validated` and no fallback event.

Expected: selected tests pass after updating expectations to schema-contract segment authoring.

- [ ] **Step 7: Commit**

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: use schema-contract segment writer for real reports"
```

---

### Task 6: Fail Closed On Publication Contract Failures

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing fail-closed publication test**

Append this test to `backend/tests/unit/test_run_service.py`:

```python
def test_real_schema_contract_writer_fails_closed_on_publication_contract_error(
    monkeypatch,
) -> None:
    service = _segmented_writer_service()
    service._settings = replace(
        service._settings,
        writer_structured_report_enabled=True,
        writer_timeout_seconds=10,
    )
    record = _segmented_writer_record(service, competitors=["Cursor"])
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()

    async def fake_segmented_report(self, record, *, evidence_pack_result, timeout_seconds, language_guidance, memory_context, layer_context, required_sections):
        return (
            "<!-- report-section:key=executive_summary layer=core --> [source:raw-source-a]\n"
            "## 执行摘要\n"
            "建议选择 Cursor。 [source:raw-source-a]\n\n"
            "### Direct User / Community Signals\n"
            "英文结构标题应被 publication contract 拦截。 [source:raw-source-a]\n"
        )

    monkeypatch.setattr(service, "_writer_segmented_report_markdown", fake_segmented_report)

    asyncio.run(service._real_writer_step(record))

    event_types = [event.type for event in record.events]
    assert record.detail.status == "failed"
    assert record.detail.report_md == ""
    assert "writer_schema_first_failed_closed" in event_types
    assert "writer_markdown_fallback_used" not in event_types
```

- [ ] **Step 2: Run the failing publication fail-closed test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_real_schema_contract_writer_fails_closed_on_publication_contract_error -q
```

Expected: FAIL if publication contract failures do not route through fail-closed behavior.

- [ ] **Step 3: Ensure publication errors use the existing fail-closed block**

In `_real_writer_step()`, make sure the `ValueError` raised for `schema-contract segment publication contract failed` occurs inside the same `try` block that catches structured-enabled real-run failures and emits `writer_schema_first_failed_closed`.

Do not call `_writer_markdown_report_from_evidence_pack()` after this failure when `_schema_first_real_run(detail, structured_enabled)` is true.

- [ ] **Step 4: Run fail-closed tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_real_schema_contract_writer_fails_closed_on_publication_contract_error backend/tests/unit/test_run_service.py::test_real_schema_first_writer_fails_closed_when_structured_path_fails backend/tests/unit/test_run_service.py::test_markdown_writer_still_runs_when_structured_flag_disabled -q
```

Expected: selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "fix: fail closed on schema-contract publication errors"
```

---

### Task 7: Preserve Scoped Recommendation On Segment Redo

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing segment recommendation delta test**

Append this test to `backend/tests/unit/test_run_service.py`:

```python
def test_schema_contract_segment_scoped_redo_preserves_unjustified_recommendation_drift(
    monkeypatch,
) -> None:
    service = _segmented_writer_service()
    service._settings = replace(
        service._settings,
        writer_structured_report_enabled=True,
        writer_timeout_seconds=10,
    )
    record = _segmented_writer_record(
        service,
        run_id="run-schema-contract-recommendation-guard",
        competitors=["Cursor", "Windsurf"],
    )
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()
    record.detail.report_md = (
        "## 执行摘要\n"
        "- 建议: Cursor + GitHub Copilot 双轨采购。 [source:raw-source-a]\n\n"
        "## 决策摘要\n"
        "上一版建议保持双轨。 [source:raw-source-a]\n"
    )
    _attach_scoped_structured_writer_redo(
        record,
        target_competitor="Claude Code",
        target_subagent="persona",
    )

    async def fake_segmented_report(self, record, *, evidence_pack_result, timeout_seconds, language_guidance, memory_context, layer_context, required_sections):
        return (
            "## 执行摘要\n"
            "- 建议: Windsurf 作为主采购选择。 [source:raw-source-b]\n\n"
            "## 决策摘要\n"
            "这次只补了 Claude Code persona，未提供 Windsurf 新证据。 [source:raw-source-b]\n\n"
            "## 竞争发现\n"
            "没有新的 Windsurf 采购证据。 [source:raw-source-b]\n"
        )

    monkeypatch.setattr(service, "_writer_segmented_report_markdown", fake_segmented_report)

    asyncio.run(service._real_writer_step(record))

    assert "Cursor + GitHub Copilot 双轨采购" in record.detail.report_md
    assert "Windsurf 作为主采购选择" not in record.detail.report_md
    guard_events = [
        event for event in record.events if event.type == "writer_recommendation_delta_checked"
    ]
    assert guard_events
    assert guard_events[-1].payload["accepted"] is False
```

- [ ] **Step 2: Run the failing recommendation guard test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_schema_contract_segment_scoped_redo_preserves_unjustified_recommendation_drift -q
```

Expected: FAIL because the schema-contract segment path does not yet check Markdown recommendation drift.

- [ ] **Step 3: Implement Markdown recommendation delta guard**

In `backend/packages/agents/writer/logic.py`, after the segment report passes publication contract but before it is hardened into `detail.report_md`, add:

```python
pending = record.pending_graph_redo
previous_recommendation = previous_recommendation_posture(
    previous_structured_report=getattr(record, "structured_report_snapshot", None),
    previous_report=previous_report,
)
candidate_recommendation = previous_recommendation_posture(
    previous_structured_report=None,
    previous_report=report_md,
)
scoped_competitors: set[str] = set()
scoped_dimensions: set[str] = set()
if pending is not None:
    for scope in pending.redo_scopes:
        if scope.target_competitor:
            scoped_competitors.add(scope.target_competitor)
        scoped_competitors.update(scope.target_competitors)
        if scope.target_subagent:
            scoped_dimensions.add(scope.target_subagent)
recommendation_problem = (
    recommendation_delta_problem(
        previous_recommendation=previous_recommendation,
        candidate_recommendation=candidate_recommendation,
        scoped_competitors=scoped_competitors,
        scoped_dimensions=scoped_dimensions,
        candidate_rationale=report_md,
    )
    if pending is not None and previous_recommendation and candidate_recommendation
    else None
)
if pending is not None and previous_recommendation and candidate_recommendation:
    await self.emit(
        detail.id,
        "writer_recommendation_delta_checked",
        "writer",
        None,
        "Schema-contract segment recommendation delta checked.",
        {
            "previous_recommendation": previous_recommendation,
            "candidate_recommendation": candidate_recommendation,
            "scoped_competitors": sorted(scoped_competitors),
            "scoped_dimensions": sorted(scoped_dimensions),
            "accepted": recommendation_problem is None,
            "reason": recommendation_problem,
        },
    )
if recommendation_problem:
    anti_regression_reason = recommendation_problem
    detail.report_md = self._preserve_hardened_previous_report(detail, previous_report)
    report_md = detail.report_md
    writer_mode = "preserved previous report after recommendation delta guard"
    structured_recommendation_guard_preserved = True
```

Use the existing imports:

```python
previous_recommendation_posture
recommendation_delta_problem
```

Do not add a new recommendation parser.

- [ ] **Step 4: Run recommendation guard tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_schema_contract_segment_scoped_redo_preserves_unjustified_recommendation_drift backend/tests/unit/test_run_service.py::test_real_schema_first_scoped_redo_uses_markdown_previous_recommendation_without_snapshot -q
```

Expected: selected tests pass. If the old structured-specific test expects a `StructuredReport` snapshot change, update only that expectation to accept the segment-mode preservation event.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "fix: guard schema-contract segment recommendation drift"
```

---

### Task 8: Keep Legacy Flag-Disabled Markdown Path Working

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/packages/agents/writer/logic.py` only if the test fails.

- [ ] **Step 1: Strengthen legacy fallback test**

Update `test_markdown_writer_still_runs_when_structured_flag_disabled` so it also asserts publication-contract segment events are absent:

```python
    event_types = [event.type for event in record.events]
    assert "writer_publication_contract_validated" not in event_types
    assert "writer_markdown_fallback_used" not in event_types
```

This test proves that the feature-flag-disabled path remains the legacy Markdown path, not the schema-contract segment path.

- [ ] **Step 2: Run legacy path test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_markdown_writer_still_runs_when_structured_flag_disabled -q
```

Expected: pass. If it fails because schema-contract publication validation runs when the flag is disabled, move the new segment path under `if structured_enabled:`.

- [ ] **Step 3: Commit if a code or test change was made**

If only the test changed:

```powershell
git add backend/tests/unit/test_run_service.py
git commit -m "test: preserve flag-disabled markdown writer path"
```

If code also changed:

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "fix: preserve flag-disabled markdown writer path"
```

---

### Task 9: Focused Regression Suite

**Files:**
- Modify source only if a feature-owned focused test fails.

- [ ] **Step 1: Run writer assembler, contract, evidence, and publication tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_report_assembler.py backend/tests/unit/test_writer_evidence_pack.py backend/tests/unit/test_writer_segment_contract.py backend/tests/unit/test_writer_publication_contract.py -q
```

Expected: all listed tests pass.

- [ ] **Step 2: Run focused run-service writer tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py -k "schema_contract or schema_first or segmented_writer or writer_segment or markdown_writer_still_runs" -q
```

Expected: selected tests pass. If old tests explicitly assert that the 13-section JSON writer is the default real-run path, update those tests to assert the new schema-contract segment path.

- [ ] **Step 3: Run existing structured tests to protect diagnostic code**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_structured_repair.py -q
```

Expected: structured diagnostic tests still pass. If a test assumes structured JSON is the real-run default, move that assertion to a direct `_writer_structured_report()` unit test.

- [ ] **Step 4: Commit feature-owned fixes from regression suite**

If tests required more source changes, inspect exact files:

```powershell
git status --short
```

Stage only feature-owned files. Example when `logic.py` and tests changed:

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "fix: stabilize schema-contract segment writer tests"
```

If no files changed, do not create an empty commit.

---

### Task 10: Restart Services And Run One Real Report

**Files:**
- Do not edit source files unless the real run reveals a feature-owned failure.
- Do not commit run DBs, logs, outputs, or generated reports.

- [ ] **Step 1: Find existing service scripts**

Run:

```powershell
rg -n "uvicorn|vite|pnpm|npm|conda|backend|frontend|5173|8000|start|stop|restart" README.md Makefile docker-compose.yml scripts docs -S
```

Use the repo's existing stop/start scripts if they are present. Do not invent a new startup path when scripts already exist.

- [ ] **Step 2: Stop current project services**

If a repo stop script exists, run it. If no script exists, list relevant processes:

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'plan_a|uvicorn|vite|pnpm|npm'
} | Select-Object ProcessId,Name,CommandLine
```

Stop only processes clearly serving `D:\codex_workspace\plan_a`.

- [ ] **Step 3: Start backend with conda environment**

Use the discovered script. If no script exists, use this fallback:

```powershell
Start-Process -WindowStyle Hidden -FilePath "D:\Anaconda\envs\bd-competiscope-v2\python.exe" -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory "D:\codex_workspace\plan_a\backend"
```

- [ ] **Step 4: Start frontend**

Use the discovered script. If no script exists and the repo uses pnpm, use this fallback:

```powershell
Start-Process -WindowStyle Hidden -FilePath "pnpm" -ArgumentList "dev", "--host", "127.0.0.1" -WorkingDirectory "D:\codex_workspace\plan_a\frontend"
```

- [ ] **Step 5: Confirm local health**

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-WebRequest http://127.0.0.1:5173 -UseBasicParsing | Select-Object StatusCode
```

Expected: backend health returns an OK payload, frontend returns HTTP 200.

- [ ] **Step 6: Start one real report run**

Use the current API shape. If unchanged, run:

```powershell
$created = Invoke-RestMethod -Method Post -ContentType "application/json" -Uri "http://127.0.0.1:8000/api/runs" -Body (@{
  topic = "AI Coding Agent"
  competitors = @("Claude Code", "Cursor", "GitHub Copilot", "Windsurf")
  dimensions = @("pricing", "feature", "persona")
  execution_mode = "real"
  output_language = "zh-CN"
} | ConvertTo-Json -Depth 6)
$runId = $created.id
$runId
```

- [ ] **Step 7: Wait for terminal status**

Run:

```powershell
while ($true) {
  $run = Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId"
  "{0} {1}" -f (Get-Date), $run.status
  if ($run.status -in @("completed", "completed_with_blockers", "failed")) { break }
  Start-Sleep -Seconds 20
}
```

- [ ] **Step 8: Audit the real run**

Inspect run detail, events, spans, warnings, and final report. Verify all of these:

- No `writer_structured_report_validated` event appears for the real main authoring path.
- No `writer_markdown_fallback_used` event appears.
- `writer_segment_preflight`, `writer_segment_validated`, `writer_assembly_completed`, and `writer_publication_contract_validated` appear.
- Publication contract passed or failed closed without fallback.
- Report body has no citation on section marker lines.
- Report body has no citation in headings.
- Report body has no citation in table headers.
- Chinese report has localized structural headings.
- No internal terms such as `source_registry`, `allowed_source_ids`, `Segment Evidence Pack`, `Writer Evidence Pack`, `fact:`, or `signal:` appear.
- Executive summary contains a real business recommendation, not a system description.
- Battlecard has competitor-specific attack, defense, objection, rebuttal, use-when, and proof-needed content.
- Support appendix appears after core analysis and reads like reader-facing audit material, not raw logs.

- [ ] **Step 9: Fix only feature-owned real-run failures**

If the run reveals a feature-owned failure, write a focused failing unit test for that exact shape, fix it, run focused tests, commit, restart services, and run a new real report.

Do not mark this plan complete until a real run has been audited after restart.

---

## Final Completion Checklist

Before claiming completion, verify with fresh evidence:

- [ ] Spec is committed: `docs/superpowers/specs/2026-06-20-schema-contract-segment-writer-design.md`
- [ ] This plan is committed: `docs/superpowers/plans/2026-06-20-schema-contract-segment-writer.md`
- [ ] Real runs with `writer_structured_report_enabled=True` use schema-contract segmented authoring.
- [ ] The 13-section JSON writer is not the default real-run authoring path.
- [ ] Legacy/flag-disabled Markdown path still works.
- [ ] Segment inputs include `section_key` and `layer`.
- [ ] Assembler consumes keyed fragments and keeps core before support.
- [ ] Publication contract validates zh-CN reports without requiring `StructuredReport`.
- [ ] Publication contract failures fail closed for real schema-contract runs.
- [ ] Scoped redo cannot accept unjustified recommendation drift.
- [ ] Focused writer/run-service tests pass in the conda environment.
- [ ] Backend and frontend were restarted from the current branch.
- [ ] One new real run was executed and audited.
- [ ] No generated artifacts, DB packages, logs, zips, Word docs, or report outputs were committed.
