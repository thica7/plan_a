from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from packages.i18n.language import repair_mojibake_text

SectionLayer = Literal["core", "support", "audit"]


@dataclass(frozen=True)
class ReportSection:
    heading: str
    normalized_heading: str
    level: int
    start: int
    end: int
    line_start: int
    line_end: int
    body: str
    layer: SectionLayer
    section_key: str | None = None


@dataclass(frozen=True)
class ReportSectionIndex:
    markdown: str
    sections: tuple[ReportSection, ...]

    def sections_before_support(self) -> tuple[ReportSection, ...]:
        first_support = next(
            (section for section in self.sections if section.layer in {"support", "audit"}),
            None,
        )
        if first_support is None:
            return self.sections
        return tuple(section for section in self.sections if section.start < first_support.start)

    def section_for_line(self, line_number: int) -> ReportSection | None:
        return next(
            (
                section
                for section in self.sections
                if section.line_start <= line_number <= section.line_end
            ),
            None,
        )

    def is_support_or_audit_line(self, line_number: int) -> bool:
        section = self.section_for_line(line_number)
        return section is not None and section.layer in {"support", "audit"}


@dataclass(frozen=True)
class ReportSectionMarker:
    section_key: str | None
    layer: SectionLayer | None


@dataclass(frozen=True)
class _ReportSectionEntry:
    heading_match: re.Match[str]
    marker: ReportSectionMarker | None
    start: int


def build_report_section_index(markdown: str) -> ReportSectionIndex:
    report_md = repair_mojibake_text(markdown or "")
    heading_matches = list(
        re.finditer(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", report_md, flags=re.MULTILINE)
    )
    entries = [
        _section_entry_for_heading(report_md, match) for match in heading_matches
    ]
    sections: list[ReportSection] = []
    sticky_support = False
    for index, entry in enumerate(entries):
        match = entry.heading_match
        heading = clean_heading(match.group(2))
        normalized = normalize_heading(heading)
        level = len(match.group(1))
        body_start = match.end()
        body_end = entries[index + 1].start if index + 1 < len(entries) else len(report_md)
        marker = entry.marker
        if marker is not None and marker.layer is not None:
            layer = marker.layer
            sticky_support = layer in {"support", "audit"}
        else:
            layer = classify_section_layer(normalized, sticky_support=sticky_support)
        if marker is None and is_support_layer_heading(normalized):
            sticky_support = True
            layer = "audit"
        sections.append(
            ReportSection(
                heading=heading,
                normalized_heading=normalized,
                level=level,
                start=entry.start,
                end=body_end,
                line_start=_line_number_at(report_md, entry.start),
                line_end=_line_number_at(report_md, max(body_end - 1, entry.start)),
                body=report_md[body_start:body_end].strip(),
                layer=layer,
                section_key=marker.section_key if marker is not None else None,
            )
        )
    return ReportSectionIndex(markdown=report_md, sections=tuple(sections))


def report_section_marker(section_key: str, layer: SectionLayer) -> str:
    safe_key = re.sub(r"[^a-z0-9_:-]", "", section_key.casefold())
    return f"<!-- report-section:key={safe_key} layer={layer} -->"


def _section_entry_for_heading(
    markdown: str,
    heading_match: re.Match[str],
) -> _ReportSectionEntry:
    marker_start, marker = _marker_before_heading(markdown, heading_match.start())
    return _ReportSectionEntry(
        heading_match=heading_match,
        marker=marker,
        start=marker_start if marker is not None else heading_match.start(),
    )


def _marker_before_heading(
    markdown: str,
    heading_start: int,
) -> tuple[int, ReportSectionMarker | None]:
    marker_line_end = heading_start
    if marker_line_end > 0 and markdown[marker_line_end - 1] == "\n":
        marker_line_end -= 1
    marker_line_start = markdown.rfind("\n", 0, marker_line_end) + 1
    marker_line = markdown[marker_line_start:marker_line_end].strip()
    marker = parse_report_section_marker(marker_line)
    if marker is None:
        return heading_start, None
    return marker_line_start, marker


def parse_report_section_marker(line: str) -> ReportSectionMarker | None:
    match = re.fullmatch(r"<!--\s*report-section:([^>]*)-->", line.strip())
    if match is None:
        return None
    attrs = {
        key.casefold(): value
        for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)=([A-Za-z0-9_:-]+)", match.group(1))
    }
    layer_text = attrs.get("layer")
    layer: SectionLayer | None = None
    if layer_text == "core":
        layer = "core"
    elif layer_text == "support":
        layer = "support"
    elif layer_text == "audit":
        layer = "audit"
    section_key = attrs.get("key")
    if section_key is not None:
        section_key = re.sub(r"[^a-z0-9_:-]", "", section_key.casefold()) or None
    if section_key is None and layer is None:
        return None
    return ReportSectionMarker(section_key=section_key, layer=layer)


def clean_heading(heading: str) -> str:
    return re.sub(r"\s+", " ", heading.strip().strip("#").strip())


def normalize_heading(heading: str) -> str:
    cleaned = clean_heading(heading)
    cleaned = re.sub(
        r"^(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\.)]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.casefold()


def classify_section_layer(
    normalized_heading: str,
    *,
    sticky_support: bool = False,
) -> SectionLayer:
    if sticky_support:
        return "audit"
    if _contains_any(normalized_heading, AUDIT_HEADING_NEEDLES):
        return "audit"
    if _contains_any(normalized_heading, SUPPORT_HEADING_NEEDLES):
        return "support"
    return "core"


def is_support_layer_heading(normalized_heading: str) -> bool:
    return _contains_any(normalized_heading, SUPPORT_LAYER_NEEDLES)


def _line_number_at(markdown: str, offset: int) -> int:
    return markdown.count("\n", 0, offset) + 1


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    compact_value = re.sub(r"\s+", "", value)
    return any(needle in value or re.sub(r"\s+", "", needle) in compact_value for needle in needles)


SUPPORT_LAYER_NEEDLES = (
    "support layer",
    "audit layer",
    "support / audit",
    "support and audit",
    "supporting evidence and qa",
    "支撑材料",
    "支持/审计",
    "支持层",
    "审计层",
    "支撑层",
)

SUPPORT_HEADING_NEEDLES = (
    "rag gap fill",
    "evidence gap fill",
    "retrieval",
    "source quality",
    "source coverage",
    "source appendix",
    "evidence appendix",
    "evidence support",
    "knowledge coverage",
    "confidence notes",
    "memory context",
    "user research evidence",
    "next collection",
    "verification plan",
    "buyer research",
    "支撑材料",
    "证据与 qa 支撑",
    "证据与qa支撑",
    "rag 缺口补全",
    "rag缺口补全",
    "证据缺口补全",
    "证据附录",
    "来源附录",
    "来源质量",
    "证据支撑",
    "知识覆盖",
    "置信度说明",
    "下一步采集",
    "建议检索",
    "rag 缂哄彛琛ュ叏",
    "璇佹嵁缂哄彛琛ュ叏",
    "璇佹嵁闄勫綍",
    "鏉ユ簮闄勫綍",
)

AUDIT_HEADING_NEEDLES = (
    "final qa gate status",
    "qa gate",
    "release gate",
    "follow-up repairs",
    "follow up repairs",
    "repair",
    "generation notes",
    "claim validation",
    "claim risk",
    "evidence risk",
    "scenario qa",
    "scenario checklist",
    "qa status",
    "final qa",
    "声明校验",
    "证据风险",
    "声明校验与证据风险",
    "场景 qa",
    "场景qa",
    "场景 qa 清单",
    "场景qa清单",
    "场景清单",
    "最终 qa",
    "最终qa",
    "修复记录",
    "发布门禁",
    "生成说明",
    "澹版槑鏍￠獙",
    "璇佹嵁椋庨櫓",
    "鍦烘櫙 qa",
    "鍦烘櫙娓呭崟",
)
