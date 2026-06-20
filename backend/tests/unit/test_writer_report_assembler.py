from __future__ import annotations

from packages.agents.writer.assembler import (
    ReportSectionFragment,
    assemble_report_fragments,
    assemble_report_sections,
)
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


def test_keyed_assembler_uses_fragment_layer_for_unknown_sections() -> None:
    fragments = [
        ReportSectionFragment(
            markdown="## Custom Core Readout\nCore finding. [source:raw-source-a]",
            section_key="custom_core_readout",
            layer="core",
            segment_name="decision_summary",
        ),
        ReportSectionFragment(
            markdown="## Mystery Audit Notes\nSupport note. [source:raw-source-b]",
            section_key="support_appendix",
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


def test_keyed_assembler_wraps_body_only_fragment_with_canonical_section() -> None:
    fragments = [
        ReportSectionFragment(
            markdown="Decision body without its own heading. [source:raw-source-a]",
            section_key="decision_summary",
            layer="core",
            segment_name="decision_summary",
        )
    ]

    assembled = assemble_report_fragments(
        fragments,
        output_language="en-US",
        competitors=["Cursor"],
    )

    assert assembled.markdown.startswith(
        "<!-- report-section:key=decision_summary layer=core -->\n## Decision Summary"
    )
    assert "Decision body without its own heading" in assembled.markdown
    assert assembled.telemetry["output_section_count"] == 1
    assert assembled.telemetry["fragment_section_keys"] == ["decision_summary"]


def test_keyed_assembler_keeps_heading_only_canonical_section() -> None:
    fragments = [
        ReportSectionFragment(
            markdown="## Decision Summary",
            section_key="decision_summary",
            layer="core",
            segment_name="decision_summary",
        )
    ]

    assembled = assemble_report_fragments(
        fragments,
        output_language="en-US",
        competitors=["Cursor"],
    )

    assert assembled.markdown.startswith(
        "<!-- report-section:key=decision_summary layer=core -->\n## Decision Summary"
    )
    assert assembled.telemetry["output_section_count"] == 1
    assert assembled.telemetry["fragment_section_keys"] == ["decision_summary"]


def test_keyed_assembler_canonical_section_key_overrides_misleading_heading() -> None:
    fragments = [
        ReportSectionFragment(
            markdown="## Evidence & QA Support\nThis is actually decision content. [source:raw-source-a]",
            section_key="decision_summary",
            layer="core",
            segment_name="decision_summary",
        )
    ]

    assembled = assemble_report_fragments(
        fragments,
        output_language="en-US",
        competitors=["Cursor"],
    )

    assert assembled.markdown.startswith(
        "<!-- report-section:key=decision_summary layer=core -->\n## Decision Summary"
    )
    assert "This is actually decision content" in assembled.markdown
    assert "## Evidence & QA Support" not in assembled.markdown
    assert assembled.telemetry["first_support_key"] is None


def test_keyed_assembler_keeps_intro_inside_canonical_section() -> None:
    fragments = [
        ReportSectionFragment(
            markdown=(
                "Lead-in decision sentence. [source:raw-source-a]\n\n"
                "## Evidence & QA Support\n"
                "This H2 should not define the section. [source:raw-source-a]"
            ),
            section_key="decision_summary",
            layer="core",
            segment_name="decision_summary",
        )
    ]

    assembled = assemble_report_fragments(
        fragments,
        output_language="en-US",
        competitors=["Cursor"],
    )

    assert assembled.markdown.startswith(
        "<!-- report-section:key=decision_summary layer=core -->\n## Decision Summary"
    )
    assert "Lead-in decision sentence" in assembled.markdown
    assert assembled.markdown.index("Lead-in decision sentence") > assembled.markdown.index(
        "## Decision Summary"
    )
    assert "## Evidence & QA Support" not in assembled.markdown


def test_keyed_assembler_distributes_allowed_headings_to_matching_markers() -> None:
    fragments = [
        ReportSectionFragment(
            markdown=(
                "## Executive Summary\n"
                "Executive body. [source:raw-source-a]\n\n"
                "## Decision Summary\n"
                "Decision body. [source:raw-source-a]\n\n"
                "## Competitive Findings\n"
                "Findings body. [source:raw-source-a]"
            ),
            section_key="decision_summary",
            layer="core",
            segment_name="decision_summary",
        )
    ]

    assembled = assemble_report_fragments(
        fragments,
        output_language="en-US",
        competitors=["Cursor"],
    )

    index = build_report_section_index(assembled.markdown)
    heading_to_key = {
        section.heading: section.section_key
        for section in index.sections
        if section.heading
        in {"Executive Summary", "Decision Summary", "Competitive Findings"}
    }

    assert heading_to_key == {
        "Executive Summary": "executive_summary",
        "Decision Summary": "decision_summary",
        "Competitive Findings": "competitive_findings",
    }
    assert assembled.markdown.index("## Executive Summary") < assembled.markdown.index(
        "## Decision Summary"
    )
    assert assembled.markdown.index("## Decision Summary") < assembled.markdown.index(
        "## Competitive Findings"
    )


def test_keyed_assembler_treats_audit_layer_as_support_for_unknown_sections() -> None:
    fragments = [
        ReportSectionFragment(
            markdown="## Mystery Audit Notes\nAudit note. [source:raw-source-a]",
            section_key="custom_audit_notes",
            layer="audit",
            segment_name="support_appendix",
        ),
        ReportSectionFragment(
            markdown="## Custom Core Readout\nCore note. [source:raw-source-b]",
            section_key="custom_core_readout",
            layer="core",
            segment_name="decision_summary",
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
    assert assembled.telemetry["unknown_support_section_count"] == 1
    assert assembled.telemetry["unknown_core_section_count"] == 1


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
