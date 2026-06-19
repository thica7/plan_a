from __future__ import annotations

from packages.agents.writer.assembler import assemble_report_sections
from packages.business_intel.report_sections import build_report_section_index
from packages.i18n.language import report_label


def test_assembler_merges_duplicate_sections_and_moves_support_after_core() -> None:
    result = assemble_report_sections(
        [
            "Intro paragraph with [source:intro].",
            "## Decision Summary\nFirst decision line [source:decision-1].",
            "## Evidence and QA Support\nFirst evidence line [source:evidence-1].",
            "## Competitor Deep Dives\nDeep dive line [source:deep-dive].",
            "## Decision Summary\nSecond decision line [source:decision-2].",
            "## SWOT Analysis\nSWOT line [source:swot].",
            "## Evidence and QA Support\nSecond evidence line [source:evidence-2].",
        ],
        output_language="en-US",
        competitors=["Acme", "Beta"],
    )

    assert result.markdown.count("## Decision Summary") == 1
    assert result.markdown.count("## Evidence & QA Support") == 1
    assert result.markdown.index("## Competitor Deep Dives") < result.markdown.index(
        "## Evidence & QA Support"
    )
    assert result.markdown.index("## SWOT Analysis") < result.markdown.index(
        "## Evidence & QA Support"
    )
    for line in (
        "Intro paragraph with [source:intro].",
        "First decision line [source:decision-1].",
        "Second decision line [source:decision-2].",
        "First evidence line [source:evidence-1].",
        "Second evidence line [source:evidence-2].",
        "Deep dive line [source:deep-dive].",
        "SWOT line [source:swot].",
    ):
        assert line in result.markdown
    assert result.telemetry["duplicate_section_count_before"] == 2
    assert result.telemetry["duplicate_section_count_after"] == 0
    assert result.telemetry["competitors"] == ["Acme", "Beta"]
    assert isinstance(result.telemetry["merged_section_keys"], list)
    assert isinstance(result.telemetry["competitors"], list)
    assert set(result.telemetry["merged_section_keys"]) >= {
        "decision_summary",
        "evidence_support",
    }


def test_assembler_emits_structured_section_markers_for_known_sections() -> None:
    result = assemble_report_sections(
        [
            "## Decision Summary\nDecision body [source:decision].",
            "## Evidence and QA Support\nSupport body [source:support].",
        ],
        output_language="en-US",
        competitors=["Acme"],
    )

    assert "<!-- report-section:key=decision_summary layer=core -->" in result.markdown
    assert "<!-- report-section:key=evidence_support layer=support -->" in result.markdown

    index = build_report_section_index(result.markdown)
    decision = next(
        section for section in index.sections if section.section_key == "decision_summary"
    )
    support = next(
        section for section in index.sections if section.section_key == "evidence_support"
    )
    assert decision.layer == "core"
    assert support.layer == "support"
    assert result.markdown.index("## Decision Summary") < result.markdown.index(
        "## Evidence & QA Support"
    )


def test_assembler_preserves_unknown_core_before_support() -> None:
    result = assemble_report_sections(
        [
            "## Evidence Appendix\nEvidence appendix body.",
            "## Custom Core Insight\nCustom insight body.",
        ],
        output_language="en-US",
        competitors=[],
    )

    assert result.markdown.index("## Custom Core Insight") < result.markdown.index(
        "## Evidence Appendix"
    )
    assert result.telemetry["unknown_core_section_count"] == 1


def test_assembler_reports_duplicate_unknown_h2s_after_assembly() -> None:
    result = assemble_report_sections(
        [
            "## Custom Core Insight\nFirst custom body [source:custom-1].",
            "## Custom Core Insight\nSecond custom body [source:custom-2].",
        ],
        output_language="en-US",
        competitors=["Acme"],
    )

    assert result.markdown.count("## Custom Core Insight") == 2
    assert "First custom body [source:custom-1]." in result.markdown
    assert "Second custom body [source:custom-2]." in result.markdown
    assert result.telemetry["duplicate_section_count_after"] == 1
    assert result.telemetry["competitors"] == ["Acme"]


def test_assembler_handles_zh_labels() -> None:
    decision = report_label("zh-CN", "decision_summary")
    evidence = report_label("zh-CN", "evidence_support")
    deep_dives = report_label("zh-CN", "competitor_deep_dives")

    result = assemble_report_sections(
        [
            f"## {evidence}\nEvidence body [source:zh-evidence].",
            f"## {deep_dives}\nDeep dive body [source:zh-dive].",
            f"## {decision}\nDecision body [source:zh-decision].",
        ],
        output_language="zh-CN",
        competitors=["\u7532", "\u4e59"],
    )

    assert result.markdown.index(f"## {decision}") < result.markdown.index(
        f"## {evidence}"
    )
    assert result.markdown.index(f"## {deep_dives}") < result.markdown.index(
        f"## {evidence}"
    )
