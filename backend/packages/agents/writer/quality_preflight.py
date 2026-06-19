from __future__ import annotations

import re
from dataclasses import dataclass

from packages.agents.writer.segment_contract import (
    CORE_HEADING_KEYS,
    SUPPORT_HEADING_KEYS,
    heading_key_for,
)
from packages.schema.api_dto import RunDetail

REQUIRED_CORE_KEYS: tuple[str, ...] = (
    "decision_summary",
    "competitive_findings",
    "review_theme_summary",
    "competitor_deep_dives",
    "side_by_side_matrix",
    "swot_analysis",
)

_H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)
_LEADING_HEADING_DECORATION_RE = re.compile(
    r"^(?:"
    r"[-*+\u2022]\s+|"
    r"(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\.)]\s+|"
    r"(?:section\s+)?[\(\[\uff08\u3010]\s*"
    r"(?:\d+(?:\.\d+)*|[ivxlcdm]+|[\u4e00\u4e8c\u4e09\u56db"
    r"\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343]+)"
    r"\s*[\)\]\uff09\u3011]\s*|"
    r"(?:\u7b2c\s*)?[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03"
    r"\u516b\u4e5d\u5341\u767e\u5343]+[\u3001.\uff0e)]\s*"
    r")",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class WriterQualityPreflightResult:
    passed: bool
    failure_reasons: list[str]
    duplicate_section_count: int
    missing_core_sections: list[str]
    core_sections_after_support: list[str]
    first_support_key: str | None
    h2_keys: list[str]

    def telemetry_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failure_reasons": list(self.failure_reasons),
            "duplicate_section_count": self.duplicate_section_count,
            "missing_core_sections": list(self.missing_core_sections),
            "core_sections_after_support": list(self.core_sections_after_support),
            "first_support_key": self.first_support_key,
            "h2_keys": list(self.h2_keys),
        }


def run_writer_quality_preflight(
    detail: RunDetail,
    markdown: str,
) -> WriterQualityPreflightResult:
    h2_headings = [match.group(1).strip() for match in _H2_RE.finditer(markdown)]
    h2_keys: list[str] = []
    h2_identities: list[str] = []
    for heading in h2_headings:
        key = heading_key_for(heading, detail.output_language)
        if key is None:
            h2_identities.append(f"unknown:{_normalize_unknown_heading(heading)}")
            continue
        h2_keys.append(key)
        h2_identities.append(f"known:{key}")

    first_support_index = next(
        (index for index, key in enumerate(h2_keys) if key in SUPPORT_HEADING_KEYS),
        None,
    )
    first_support_key = (
        h2_keys[first_support_index] if first_support_index is not None else None
    )
    if first_support_index is None:
        before_support_keys = h2_keys
        after_support_keys: list[str] = []
    else:
        before_support_keys = h2_keys[:first_support_index]
        after_support_keys = h2_keys[first_support_index + 1 :]

    duplicate_section_count = _duplicate_identity_count(h2_identities)
    missing_core_sections = [
        key for key in REQUIRED_CORE_KEYS if key not in before_support_keys
    ]
    core_sections_after_support = [
        key for key in after_support_keys if key in CORE_HEADING_KEYS
    ]

    failure_reasons: list[str] = []
    if duplicate_section_count:
        failure_reasons.append("duplicate_sections")
    if missing_core_sections:
        failure_reasons.append("missing_core_sections")
    if core_sections_after_support:
        failure_reasons.append("core_sections_after_support")

    return WriterQualityPreflightResult(
        passed=not failure_reasons,
        failure_reasons=failure_reasons,
        duplicate_section_count=duplicate_section_count,
        missing_core_sections=missing_core_sections,
        core_sections_after_support=core_sections_after_support,
        first_support_key=first_support_key,
        h2_keys=h2_keys,
    )


def _duplicate_identity_count(h2_identities: list[str]) -> int:
    counts: dict[str, int] = {}
    for identity in h2_identities:
        counts[identity] = counts.get(identity, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _normalize_unknown_heading(heading: str) -> str:
    cleaned = heading.strip().translate(_DASH_TRANSLATION)
    cleaned = re.sub(r"\s+#+$", "", cleaned).strip()
    cleaned = _strip_leading_heading_decoration(cleaned)
    return " ".join(cleaned.casefold().split())


def _strip_leading_heading_decoration(heading: str) -> str:
    cleaned = heading.strip()
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _LEADING_HEADING_DECORATION_RE.sub("", cleaned).strip()
    return cleaned
