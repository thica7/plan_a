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


def test_section_index_classifies_real_chinese_support_and_audit_headings() -> None:
    markdown = """# AI Coding Agent

## 执行摘要
这里是核心判断。

## 支撑材料
官方来源可能不足，社区来源只作为风险信号。

## 证据与 QA 支撑
这里是审计信息。

## 声明校验与证据风险
这里是声明风险。
"""

    index = build_report_section_index(markdown)

    assert index.is_support_or_audit_line(4) is False
    assert index.is_support_or_audit_line(7) is True
    assert index.is_support_or_audit_line(10) is True
    assert index.is_support_or_audit_line(13) is True
    assert [section.heading for section in index.sections_before_support()] == [
        "AI Coding Agent",
        "执行摘要",
    ]


def test_section_index_prefers_structured_markers_over_heading_text() -> None:
    markdown = """# AI Coding Agent

<!-- report-section:key=executive_summary layer=core -->
## Evidence Appendix
This is intentionally a core section despite the support-looking title.

<!-- report-section:key=evidence_support layer=support -->
## Custom Analysis
Official-looking caveats here belong to support.
"""

    index = build_report_section_index(markdown)

    executive = index.section_for_line(5)
    support = index.section_for_line(9)

    assert executive is not None
    assert executive.heading == "Evidence Appendix"
    assert executive.section_key == "executive_summary"
    assert executive.layer == "core"
    assert support is not None
    assert support.heading == "Custom Analysis"
    assert support.section_key == "evidence_support"
    assert support.layer == "support"
    assert index.is_support_or_audit_line(5) is False
    assert index.is_support_or_audit_line(9) is True
    assert [section.section_key for section in index.sections_before_support()] == [
        None,
        "executive_summary",
    ]
