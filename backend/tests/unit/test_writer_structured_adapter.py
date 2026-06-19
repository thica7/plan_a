from __future__ import annotations

from packages.agents.writer.structured_adapter import (
    MarkdownFailureShape,
    detect_markdown_failure_shapes,
)


def test_detects_known_legacy_markdown_failure_shapes() -> None:
    markdown = """
## 执行摘要

- **核心结论：** This report is structured as decision analysis first, with evidence and QA support after the core competitive readout. [source:raw-source-a]

## 用户评价整理

### Direct User / Community Signals

- Cursor users mention speed. [source:raw-source-a]

## 战报

- 直接战报定位
- 反对意见处理
- 行动偏向
- 落地检查

## 决策矩阵

| 维度 [source:raw-source-a] | Cursor |
|---|---|
| pricing | visible [source:raw-source-a] |

## 支撑材料

Segment Evidence Pack JSON includes source_registry.
"""

    result = detect_markdown_failure_shapes(markdown, output_language="zh-CN")

    assert not result.passed
    assert result.issue_codes() == [
        "executive_summary_template_only",
        "english_structural_heading_in_zh",
        "battlecard_template_only",
        "citation_in_table_header",
        "internal_term_leak",
    ]
    assert result.issues[0] == MarkdownFailureShape(
        code="executive_summary_template_only",
        section="执行摘要",
        line_number=4,
    )


def test_accepts_clean_markdown_fixture() -> None:
    markdown = """
## 执行摘要

- **推荐：** 优先选择 Cursor 作为团队采购基线。 [source:raw-source-a]

## 战报

### Cursor

- **目标买家：** 工程负责人
- **使用场景：** 当买家重视低风险团队落地时使用。 [source:raw-source-a]

## 支撑材料

### 证据附录

| Source ID | Title | Competitor | Dimension | Role | Confidence |
|---|---|---|---|---|---|
| raw-source-a | Cursor pricing | Cursor | pricing | official_fact | high |
"""

    result = detect_markdown_failure_shapes(markdown, output_language="zh-CN")

    assert result.passed
    assert result.issues == []
    assert result.issue_codes() == []


def test_does_not_flag_body_table_citations_or_competitor_heading() -> None:
    markdown = """
## 战报

### Cursor

| 维度 | Cursor |
|---|---|
| pricing | visible [source:raw-source-a] |
"""

    result = detect_markdown_failure_shapes(markdown, output_language="zh-CN")

    assert result.passed


def test_detects_battlecard_template_only_after_three_template_terms() -> None:
    markdown = """
## 战报

- 直接战报定位
- 反对意见处理
- 行动偏向
"""

    result = detect_markdown_failure_shapes(markdown, output_language="zh-CN")

    assert result.issue_codes() == ["battlecard_template_only"]
    assert result.issues[0].line_number == 4
