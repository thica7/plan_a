from __future__ import annotations

from collections.abc import Mapping, Sequence

from packages.agents.writer.assembler import CANONICAL_REPORT_ORDER
from packages.agents.writer.segment_contract import (
    CORE_HEADING_KEYS,
    SUPPORT_HEADING_KEYS,
    heading_key_for,
)
from packages.business_intel.report_sections import (
    ReportSection,
    SectionLayer,
    build_report_section_index,
)
from packages.schema.api_dto import RunDetail
from packages.schema.report_artifact import (
    ReportArtifactLegacyInfo,
    ReportArtifactRenderCache,
    ReportArtifactV2,
    ReportLayer,
    ReportLayerSection,
    ReportQualityAccount,
    SectionBrief,
)


def assemble_report_artifact_v2(
    detail: RunDetail,
    section_markdown_by_key: Mapping[str, str],
) -> ReportArtifactV2:
    layer_markdowns = _layer_markdowns(
        section_markdown_by_key,
        output_language=detail.output_language,
    )
    brief_by_key = _brief_by_key(detail.section_briefs)
    core_markdown = layer_markdowns["core"]
    support_markdown = layer_markdowns["support"]
    audit_markdown = layer_markdowns["audit"]
    return ReportArtifactV2(
        artifact_version=2,
        run_id=detail.id,
        core_report=ReportLayer(
            layer="core",
            markdown=core_markdown,
            sections=_layer_sections(
                core_markdown,
                briefs=brief_by_key,
                output_language=detail.output_language,
            ),
        ),
        support_appendix=ReportLayer(
            layer="support",
            markdown=support_markdown,
            sections=_layer_sections(
                support_markdown,
                briefs=brief_by_key,
                output_language=detail.output_language,
            ),
        ),
        audit_log=ReportLayer(
            layer="audit",
            markdown=audit_markdown,
            sections=_layer_sections(
                audit_markdown,
                briefs=brief_by_key,
                output_language=detail.output_language,
            ),
            metadata={"audit_content": "empty"} if not audit_markdown else {},
        ),
        claim_card_bundles=list(detail.claim_card_bundles),
        decision_card_bundle=detail.decision_card_bundle,
        section_briefs=list(detail.section_briefs),
        quality=ReportQualityAccount(
            core_gate={"status": "not_run"},
            support_gate={"status": "not_run"},
            audit_gate={"status": "not_run"},
            warnings=[],
            blockers=[],
            revision_count=len(detail.revisions),
        ),
        render_cache=ReportArtifactRenderCache(
            core_markdown=core_markdown,
            support_markdown=support_markdown,
            audit_markdown=audit_markdown,
            full_markdown=_join_markdown(
                (core_markdown, support_markdown, audit_markdown)
            ),
        ),
        legacy=ReportArtifactLegacyInfo(
            source="report_artifact_v2",
            report_md_alias=True,
        ),
        metadata={
            "assembler": "deterministic_report_artifact_v2",
            "output_language": detail.output_language,
            "section_keys": _ordered_section_keys(section_markdown_by_key),
        },
    )


def _layer_markdowns(
    section_markdown_by_key: Mapping[str, str],
    *,
    output_language: str,
) -> dict[SectionLayer, str]:
    layer_blocks: dict[SectionLayer, list[str]] = {
        "core": [],
        "support": [],
        "audit": [],
    }
    if set(section_markdown_by_key) == {"final_report"}:
        return _split_markdown_by_layers(
            section_markdown_by_key["final_report"],
            output_language=output_language,
        )

    for key in _ordered_section_keys(section_markdown_by_key):
        markdown = (section_markdown_by_key.get(key) or "").strip()
        if not markdown:
            continue
        if not build_report_section_index(markdown).sections:
            layer_blocks[_layer_for_section_key(key)].append(markdown)
            continue
        split = _split_markdown_by_layers(markdown, output_language=output_language)
        for layer, layer_markdown in split.items():
            if layer_markdown:
                layer_blocks[layer].append(layer_markdown)

    return {
        layer: _join_markdown(blocks) for layer, blocks in layer_blocks.items()
    }


def _split_markdown_by_layers(
    markdown: str,
    *,
    output_language: str,
) -> dict[SectionLayer, str]:
    stripped = markdown.strip()
    layer_blocks: dict[SectionLayer, list[str]] = {
        "core": [],
        "support": [],
        "audit": [],
    }
    if not stripped:
        return {layer: "" for layer in layer_blocks}

    index = build_report_section_index(stripped)
    if not index.sections:
        layer_blocks["core"].append(stripped)
        return {
            layer: _join_markdown(blocks) for layer, blocks in layer_blocks.items()
        }

    first_section = index.sections[0]
    preamble = stripped[: first_section.start].strip()
    if preamble:
        layer_blocks["core"].append(preamble)
    for section in index.sections:
        block = stripped[section.start : section.end].strip()
        if not block:
            continue
        layer_blocks[_section_layer(section, output_language=output_language)].append(
            block
        )
    return {layer: _join_markdown(blocks) for layer, blocks in layer_blocks.items()}


def _section_layer(section: ReportSection, *, output_language: str) -> SectionLayer:
    if section.layer == "audit":
        return "audit"
    if section.section_key:
        return _layer_for_section_key(section.section_key)
    heading_key = heading_key_for(section.heading, output_language)
    if heading_key:
        return _layer_for_section_key(heading_key)
    return section.layer


def _layer_for_section_key(section_key: str) -> SectionLayer:
    if section_key in SUPPORT_HEADING_KEYS:
        return "support"
    if section_key.startswith("audit_") or section_key in {"audit_log"}:
        return "audit"
    if section_key in CORE_HEADING_KEYS:
        return "core"
    return "core"


def _ordered_section_keys(section_markdown_by_key: Mapping[str, str]) -> list[str]:
    ordered_keys = [
        key for key in CANONICAL_REPORT_ORDER if key in section_markdown_by_key
    ]
    ordered_keys.extend(
        sorted(key for key in section_markdown_by_key if key not in ordered_keys)
    )
    return ordered_keys


def _layer_sections(
    markdown: str,
    *,
    briefs: Mapping[str, SectionBrief],
    output_language: str,
) -> list[ReportLayerSection]:
    sections: list[ReportLayerSection] = []
    for index, section in enumerate(
        build_report_section_index(markdown).sections,
        start=1,
    ):
        section_key = (
            section.section_key
            or heading_key_for(section.heading, output_language)
            or f"section_{index}"
        )
        brief = briefs.get(section_key)
        sections.append(
            ReportLayerSection(
                section_key=section_key,
                heading=section.heading,
                start_line=section.line_start,
                end_line=section.line_end,
                source_ids=list(brief.allowed_source_ids) if brief else [],
                claim_card_ids=list(brief.allowed_claim_card_ids) if brief else [],
                decision_card_ids=list(brief.allowed_decision_card_ids)
                if brief
                else [],
            )
        )
    return sections


def _brief_by_key(briefs: Sequence[SectionBrief]) -> dict[str, SectionBrief]:
    return {brief.section_key: brief for brief in briefs}


def _join_markdown(markdowns: Sequence[str]) -> str:
    return "\n\n".join(markdown for markdown in markdowns if markdown).strip()


__all__ = ["assemble_report_artifact_v2"]
