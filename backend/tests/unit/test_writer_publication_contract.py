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
