# Report Section Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared report section index so report quality gates and QA blockers classify core vs support/audit report content consistently.

**Architecture:** Introduce a focused `report_sections.py` helper that parses Markdown headings once and exposes line/section lookup helpers. Wire the existing RAG, SWOT, and community official-commitment checks through that helper without changing writer, collector, comparator, or release-gate policy.

**Tech Stack:** Python 3.11, pytest, existing `packages.business_intel` and `packages.agents.qa` modules.

---

### Task 1: Add Section Index Tests

**Files:**
- Create: `backend/tests/unit/test_report_sections.py`
- Modify: none

- [ ] **Step 1: Write the failing test**

```python
from packages.business_intel.report_sections import build_report_section_index


def test_section_index_classifies_support_and_audit_lines() -> None:
    markdown = """# AI Coding Agent Report

## Executive Summary
Official Cursor pricing is not asserted from community sources. [source:official]

## RAG 缺口补全
| 缺口 | 建议检索/取证 | 当前状态 |
| --- | --- | --- |
| pricing | 官方 pricing page | 社区来源可能过时 [source:reddit-pricing] |

## Final QA Gate Status
- blocker repeated line: official commitment line cites reddit-pricing.
"""

    index = build_report_section_index(markdown)

    core_line = 4
    rag_line = 8
    final_qa_line = 11

    assert index.is_support_or_audit_line(core_line) is False
    assert index.is_support_or_audit_line(rag_line) is True
    assert index.is_support_or_audit_line(final_qa_line) is True
    assert [section.heading for section in index.sections_before_support()] == [
        "AI Coding Agent Report",
        "Executive Summary",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_sections.py::test_section_index_classifies_support_and_audit_lines -q
```

Expected: FAIL because `packages.business_intel.report_sections` does not exist.

- [ ] **Step 3: Implement the section index**

Create `backend/packages/business_intel/report_sections.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from packages.i18n.language import repair_mojibake_text

SectionLayer = Literal["core", "support", "audit"]


@dataclass(frozen=True)
class ReportSection:
    heading: str
    normalized_heading: str
    level: int
    start: int
    end: int
    line_start: int
    line_end: int
    body: str
    layer: SectionLayer


@dataclass(frozen=True)
class ReportSectionIndex:
    markdown: str
    sections: tuple[ReportSection, ...]

    def sections_before_support(self) -> tuple[ReportSection, ...]:
        first_support = next(
            (section for section in self.sections if section.layer in {"support", "audit"}),
            None,
        )
        if first_support is None:
            return self.sections
        return tuple(section for section in self.sections if section.start < first_support.start)

    def section_for_line(self, line_number: int) -> ReportSection | None:
        return next(
            (
                section
                for section in self.sections
                if section.line_start <= line_number <= section.line_end
            ),
            None,
        )

    def is_support_or_audit_line(self, line_number: int) -> bool:
        section = self.section_for_line(line_number)
        return section is not None and section.layer in {"support", "audit"}


def build_report_section_index(markdown: str) -> ReportSectionIndex:
    report_md = repair_mojibake_text(markdown or "")
    matches = list(
        re.finditer(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", report_md, flags=re.MULTILINE)
    )
    sections: list[ReportSection] = []
    sticky_support = False
    for index, match in enumerate(matches):
        heading = clean_heading(match.group(2))
        normalized = normalize_heading(heading)
        level = len(match.group(1))
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(report_md)
        layer = classify_section_layer(normalized, sticky_support=sticky_support)
        if is_support_layer_heading(normalized):
            sticky_support = True
            layer = "audit"
        sections.append(
            ReportSection(
                heading=heading,
                normalized_heading=normalized,
                level=level,
                start=match.start(),
                end=body_end,
                line_start=report_md.count("\n", 0, match.start()) + 1,
                line_end=report_md.count("\n", 0, body_end) + 1,
                body=report_md[body_start:body_end].strip(),
                layer=layer,
            )
        )
    return ReportSectionIndex(markdown=report_md, sections=tuple(sections))
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_sections.py::test_section_index_classifies_support_and_audit_lines -q
```

Expected: PASS.

### Task 2: Wire RAG/SWOT Quality Scoring

**Files:**
- Modify: `backend/packages/business_intel/report_quality.py`
- Modify: `backend/tests/unit/test_report_quality.py`

- [ ] **Step 1: Write failing quality tests**

Add tests that:

- require `rag_gap_fill_section_score == 1.0` for a normal Chinese `RAG 缺口补全` table with `建议检索/取证`.
- require `swot_section_score == 1.0` for `**Strengths (优势):**`, `**Weaknesses (劣势):**`, `**Opportunities (机会):**`, and `**Threats (威胁):**`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_quality.py::test_compare_run_quality_accepts_normal_chinese_rag_gap_fill_table backend/tests/unit/test_report_quality.py::test_report_quality_accepts_bilingual_swot_quadrant_labels -q
```

Expected: FAIL because the existing scorer misses the normal Chinese RAG phrases and bilingual SWOT labels.

- [ ] **Step 3: Implement minimal scorer changes**

Use `build_report_section_index()` in the existing support-section helpers or in the specific RAG scorer. Add SWOT label candidate normalization so parenthetical bilingual labels can map to either language. Keep existing English and mojibake compatibility.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_quality.py::test_compare_run_quality_accepts_normal_chinese_rag_gap_fill_table backend/tests/unit/test_report_quality.py::test_report_quality_accepts_bilingual_swot_quadrant_labels -q
```

Expected: PASS.

### Task 3: Wire QA False-Positive Guard

**Files:**
- Modify: `backend/packages/agents/qa/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing QA tests**

Add a test where:

- a core line `Official Cursor pricing is $20... [source:reddit-pricing]` still blocks;
- support/audit lines under `RAG 缺口补全` and `Final QA Gate Status` repeat `official commitment` and `reddit-pricing` but do not block.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_qa_ignores_community_official_commitment_repeats_in_support_audit_sections -q
```

Expected: FAIL because `_build_community_official_commitment_issues()` currently scans every line.

- [ ] **Step 3: Implement minimal QA change**

Build a report section index once inside `_build_community_official_commitment_issues()` and skip lines where `index.is_support_or_audit_line(line_number)` returns true. Leave all existing official/community evidence checks unchanged for core prose.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_qa_blocks_community_observation_written_as_official_commitment backend/tests/unit/test_run_service.py::test_qa_ignores_community_official_commitment_repeats_in_support_audit_sections -q
```

Expected: PASS.

### Task 4: Regression Verification

**Files:**
- No new production files unless earlier tasks require refactor.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_sections.py backend/tests/unit/test_report_quality.py backend/tests/unit/test_run_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Re-score run-dd8 if local journal data is available**

Run a small script or existing test utility to call `compare_run_quality()` for `run-dd8dfa79692330f1ec8626d32192aa87`.

Expected: `rag_gap_fill_section_score == 1.0`; no new blocker should be introduced.

- [ ] **Step 3: Review git diff**

Run:

```bash
git diff -- backend/packages/business_intel/report_sections.py backend/packages/business_intel/report_quality.py backend/packages/agents/qa/logic.py backend/tests/unit/test_report_sections.py backend/tests/unit/test_report_quality.py backend/tests/unit/test_run_service.py
```

Expected: diff only contains the section-index repair and tests.

## Plan Self-Review

- Spec coverage: all three target failures map to Tasks 1-3; Task 4 covers regression.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: the plan uses `build_report_section_index`, `ReportSectionIndex`, and `is_support_or_audit_line` consistently.
