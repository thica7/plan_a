from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from packages.schema.models import QCIssue


@dataclass(frozen=True)
class FinalQualityResult:
    findings: list[QCIssue]
    blocker_count: int
    warn_count: int
    issue_count: int
    quality_status: str
    readiness_score: int | None
    revision_issue_count_after: int
    revision_convergence_ratio: float

    def telemetry_payload(self) -> dict[str, object]:
        return {
            "blocker_count": self.blocker_count,
            "warn_count": self.warn_count,
            "issue_count": self.issue_count,
            "quality_status": self.quality_status,
            "readiness_score": self.readiness_score,
            "revision_issue_count_after": self.revision_issue_count_after,
            "revision_convergence_ratio": self.revision_convergence_ratio,
        }


def build_final_quality_result(
    *,
    deterministic_findings: Sequence[QCIssue],
    release_gate_findings: Sequence[QCIssue],
    readiness_score: int | None,
    issue_count_before: int = 0,
) -> FinalQualityResult:
    findings = _dedupe_findings([*deterministic_findings, *release_gate_findings])
    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    warn_count = sum(1 for finding in findings if finding.severity == "warn")
    issue_count = len(findings)
    if blocker_count:
        quality_status = "completed_with_blockers"
    elif warn_count:
        quality_status = "completed_with_warnings"
    else:
        quality_status = "clean_pass"
    return FinalQualityResult(
        findings=findings,
        blocker_count=blocker_count,
        warn_count=warn_count,
        issue_count=issue_count,
        quality_status=quality_status,
        readiness_score=readiness_score,
        revision_issue_count_after=issue_count,
        revision_convergence_ratio=round(issue_count / max(1, issue_count_before), 3),
    )


def _dedupe_findings(findings: list[QCIssue]) -> list[QCIssue]:
    seen: set[str] = set()
    deduped: list[QCIssue] = []
    for finding in findings:
        if finding.id in seen:
            continue
        seen.add(finding.id)
        deduped.append(finding)
    return deduped
