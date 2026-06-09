from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from packages.business_intel.source_reconciliation import normalize_source_token, source_tokens
from packages.research.evidence.strength import (
    EvidenceStrengthDecision,
    classify_evidence_strength,
    evidence_can_support_strong_report_section,
)

ReportSectionPolicy = Literal[
    "strong_conclusion",
    "factual_comparison",
    "qualitative_signal",
    "audit_appendix",
]

SOURCE_TOKEN_RE = re.compile(r"\[source:[^\]]+\]")
STRONG_CONCLUSION_RE = re.compile(
    r"\b("
    r"overall confidence|winner|leading option|best option|safer|safest|"
    r"recommended|recommendation|executive recommendation|executive summary|"
    r"dimension winner|soc\s*2|iso\s*/?\s*iec|ip indemnity|sso|saml|scim|"
    r"audit log|pricing transparency"
    r")\b",
    flags=re.IGNORECASE,
)
QUALITATIVE_SECTION_RE = re.compile(
    r"\b(caveat|risk|persona|user research|buyer research|validation plan|"
    r"verification plan|evidence gap|limitations?)\b",
    flags=re.IGNORECASE,
)
APPENDIX_SECTION_RE = re.compile(
    r"\b(appendix|source quality|source coverage|release gate|qa|claim validation)\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ReportCitationPolicyViolation:
    rule_id: str
    rule_name: str
    severity: Literal["warn", "blocker"]
    line_number: int
    section_heading: str
    section_policy: ReportSectionPolicy
    line: str
    evidence_ids: list[str]
    source_strengths: dict[str, EvidenceStrengthDecision]
    message: str
    recommendation: str


@dataclass(frozen=True)
class ReportCitationPolicyRepairResult:
    report_md: str
    changed: bool
    repaired_line_count: int
    violations: list[ReportCitationPolicyViolation]

    def metadata(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "repaired_line_count": self.repaired_line_count,
            "violation_count": len(self.violations),
            "violations": [
                {
                    "rule_id": item.rule_id,
                    "severity": item.severity,
                    "line_number": item.line_number,
                    "section_heading": item.section_heading,
                    "section_policy": item.section_policy,
                    "evidence_ids": item.evidence_ids,
                    "message": item.message,
                    "recommendation": item.recommendation,
                }
                for item in self.violations
            ],
        }


def writer_report_citation_policy_text() -> str:
    return (
        "Citation policy: Overall Confidence, Executive Recommendation, winner, "
        "procurement, pricing, security, or other strong conclusion lines may cite only "
        "high-confidence verified webpage or official evidence. Interview, survey, manual, "
        "synthetic, or low-confidence sources may appear only in caveat, risk, user-research, "
        "validation-plan, or appendix sections and must be described as qualitative signals."
    )


def report_citation_policy_violations(
    report_md: str,
    evidence: list[object],
) -> list[ReportCitationPolicyViolation]:
    evidence_by_token = _evidence_by_source_token(evidence)
    violations: list[ReportCitationPolicyViolation] = []
    section_heading = ""
    for line_number, line in enumerate(report_md.splitlines(), start=1):
        heading = _heading_text(line)
        if heading is not None:
            section_heading = heading
            continue
        section_policy = report_section_policy(section_heading, line)
        if section_policy != "strong_conclusion":
            continue
        cited = _cited_evidence(line, evidence_by_token)
        weak = {
            token: item
            for token, item in cited.items()
            if not evidence_can_support_strong_report_section(item)
        }
        if not weak:
            continue
        decisions = {
            _evidence_id(item): classify_evidence_strength(item) for item in weak.values()
        }
        evidence_ids = list(decisions)
        violations.append(
            ReportCitationPolicyViolation(
                rule_id="strong_conclusion_uses_weak_source",
                rule_name="Strong conclusion source quality",
                severity="blocker",
                line_number=line_number,
                section_heading=section_heading,
                section_policy=section_policy,
                line=line.strip(),
                evidence_ids=evidence_ids,
                source_strengths=decisions,
                message=(
                    "A strong report conclusion cites evidence that cannot support strong "
                    f"report language. Line: {line.strip()[:220]}"
                ),
                recommendation=(
                    "Rewrite the line as a caveat or replace the citation with high-confidence "
                    "verified webpage or official evidence."
                ),
            )
        )
    return violations


def repair_report_citation_policy(
    report_md: str,
    evidence: list[object],
) -> ReportCitationPolicyRepairResult:
    violations = report_citation_policy_violations(report_md, evidence)
    if not violations:
        return ReportCitationPolicyRepairResult(
            report_md=report_md,
            changed=False,
            repaired_line_count=0,
            violations=[],
        )
    violation_lines = {item.line_number: item for item in violations}
    repaired_lines: list[str] = []
    repaired_line_count = 0
    for line_number, line in enumerate(report_md.splitlines(), start=1):
        violation = violation_lines.get(line_number)
        if violation is None:
            repaired_lines.append(line)
            continue
        repaired_lines.append(_repair_strong_conclusion_line(line, evidence))
        repaired_line_count += 1
    repaired = "\n".join(repaired_lines)
    return ReportCitationPolicyRepairResult(
        report_md=repaired,
        changed=repaired != report_md,
        repaired_line_count=repaired_line_count,
        violations=violations,
    )


def report_section_policy(section_heading: str, line: str) -> ReportSectionPolicy:
    line_text = line.strip()
    if not line_text:
        return "audit_appendix"
    combined = f"{section_heading} {line_text}"
    if APPENDIX_SECTION_RE.search(section_heading):
        return "audit_appendix"
    if QUALITATIVE_SECTION_RE.search(combined) and not _line_is_overall_confidence(line_text):
        return "qualitative_signal"
    if STRONG_CONCLUSION_RE.search(combined):
        return "strong_conclusion"
    if _line_mentions_factual_axis(combined):
        return "factual_comparison"
    return "audit_appendix"


def source_ids_for_report_line_policy(
    evidence: list[object],
    *,
    require_strong_support: bool,
    limit: int = 4,
) -> list[str]:
    source_ids: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        if require_strong_support and not evidence_can_support_strong_report_section(item):
            continue
        source_id = _report_source_id(item)
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        source_ids.append(source_id)
        if len(source_ids) >= limit:
            break
    return source_ids


def is_strong_report_line(line: str, section_heading: str = "") -> bool:
    return report_section_policy(section_heading, line) == "strong_conclusion"


def _repair_strong_conclusion_line(line: str, evidence: list[object]) -> str:
    allowed_ids = source_ids_for_report_line_policy(
        evidence,
        require_strong_support=True,
        limit=2,
    )
    without_tokens = SOURCE_TOKEN_RE.sub("", line).rstrip()
    downgraded = _downgrade_strong_language(without_tokens)
    if not allowed_ids:
        return (
            f"{downgraded} No high-confidence verified citation is currently attached; "
            "keep this as a draft caveat until stronger evidence is collected."
        )
    refs = " ".join(f"[source:{source_id}]" for source_id in allowed_ids)
    return f"{downgraded} {refs}".rstrip()


def _downgrade_strong_language(line: str) -> str:
    stripped = line.strip()
    if _line_is_overall_confidence(stripped):
        _, _, remainder = stripped.partition("|")
        caveat = remainder.strip() or stripped
        caveat = re.sub(r"^Caveat:\s*", "", caveat, flags=re.IGNORECASE)
        return f"Evidence caveat: {caveat}"
    replacements = [
        (r"\brecommended\b", "tentatively suggested"),
        (r"\brecommendation\b", "draft recommendation"),
        (r"\bwinner\b", "current evidence leader"),
        (r"\bleading option\b", "current evidence leader"),
        (r"\bbest option\b", "current evidence leader"),
        (r"\bsafer\b", "lower-observed-risk"),
        (r"\bsafest\b", "lowest-observed-risk"),
    ]
    downgraded = stripped
    for pattern, replacement in replacements:
        downgraded = re.sub(pattern, replacement, downgraded, flags=re.IGNORECASE)
    if downgraded == stripped:
        return f"Draft caveat: {stripped}"
    return downgraded


def _cited_evidence(
    line: str,
    evidence_by_token: dict[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for token in source_tokens(line):
        normalized = normalize_source_token(token)
        item = evidence_by_token.get(normalized)
        if item is not None:
            result[normalized] = item
    return result


def _evidence_by_source_token(evidence: list[object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in evidence:
        for token in _source_tokens_for_evidence(item):
            result[normalize_source_token(token)] = item
    return result


def _source_tokens_for_evidence(evidence: object) -> list[str]:
    values = [
        _string_attr(evidence, "id"),
        _string_attr(evidence, "raw_source_id"),
    ]
    metadata = getattr(evidence, "metadata", {})
    if isinstance(metadata, dict):
        values.extend(
            str(metadata.get(key) or "")
            for key in ("raw_source_id", "source_id", "canonical_source_id")
        )
    return [value for value in values if value.strip()]


def _evidence_id(evidence: object) -> str:
    return _string_attr(evidence, "id") or _string_attr(evidence, "raw_source_id")


def _report_source_id(evidence: object) -> str:
    return _string_attr(evidence, "raw_source_id") or _string_attr(evidence, "id")


def _heading_text(line: str) -> str | None:
    match = re.match(r"^\s*#{1,4}\s+(.+?)\s*$", line)
    return match.group(1).strip() if match else None


def _line_is_overall_confidence(line: str) -> bool:
    return line.strip().casefold().startswith("overall confidence")


def _line_mentions_factual_axis(value: str) -> bool:
    return bool(re.search(r"\b(pricing|price|feature|capability|tier|plan)\b", value, re.I))


def _string_attr(value: object, name: str) -> str:
    return str(getattr(value, name, "") or "").strip()
