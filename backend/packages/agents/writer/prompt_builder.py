from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from packages.schema.api_dto import RunDetail


@dataclass(frozen=True)
class WriterPrompt:
    system: str
    user: str


@dataclass(frozen=True)
class WriterPromptBuilder:
    def first_draft_prompt(
        self,
        detail: RunDetail,
        *,
        language_guidance: str,
        user_research_policy: str,
        memory_context: str,
        layer_context: str,
        grounding_prompt: str,
        community_policy_text: str,
        writer_context_json: str,
        required_sections: str,
    ) -> WriterPrompt:
        return WriterPrompt(
            system=(
                "You are a senior enterprise competitive-intelligence analyst. "
                "Produce a concise decision-grade markdown first draft, not a short "
                "summary. Use an analysis-first structure: lead with an executive "
                "takeaway, decision summary, competitive findings, competitor deep "
                "dives, and the selected layer-specific analysis. Put source quality, "
                "scenario QA, claim risk, RAG gap-fill, verification tasks, and the "
                "evidence appendix after the core analysis as support material. Write "
                "with consulting depth: side-by-side matrices, dimension analysis, "
                "risks, buying implications, and explicit next validation tasks. Cite "
                "factual claims with existing source IDs using [source:ID]. Do not "
                "invent source IDs. "
                "Do not use web_search_result or confidence < 0.75 as the sole support "
                "for a winner, legal/security certification, pricing, or procurement "
                "recommendation. If evidence is incomplete, say the conclusion is "
                "tentative and list the exact evidence gap. Do not claim all sources "
                "are verified when any source_type is web_search_result or "
                "llm_public_knowledge. "
                "Follow the Grounded Evidence Contract exactly. "
                f"{language_guidance} "
                f"{user_research_policy} "
                "Honor confirmed memory guidance when it does not conflict with "
                "evidence, schema requirements, or compliance policy. "
                "Use the requested competitive layer to choose the report shape: L1 "
                "is a direct battlecard, L2 is adjacent workflow and enterprise-risk "
                "analysis, and L3 is market landscape and category strategy."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                f"Competitive Layer: {detail.plan.competitor_layer}\n"
                f"Scenario ID: {detail.plan.scenario_id or 'auto'}\n"
                "Scenario Recommended Dimensions: "
                f"{', '.join(detail.plan.scenario_recommended_dimensions)}\n"
                f"QA Rule IDs: {', '.join(detail.plan.qa_rule_ids)}\n"
                f"Confirmed Memory Preferences:\n{memory_context}\n"
                f"Layer Report Context: {layer_context}\n"
                f"{grounding_prompt}\n"
                f"{community_policy_text}\n"
                f"Writer Report Brief JSON: {writer_context_json}\n\n"
                f"Required sections:\n{required_sections}\n"
                "Target 16,000-20,000 characters for the first draft. Use about "
                "70-80% of the report on the Core analysis layer: decision summary, "
                "competitive findings, user review themes, competitor deep dives, "
                "SWOT, matrix interpretation, and layer-specific implications. "
                "Core section minimums: Decision Summary 800+ characters; "
                "Competitive Findings 1,200+; User Review Themes 1,000+ when "
                "review, community, survey, interview, or persona evidence exists; "
                "Competitor Deep Dives 1,400+ and every competitor covered; SWOT "
                "1,400+ with explicit Strengths, Weaknesses, Opportunities, and "
                "Threats for every competitor; Matrix Interpretation 900+; "
                "Layer-specific Battlecard/Workflow/Market section 1,200+. Keep "
                "the Support/audit layer concise and complete; it is the audit trail, "
                "not the main readout. Prefer deeper cited analysis and decision "
                "implications over repeated source IDs or QA boilerplate."
            ),
        )

    def segment_prompt(
        self,
        detail: RunDetail,
        *,
        segment: dict[str, object],
        segment_json: str,
        retry_count: int,
        allowed_h2_headings: str,
        required_h2_headings: str,
        forbidden_h2_headings: str,
        segment_outline: str,
        citation_warning: str,
        contract_warning: str,
        user_research_gap_instruction: str,
        shard_instruction: str,
        language_guidance: str,
        user_research_policy: str,
        memory_context: str,
        layer_context: str,
        community_policy_text: str,
        required_sections: str,
    ) -> WriterPrompt:
        return WriterPrompt(
            system=(
                "You are a senior enterprise competitive-intelligence analyst writing "
                "one section group of a larger markdown report. Return only markdown "
                "for this segment. Cite factual claims only with source IDs in "
                "allowed_source_ids. Do not invent source IDs. Use exact [source:ID] "
                "syntax with no space after source:. Do not combine multiple source "
                "IDs inside one [source:...] token; write consecutive citations "
                "like [source:A][source:B]. Do not put citations in headings or "
                "table header rows. "
                "Do not use web_search_result or confidence < 0.75 as the sole support "
                "for a winner, legal/security certification, pricing, or procurement "
                "recommendation. If evidence is incomplete, say the conclusion is "
                "tentative and list the exact evidence gap. Do not claim all sources "
                "are verified when any source_type is web_search_result or "
                "llm_public_knowledge. "
                f"{user_research_policy} "
                f"{language_guidance}"
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                f"segment_name={segment['segment_name']}\n"
                f"segment_kind={segment.get('segment_kind', 'section_fragment')}\n"
                f"section_id={segment.get('section_id', segment['segment_name'])}\n"
                f"segment_competitor={segment.get('segment_competitor') or 'all'}\n"
                f"retry_count={retry_count}\n"
                "Allowed H2 headings for this segment: "
                f"{allowed_h2_headings or 'none'}\n"
                "Required H2 headings for this segment: "
                f"{required_h2_headings or 'none'}\n"
                "Forbidden H2 headings for this segment: "
                f"{forbidden_h2_headings or 'none'}\n"
                f"{segment_outline}\n"
                f"{citation_warning}"
                f"{contract_warning}"
                f"{user_research_gap_instruction}"
                f"{shard_instruction}"
                "Do not write headings outside this segment's contract. "
                "Do not write support or appendix sections unless "
                "segment_kind=support_fragment. If segment_kind=evidence_shard, "
                "do not write any ## H2 headings. Never mention Segment Evidence Pack, "
                "Writer Evidence Pack, Writer Report Brief, report_brief, writer_constraints, "
                "source_registry, allowed_source_ids, or other writer-internal field "
                "names in the reader-facing markdown.\n"
                f"Confirmed Memory Preferences:\n{memory_context}\n"
                f"Layer Report Context: {layer_context}\n"
                f"{community_policy_text}\n"
                f"Segment Evidence Pack JSON: {segment_json}\n\n"
                f"Required sections for full report:\n{required_sections}\n"
                "Write with consulting depth for this segment. Keep support material "
                "concise and preserve [source:ID] citation syntax."
            ),
        )

    def section_repair_prompt(
        self,
        detail: RunDetail,
        *,
        sections: Sequence[str],
        section_headings: str,
        language_guidance: str,
        community_policy_text: str,
        writer_context_json: str,
        previous_report: str,
    ) -> WriterPrompt:
        return WriterPrompt(
            system=(
                "You are a senior enterprise competitive-intelligence analyst repairing "
                "one section of an existing markdown report. Return only the requested "
                "section markdown. Preserve existing [source:ID] syntax, never invent "
                "source IDs, and cite factual claims with available source IDs. "
                f"{language_guidance}"
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                f"Repair only these sections: {', '.join(sections)}\n"
                f"Expected section headings:\n{section_headings}\n"
                "return only the requested section markdown; do not rewrite unrelated "
                "sections or include commentary outside the section.\n"
                "Use the exact requested level-2 heading for each returned section.\n"
                "You must preserve existing [source:ID] syntax.\n"
                f"{community_policy_text}\n"
                f"Writer Repair Context JSON: {writer_context_json}\n\n"
                f"Previous report:\n{previous_report}"
            ),
        )


def writer_user_research_policy_text() -> str:
    source_types = ", ".join(
        (
            "survey_simulated",
            "survey_response",
            "interview_record",
            "manual_transcript",
            "manual_user_note",
            "manual_note",
            "manual",
        )
    )
    return (
        f"Treat {source_types} as user-research signals, not as official factual proof."
    )
