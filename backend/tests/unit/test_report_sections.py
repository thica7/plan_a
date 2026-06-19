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

    assert index.is_support_or_audit_line(4) is False
    assert index.is_support_or_audit_line(9) is True
    assert index.is_support_or_audit_line(12) is True
    assert [section.heading for section in index.sections_before_support()] == [
        "AI Coding Agent Report",
        "Executive Summary",
    ]
