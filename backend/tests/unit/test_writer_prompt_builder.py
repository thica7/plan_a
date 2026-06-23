from __future__ import annotations

from packages.agents.writer.prompt_builder import (
    WriterPromptBuilder,
    writer_user_research_policy_text,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan


def _detail() -> RunDetail:
    return RunDetail(
        id="run-writer-prompt-builder",
        topic="AI coding agent",
        status="running",
        execution_mode="demo",
        created_at="2026-06-20T00:00:00",
        updated_at="2026-06-20T00:00:00",
        output_language="en-US",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Acme"],
            dimensions=["pricing", "feature"],
            competitor_layer="L1",
            scenario_id="l1_pricing_pack",
            scenario_recommended_dimensions=["pricing"],
            qa_rule_ids=["citation-required"],
        ),
    )


def test_first_draft_prompt_keeps_report_brief_contract() -> None:
    prompt = WriterPromptBuilder().first_draft_prompt(
        _detail(),
        language_guidance="Use English.",
        user_research_policy=writer_user_research_policy_text(),
        memory_context="Prefer procurement framing.",
        layer_context="Layer context.",
        grounding_prompt="Grounded Evidence Contract.",
        community_policy_text="Community policy.",
        writer_context_json='{"report_brief": {}}',
        required_sections="## Decision Summary",
    )

    assert "decision-grade markdown first draft" in prompt.system
    assert "Grounded Evidence Contract" in prompt.user
    assert "Writer Report Brief JSON" in prompt.user
    assert "Writer Evidence Pack JSON" not in prompt.user
    assert "Prefer procurement framing." in prompt.user


def test_segment_prompt_keeps_contract_and_retry_guidance() -> None:
    prompt = WriterPromptBuilder().segment_prompt(
        _detail(),
        segment={
            "segment_name": "decision_summary",
            "segment_kind": "section_fragment",
            "section_id": "decision_summary",
        },
        segment_json='{"segment_name": "decision_summary"}',
        retry_count=1,
        allowed_h2_headings="Decision Summary",
        required_h2_headings="Decision Summary",
        forbidden_h2_headings="Evidence Appendix",
        segment_outline="Required segment outline.",
        citation_warning="Previous segment cited source IDs outside this segment.\n",
        contract_warning="Previous segment violated its heading contract.\n",
        user_research_gap_instruction="",
        shard_instruction="",
        language_guidance="Use English.",
        user_research_policy=writer_user_research_policy_text(),
        memory_context="none",
        layer_context="Layer context.",
        community_policy_text="Community policy.",
        required_sections="## Decision Summary",
    )

    assert "report_writer_segment" not in prompt.user
    assert "retry_count=1" in prompt.user
    assert "Allowed H2 headings for this segment: Decision Summary" in prompt.user
    assert "Previous segment violated its heading contract" in prompt.user
    assert "Segment Evidence Pack JSON" in prompt.user
    assert "Do not write headings outside this segment's contract" in prompt.user


def test_section_repair_prompt_is_scoped_to_requested_sections() -> None:
    prompt = WriterPromptBuilder().section_repair_prompt(
        _detail(),
        sections=["decision_summary"],
        section_headings="decision_summary -> ## Decision Summary",
        language_guidance="Use English.",
        community_policy_text="Community policy.",
        writer_context_json='{"repair_sections": ["decision_summary"]}',
        previous_report="## Decision Summary\nThin.",
    )

    assert "repairing one section" in prompt.system
    assert "Repair only these sections: decision_summary" in prompt.user
    assert "Writer Repair Context JSON" in prompt.user
    assert "do not rewrite unrelated sections" in prompt.user
