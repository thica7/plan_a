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


def build_report_section_index(markdown: str) -> ReportSectionIndex:
    report_md = repair_mojibake_text(markdown or "")
    matches = list(
        re.finditer(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", report_md, flags=re.MULTILINE)
    )
    sections: list[ReportSection] = []
    sticky_support = False
    for index, match in enumerate(matches):
        heading = clean_heading(match.group(2))
        normalized = normalize_heading(heading)
        level = len(match.group(1))
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(report_md)
        layer = classify_section_layer(normalized, sticky_support=sticky_support)
        if is_support_layer_heading(normalized):
            sticky_support = True
            layer = "audit"
        sections.append(
            ReportSection(
                heading=heading,
                normalized_heading=normalized,
                level=level,
                start=match.start(),
                end=body_end,
                line_start=_line_number_at(report_md, match.start()),
                line_end=_line_number_at(report_md, max(body_end - 1, match.start())),
                body=report_md[body_start:body_end].strip(),
                layer=layer,
            )
        )
    return ReportSectionIndex(markdown=report_md, sections=tuple(sections))


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
    "场景 qa",
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
