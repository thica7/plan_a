from __future__ import annotations

from packages.agents.writer.publication_contract import validate_publication_contract
from packages.agents.writer.structured_renderer import render_structured_report
from test_writer_structured_renderer import _report


def test_rejects_english_structural_heading_in_zh_report() -> None:
    markdown = "## 用户评价整理\n\n### Direct User / Community Signals\n\n正文。\n"

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids=set(),
    )

    assert not result.passed
    assert result.issue_codes() == ["english_structural_heading_in_zh"]
    assert result.issues[0].repair_target == "renderer"


def test_rejects_broader_renderer_style_english_headings_in_zh_report() -> None:
    markdown = (
        "### Next Actions\n\n"
        "正文。\n\n"
        "#### Adoption Blockers\n\n"
        "正文。\n\n"
        "#### Evidence Gaps\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids=set(),
    )

    matching_issues = [
        issue
        for issue in result.issues
        if issue.code == "english_structural_heading_in_zh"
    ]
    assert [issue.line_number for issue in matching_issues] == [1, 5, 9]
    assert {issue.repair_target for issue in matching_issues} == {"renderer"}


def test_rejects_appendix_and_audit_english_headings_in_zh_report() -> None:
    markdown = (
        "### Source Appendix\n\n"
        "正文。\n\n"
        "### Claim Support Audit\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids=set(),
    )

    matching_issues = [
        issue
        for issue in result.issues
        if issue.code == "english_structural_heading_in_zh"
    ]
    assert [issue.line_number for issue in matching_issues] == [1, 5]
    assert {issue.repair_target for issue in matching_issues} == {"renderer"}


def test_rejects_top_level_english_structural_headings_in_zh_report() -> None:
    markdown = (
        "## Executive Summary\n\n"
        "正文。\n\n"
        "## Decision Matrix\n\n"
        "正文。\n\n"
        "## Support Materials\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids=set(),
    )

    matching_issues = [
        issue
        for issue in result.issues
        if issue.code == "english_structural_heading_in_zh"
    ]
    assert [issue.line_number for issue in matching_issues] == [1, 5, 9]
    assert {issue.repair_target for issue in matching_issues} == {"renderer"}


def test_allows_standalone_english_competitor_heading_in_zh_report() -> None:
    markdown = "## 用户评价整理\n\n### Cursor\n\n正文 [source:raw-source-a]\n"

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids={"raw-source-a"},
    )

    assert result.passed
    assert result.issues == []


def test_rejects_citation_in_appendix_table_header() -> None:
    markdown = (
        "| 来源 ID [source:raw-source-a] | 标题 | 竞品 | 维度 | 角色 | 置信度 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| raw-source-a | Source title | Cursor | pricing | official_fact | high |\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids={"raw-source-a"},
    )

    assert result.issue_codes() == ["citation_in_table_header"]
    assert result.issues[0].repair_target == "renderer"


def test_rejects_citations_in_headings_and_table_headers() -> None:
    markdown = (
        "# Topic [source:raw-source-a]\n\n"
        "| 维度 [source:raw-source-a] | Cursor |\n"
        "| --- | --- |\n"
        "| pricing | 正文 [source:raw-source-a] |\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids={"raw-source-a"},
    )

    assert result.issue_codes() == [
        "citation_in_heading",
        "citation_in_table_header",
    ]
    assert {issue.repair_target for issue in result.issues} == {"renderer"}


def test_accepts_renderer_output_for_clean_zh_report() -> None:
    markdown = render_structured_report(_report("zh-CN"))

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids={"raw-source-a", "raw-source-b", "raw-source-survey"},
    )

    assert result.passed
    assert result.issues == []


def test_publication_contract_rejects_source_citation_on_section_marker_line() -> None:
    report = _report("zh-CN")
    markdown = (
        "<!-- report-section:key=executive_summary layer=core --> "
        "[source:raw-source-a]\n"
        "## 执行摘要\n"
        "- 建议: 选择 Cursor。[source:raw-source-a]\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=report,
        allowed_source_ids={"raw-source-a"},
    )

    assert not result.passed
    assert "citation_on_section_marker" in result.issue_codes()
    issue = next(
        item for item in result.issues if item.code == "citation_on_section_marker"
    )
    assert issue.line_number == 1
    assert issue.repair_target == "renderer"


def test_publication_contract_accepts_clean_section_marker_line() -> None:
    report = _report("zh-CN")
    markdown = (
        "<!-- report-section:key=executive_summary layer=core -->\n"
        "## 执行摘要\n"
        "- 建议: 选择 Cursor。[source:raw-source-a]\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=report,
        allowed_source_ids={"raw-source-a"},
    )

    assert "citation_on_section_marker" not in result.issue_codes()


def test_publication_contract_accepts_renderer_section_markers_without_citations() -> None:
    report = _report("zh-CN")
    markdown = render_structured_report(report)
    marker_lines = [
        line for line in markdown.splitlines() if line.startswith("<!-- report-section:")
    ]

    result = validate_publication_contract(
        markdown,
        structured_report=report,
        allowed_source_ids={"raw-source-a", "raw-source-b", "raw-source-survey"},
    )

    assert marker_lines
    assert result.passed
    assert all("[source:" not in line for line in marker_lines)


def test_rejects_internal_terms_and_unknown_sources() -> None:
    markdown = "source_registry should stay internal.\n\n正文 [source:unknown-source]\n"

    result = validate_publication_contract(
        markdown,
        structured_report=None,
        allowed_source_ids={"raw-source-a"},
    )

    assert result.issue_codes() == ["internal_term_leak", "invalid_source_id"]
    assert "structured_section" in {
        issue.repair_target for issue in result.issues if issue.code == "internal_term_leak"
    }


def test_rejects_visible_kb_internal_ids() -> None:
    result = validate_publication_contract(
        "Visible internal reference kb:abc123 leaked into the report.\n",
        structured_report=None,
        allowed_source_ids=set(),
    )

    assert result.issue_codes() == ["internal_term_leak"]
    assert result.issues[0].repair_target == "structured_section"


def test_rejects_malformed_source_tokens_and_ids() -> None:
    markdown = (
        "正文 [source:bad id]\n"
        "更多正文 [source:raw-source-a | raw-source-b]\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=None,
        allowed_source_ids={"raw-source-a", "raw-source-b"},
    )

    invalid_issues = [
        issue for issue in result.issues if issue.code == "invalid_source_id"
    ]
    assert len(invalid_issues) == 2
    assert result.issue_codes() == ["invalid_source_id"]


def test_rejects_malformed_source_token_attempts_in_heading_table_and_body() -> None:
    markdown = (
        "### Heading [source :raw-source-a]\n\n"
        "| Dimension [ source:raw-source-a] | Cursor |\n"
        "| --- | --- |\n"
        "| pricing | Body citation 【source:raw-source-a】 |\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=None,
        allowed_source_ids={"raw-source-a"},
    )

    invalid_issues = [
        issue for issue in result.issues if issue.code == "invalid_source_id"
    ]
    assert [issue.line_number for issue in invalid_issues] == [1, 3, 5]
    assert result.issue_codes() == ["invalid_source_id"]


def test_rejects_fullwidth_colon_source_token_attempts() -> None:
    result = validate_publication_contract(
        "Body citation [source\uff1araw-source-a]\n"
        "Spaced citation [source \uff1araw-source-a]\n",
        structured_report=None,
        allowed_source_ids={"raw-source-a"},
    )
    canonical_result = validate_publication_contract(
        "Body citation [source:raw-source-a]\n",
        structured_report=None,
        allowed_source_ids={"raw-source-a"},
    )

    invalid_issues = [
        issue for issue in result.issues if issue.code == "invalid_source_id"
    ]
    assert [issue.line_number for issue in invalid_issues] == [1, 2]
    assert canonical_result.passed


def test_rejects_support_before_core_for_zh_and_non_zh() -> None:
    zh_result = validate_publication_contract(
        "## 支撑材料\n\n补充内容。\n\n## 战报\n\n核心内容。\n",
        structured_report=_report("zh-CN"),
        allowed_source_ids=set(),
    )
    en_result = validate_publication_contract(
        "## Support Materials\n\nSupplement.\n\n## Battlecard\n\nCore.\n",
        structured_report=_report("en-US"),
        allowed_source_ids=set(),
    )

    assert zh_result.issue_codes() == ["support_before_core"]
    assert en_result.issue_codes() == ["support_before_core"]
    assert {issue.repair_target for issue in zh_result.issues + en_result.issues} == {
        "renderer"
    }


def test_rejects_support_sections_before_later_core_sections() -> None:
    zh_result = validate_publication_contract(
        "## 战报\n\n核心内容。\n\n## 支撑材料\n\n补充内容。\n\n## 社区三角验证\n\n核心内容。\n",
        structured_report=_report("zh-CN"),
        allowed_source_ids=set(),
    )
    en_result = validate_publication_contract(
        "## Battlecard\n\nCore.\n\n## Support Materials\n\nSupplement.\n\n"
        "## Community Triangulation\n\nCore.\n",
        structured_report=_report("en-US"),
        allowed_source_ids=set(),
    )
    appendix_result = validate_publication_contract(
        "## Battlecard\n\nCore.\n\n## Source Appendix\n\nSupplement.\n\n"
        "## Community Triangulation\n\nCore.\n",
        structured_report=_report("en-US"),
        allowed_source_ids=set(),
    )

    assert zh_result.issue_codes() == ["support_before_core"]
    assert en_result.issue_codes() == ["support_before_core"]
    assert appendix_result.issue_codes() == ["support_before_core"]


def test_does_not_flag_source_citations_in_body_or_table_cells() -> None:
    markdown = (
        "## Battlecard\n\n"
        "- Body citation [source:raw-source-a]\n\n"
        "| Dimension | Cursor |\n"
        "| --- | --- |\n"
        "| pricing | Cell citation [source:raw-source-b] |\n"
        "\n## Support Materials\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=None,
        allowed_source_ids={"raw-source-a", "raw-source-b"},
    )

    assert result.passed
    assert result.issues == []


def test_telemetry_payload_returns_stable_fields() -> None:
    result = validate_publication_contract(
        "Segment Evidence Pack JSON leaked.\n",
        structured_report=None,
        allowed_source_ids=set(),
    )

    assert result.telemetry_payload() == {
        "passed": False,
        "issue_count": 1,
        "issue_codes": ["internal_term_leak"],
        "repair_targets": ["structured_section"],
    }
