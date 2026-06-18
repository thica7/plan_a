from __future__ import annotations

from packages.agents.writer.segment_contract import (
    heading_key_for,
    segment_contract_for,
    validate_segment_contract,
)
from packages.i18n.language import report_label


def test_decision_summary_contract_rejects_support_heading() -> None:
    contract = segment_contract_for(
        {"segment_name": "decision_summary", "output_language": "en-US"}
    )
    markdown = f"## {report_label('en-US', 'evidence_support')}\nEvidence details."

    result = validate_segment_contract(markdown, contract)

    assert contract.segment_name == "decision_summary"
    assert contract.essential is True
    assert "evidence_support" in contract.forbidden_heading_keys
    assert result.status == "retry"
    assert result.h2_headings == [report_label("en-US", "evidence_support")]
    assert result.forbidden_headings == [report_label("en-US", "evidence_support")]
    assert result.forbidden_heading_keys == ["evidence_support"]
    assert result.invalid_heading_keys == []
    assert result.errors == ["segment contains forbidden H2 headings"]


def test_competitor_deep_dive_contract_rejects_full_report_heading() -> None:
    contract = segment_contract_for(
        {"segment_name": "competitor_deep_dives", "output_language": "en-US"}
    )
    markdown = f"## {report_label('en-US', 'decision_summary')}\nDecision summary."

    result = validate_segment_contract(markdown, contract)

    assert result.status == "retry"
    assert result.h2_headings == [report_label("en-US", "decision_summary")]
    assert result.forbidden_headings == [report_label("en-US", "decision_summary")]
    assert result.forbidden_heading_keys == ["decision_summary"]
    assert result.invalid_heading_keys == []
    assert result.errors == ["segment contains forbidden H2 headings"]


def test_support_contract_rejects_core_deep_dive_heading() -> None:
    contract = segment_contract_for(
        {"segment_name": "support_appendix", "output_language": "en-US"}
    )
    markdown = f"## {report_label('en-US', 'competitor_deep_dives')}\nDeep dive."

    result = validate_segment_contract(markdown, contract)

    assert contract.segment_name == "support_appendix"
    assert contract.segment_kind == "support_fragment"
    assert contract.section_id == "evidence_support"
    assert "competitor_deep_dives" in contract.forbidden_heading_keys
    assert result.status == "retry"
    assert result.h2_headings == [report_label("en-US", "competitor_deep_dives")]
    assert result.forbidden_headings == [
        report_label("en-US", "competitor_deep_dives")
    ]
    assert result.forbidden_heading_keys == ["competitor_deep_dives"]
    assert result.invalid_heading_keys == []
    assert result.errors == ["segment contains forbidden H2 headings"]


def test_evidence_shard_contract_rejects_any_h2() -> None:
    contract = segment_contract_for(
        {"segment_kind": "evidence_shard", "output_language": "en-US"}
    )
    markdown = "## Any Heading\nEvidence details."

    result = validate_segment_contract(markdown, contract)

    assert result.status == "retry"
    assert result.h2_headings == ["Any Heading"]
    assert result.forbidden_headings == []
    assert result.forbidden_heading_keys == []
    assert result.invalid_heading_keys == []
    assert result.errors == ["evidence_shard must not contain H2 headings"]


def test_competitor_deep_dive_evidence_shard_preserves_owner_without_h3() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "competitor_deep_dives",
            "section_id": "competitor_deep_dives",
            "segment_kind": "evidence_shard",
            "segment_competitor": "Cursor",
            "output_language": "en-US",
        }
    )
    markdown = "- Cursor shard note [source:cursor-pricing]"

    result = validate_segment_contract(markdown, contract)

    assert contract.segment_kind == "evidence_shard"
    assert contract.section_id == "competitor_deep_dives"
    assert contract.segment_competitor == "Cursor"
    assert contract.allow_h2 is False
    assert result.status == "pass"
    assert result.errors == []


def test_evidence_shard_kind_takes_precedence_over_support_section() -> None:
    contract = segment_contract_for(
        {
            "segment_kind": "evidence_shard",
            "section_id": "evidence_support",
            "output_language": "en-US",
        }
    )
    markdown = f"## {report_label('en-US', 'evidence_support')}\nEvidence details."

    result = validate_segment_contract(markdown, contract)

    assert contract.segment_kind == "evidence_shard"
    assert contract.allow_h2 is False
    assert result.status == "retry"
    assert result.h2_headings == [report_label("en-US", "evidence_support")]
    assert result.errors == ["evidence_shard must not contain H2 headings"]


def test_empty_segment_output_fails() -> None:
    contract = segment_contract_for(
        {"segment_name": "decision_summary", "output_language": "en-US"}
    )

    result = validate_segment_contract(" \n\t", contract)

    assert result.status == "fail"
    assert result.h2_headings == []
    assert result.forbidden_headings == []
    assert result.forbidden_heading_keys == []
    assert result.invalid_heading_keys == []
    assert result.errors == ["segment output is empty"]


def test_required_section_body_text_without_h2_retries() -> None:
    contract = segment_contract_for(
        {"segment_name": "decision_summary", "output_language": "en-US"}
    )

    result = validate_segment_contract("Plain body text without headings.", contract)

    assert result.status == "retry"
    assert result.h2_headings == []
    assert result.missing_required_heading_keys == [
        "decision_summary",
        "competitive_findings",
    ]
    assert result.errors == ["segment is missing required H2 headings"]


def test_contract_honors_explicit_section_id_and_segment_essential() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "user_research",
            "section_id": "swot_matrix",
            "segment_essential": False,
            "output_language": "en-US",
        }
    )

    assert contract.segment_name == "user_research"
    assert contract.section_id == "swot_matrix"
    assert contract.essential is False
    assert "comparison_matrix" in contract.allowed_heading_keys
    assert "business_implications" in contract.allowed_heading_keys


def test_known_heading_outside_allowed_contract_is_invalid_not_forbidden() -> None:
    contract = segment_contract_for(
        {"segment_name": "decision_summary", "output_language": "en-US"}
    )
    markdown = f"## {report_label('en-US', 'competitor_deep_dives')}\nDeep dive."

    result = validate_segment_contract(markdown, contract)

    assert result.status == "retry"
    assert result.h2_headings == [report_label("en-US", "competitor_deep_dives")]
    assert result.forbidden_headings == []
    assert result.forbidden_heading_keys == []
    assert result.invalid_heading_keys == ["competitor_deep_dives"]
    assert result.errors == ["segment contains H2 headings outside its allowed contract"]


def test_decision_summary_contract_requires_competitive_findings() -> None:
    contract = segment_contract_for(
        {"segment_name": "decision_summary", "output_language": "en-US"}
    )
    markdown = f"## {report_label('en-US', 'decision_summary')}\nDecision only."

    result = validate_segment_contract(markdown, contract)

    assert result.status == "retry"
    assert result.missing_required_heading_keys == ["competitive_findings"]
    assert result.errors == ["segment is missing required H2 headings"]


def test_swot_matrix_contract_requires_side_by_side_matrix_and_swot() -> None:
    contract = segment_contract_for(
        {"segment_name": "swot_matrix", "output_language": "en-US"}
    )
    markdown = f"## {report_label('en-US', 'swot_analysis')}\nSWOT only."

    result = validate_segment_contract(markdown, contract)

    assert result.status == "retry"
    assert result.missing_required_heading_keys == ["side_by_side_matrix"]
    assert result.errors == ["segment is missing required H2 headings"]


def test_unknown_h2_heading_retries_with_unknown_heading_error() -> None:
    contract = segment_contract_for(
        {"segment_name": "decision_summary", "output_language": "en-US"}
    )

    result = validate_segment_contract("## Unexpected Custom Heading\nBody.", contract)

    assert result.status == "retry"
    assert result.h2_headings == ["Unexpected Custom Heading"]
    assert result.forbidden_headings == []
    assert result.forbidden_heading_keys == []
    assert result.invalid_heading_keys == []
    assert result.errors == ["segment contains unknown H2 headings"]


def test_heading_key_for_normalizes_closing_markdown_hashes() -> None:
    assert heading_key_for("Decision Summary ##", "en-US") == "decision_summary"


def test_heading_key_for_is_deterministic_across_repeated_calls() -> None:
    results = [heading_key_for("Decision Summary", "en-US") for _ in range(10)]

    assert results == ["decision_summary"] * 10


def test_valid_user_research_contract_passes_localized_heading() -> None:
    contract = segment_contract_for(
        {"segment_name": "user_research", "output_language": "zh-CN"}
    )
    localized_heading = report_label("zh-CN", "review_theme_summary")
    markdown = f"## {localized_heading}\n- Localized review summary."

    result = validate_segment_contract(markdown, contract)

    assert contract.section_id == "review_theme_summary"
    assert result.status == "pass"
    assert result.h2_headings == [localized_heading]
    assert result.forbidden_headings == []
    assert result.forbidden_heading_keys == []
    assert result.invalid_heading_keys == []
    assert result.errors == []


def test_competitor_deep_dive_requires_matching_competitor_heading() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "competitor_deep_dives",
            "section_id": "competitor_deep_dives",
            "segment_competitor": "GitHub Copilot",
            "output_language": "en-US",
        }
    )
    markdown = (
        "## Competitor Deep Dives\n"
        "### Pricing and Packaging\n"
        "GitHub Copilot pricing is visible. [source:copilot-pricing]"
    )

    result = validate_segment_contract(markdown, contract)

    assert contract.segment_competitor == "GitHub Copilot"
    assert result.status == "retry"
    assert result.errors == ["segment is missing required competitor heading"]


def test_competitor_deep_dive_accepts_exact_competitor_h3() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "competitor_deep_dives",
            "section_id": "competitor_deep_dives",
            "segment_competitor": "GitHub Copilot",
            "output_language": "en-US",
        }
    )
    markdown = (
        "## Competitor Deep Dives\n"
        "### GitHub Copilot\n"
        "GitHub Copilot pricing is visible. [source:copilot-pricing]"
    )

    result = validate_segment_contract(markdown, contract)

    assert result.status == "pass"
    assert result.errors == []


def test_competitor_deep_dive_rejects_extra_non_competitor_h3() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "competitor_deep_dives",
            "section_id": "competitor_deep_dives",
            "segment_competitor": "GitHub Copilot",
            "output_language": "en-US",
        }
    )
    markdown = (
        "## Competitor Deep Dives\n"
        "### GitHub Copilot\n"
        "GitHub Copilot pricing is visible. [source:copilot-pricing]\n"
        "### Pricing and Packaging\n"
        "Packaging detail should stay under the competitor H3. [source:copilot-pricing]"
    )

    result = validate_segment_contract(markdown, contract)

    assert result.status == "retry"
    assert result.errors == ["segment contains non-competitor H3 headings"]


def test_competitor_deep_dive_rejects_competitor_heading_at_h4() -> None:
    contract = segment_contract_for(
        {
            "segment_name": "competitor_deep_dives",
            "section_id": "competitor_deep_dives",
            "segment_competitor": "GitHub Copilot",
            "output_language": "en-US",
        }
    )
    markdown = (
        "## Competitor Deep Dives\n"
        "### Pricing and Packaging\n"
        "#### GitHub Copilot\n"
        "GitHub Copilot pricing is visible. [source:copilot-pricing]"
    )

    result = validate_segment_contract(markdown, contract)

    assert result.status == "retry"
    assert result.errors == ["segment is missing required competitor heading"]
