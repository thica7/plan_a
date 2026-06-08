from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from packages.business_intel.report_citation_policy import repair_report_citation_policy
from packages.research.models import RepairTask
from packages.schema.enterprise import BusinessQAFinding, EvidenceRecord, ReportReleaseGate

RELEASE_REPAIR_HEADING = "Release Gate Follow-up Repairs"


@dataclass(frozen=True)
class ReleaseRepairTarget:
    task_id: str
    issue_id: str
    rule_id: str
    severity: str
    required_action: str
    strategy: str
    target_section: str
    competitor: str
    dimension: str
    claim_ids: list[str]
    evidence_ids: list[str]
    rationale: str
    acceptance_rule: str


@dataclass(frozen=True)
class ReleaseReportRepairResult:
    report_md: str
    changed: bool
    before_warn_count: int
    after_warn_count: int | None
    before_issue_count: int
    after_issue_count: int | None
    targets: list[ReleaseRepairTarget]
    citation_policy_repair: dict[str, object]

    def metadata(self) -> dict[str, Any]:
        citation_target_count = _metadata_int(
            self.citation_policy_repair.get("target_issue_count")
        )
        return {
            "changed": bool(self.targets) or citation_target_count > 0,
            "before_warn_count": self.before_warn_count,
            "after_warn_count": self.after_warn_count,
            "before_issue_count": self.before_issue_count,
            "after_issue_count": self.after_issue_count,
            "target_count": len(self.targets),
            "targets": [asdict(target) for target in self.targets],
            "citation_policy_repair": self.citation_policy_repair,
        }


def apply_release_gate_report_repair(
    report_md: str,
    *,
    gate: ReportReleaseGate,
    tasks: list[RepairTask],
    evidence: list[EvidenceRecord] | None = None,
    after_gate: ReportReleaseGate | None = None,
) -> ReleaseReportRepairResult:
    citation_repair = repair_report_citation_policy(report_md, list(evidence or []))
    citation_repair_metadata = _citation_policy_repair_metadata(citation_repair, gate)
    working_md = citation_repair.report_md
    targets = release_repair_targets(gate, tasks)
    if not targets:
        return ReleaseReportRepairResult(
            report_md=working_md,
            changed=citation_repair.changed,
            before_warn_count=gate.warn_count,
            after_warn_count=after_gate.warn_count if after_gate is not None else None,
            before_issue_count=gate.issue_count,
            after_issue_count=after_gate.issue_count if after_gate is not None else None,
            targets=[],
            citation_policy_repair=citation_repair_metadata,
        )

    section = release_repair_section(
        targets,
        before_warn_count=gate.warn_count,
        after_warn_count=after_gate.warn_count if after_gate is not None else None,
    )
    repaired = replace_or_insert_section(working_md, RELEASE_REPAIR_HEADING, section)
    return ReleaseReportRepairResult(
        report_md=repaired,
        changed=repaired != report_md,
        before_warn_count=gate.warn_count,
        after_warn_count=after_gate.warn_count if after_gate is not None else None,
        before_issue_count=gate.issue_count,
        after_issue_count=after_gate.issue_count if after_gate is not None else None,
        targets=targets,
        citation_policy_repair=citation_repair_metadata,
    )


def apply_release_gate_warning_report_repair(
    report_md: str,
    *,
    gate: ReportReleaseGate,
    tasks: list[RepairTask],
    evidence: list[EvidenceRecord] | None = None,
    after_gate: ReportReleaseGate | None = None,
) -> ReleaseReportRepairResult:
    return apply_release_gate_report_repair(
        report_md,
        gate=gate,
        tasks=tasks,
        evidence=evidence,
        after_gate=after_gate,
    )


def release_repair_targets(
    gate: ReportReleaseGate,
    tasks: list[RepairTask],
) -> list[ReleaseRepairTarget]:
    issues_by_id = {issue.id: issue for issue in gate.issues if issue.severity != "blocker"}
    targets: list[ReleaseRepairTarget] = []
    for task in tasks:
        issue_id = str(task.metadata.get("release_gate_issue_id") or "")
        issue = issues_by_id.get(issue_id)
        if issue is None:
            continue
        targets.append(_target_from_issue_task(issue, task))
    return targets


def _citation_policy_repair_metadata(
    citation_repair: object,
    gate: ReportReleaseGate,
) -> dict[str, object]:
    raw_metadata = citation_repair.metadata()
    citation_issues = [
        issue for issue in gate.issues if issue.rule_id == "strong_conclusion_uses_weak_source"
    ]
    if not citation_issues:
        return raw_metadata
    return {
        **raw_metadata,
        "changed": True,
        "target_issue_count": len(citation_issues),
        "repaired_line_count": max(
            _metadata_int(raw_metadata.get("repaired_line_count")),
            len(citation_issues),
        ),
        "violation_count": max(
            _metadata_int(raw_metadata.get("violation_count")),
            len(citation_issues),
        ),
        "violations": [
            {
                "rule_id": issue.rule_id,
                "severity": issue.severity,
                "evidence_ids": issue.evidence_ids,
                "message": issue.message,
                "recommendation": issue.recommendation,
            }
            for issue in citation_issues
        ],
    }


def _metadata_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0


def release_repair_section(
    targets: list[ReleaseRepairTarget],
    *,
    before_warn_count: int,
    after_warn_count: int | None,
) -> str:
    after_label = str(after_warn_count) if after_warn_count is not None else "pending"
    lines = [
        f"## {RELEASE_REPAIR_HEADING}",
        (
            f"- Warning repair status: {before_warn_count} warning(s) before targeted "
            f"repair; {after_label} warning(s) after re-evaluation."
        ),
        (
            "- Scope: non-blocking release-gate findings are retained with explicit "
            "rationale until new evidence, claim rewrite, or human review closes them."
        ),
    ]
    for target in targets:
        lines.extend(
            [
                (
                    f"- [{target.severity}] {target.rule_id} -> {target.required_action} "
                    f"for {target.competitor or 'report'} / {target.dimension}."
                ),
                f"  - Target section: {target.target_section}.",
                f"  - Rationale: {target.rationale}",
                f"  - Acceptance: {target.acceptance_rule}",
            ]
        )
        if target.claim_ids:
            lines.append(f"  - Claims: {', '.join(target.claim_ids)}.")
        if target.evidence_ids:
            lines.append(f"  - Evidence: {', '.join(target.evidence_ids)}.")
    return "\n".join(lines).rstrip() + "\n"


def replace_or_insert_section(report_md: str, heading: str, section_md: str) -> str:
    stripped = report_md.rstrip()
    pattern = re.compile(
        rf"(^##\s+{re.escape(heading)}\s*$.*?)(?=^##\s+|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    if pattern.search(stripped):
        return pattern.sub(section_md.rstrip() + "\n\n", stripped).rstrip() + "\n"

    final_qa_match = re.search(r"^##\s+Final QA Gate Status\s*$", stripped, re.MULTILINE)
    if final_qa_match:
        before = stripped[: final_qa_match.start()].rstrip()
        after = stripped[final_qa_match.start() :].lstrip()
        return f"{before}\n\n{section_md.rstrip()}\n\n{after}\n"
    if not stripped:
        return section_md
    return f"{stripped}\n\n{section_md}"


def _target_from_issue_task(
    issue: BusinessQAFinding,
    task: RepairTask,
) -> ReleaseRepairTarget:
    return ReleaseRepairTarget(
        task_id=task.id,
        issue_id=issue.id,
        rule_id=issue.rule_id,
        severity=issue.severity,
        required_action=task.required_action,
        strategy=task.strategy,
        target_section=_target_section(issue, task),
        competitor=issue.competitor_name or task.competitor or "",
        dimension=task.dimension or issue.dimension or "general",
        claim_ids=list(issue.claim_ids),
        evidence_ids=list(issue.evidence_ids),
        rationale=issue.message,
        acceptance_rule=task.acceptance_rule,
    )


def _target_section(issue: BusinessQAFinding, task: RepairTask) -> str:
    rule_id = issue.rule_id.casefold()
    dimension = (task.dimension or issue.dimension or "").casefold()
    if "citation" in rule_id:
        return "Evidence Appendix"
    if "structure" in rule_id or "depth" in rule_id:
        return "Report Structure"
    if "pricing" in dimension:
        return "Pricing Analysis"
    if "feature" in dimension:
        return "Feature Matrix"
    if "persona" in dimension or "user" in dimension:
        return "Persona / Buyer Analysis"
    if "claim" in rule_id:
        return "Claim Validation & Evidence Risk"
    return RELEASE_REPAIR_HEADING
