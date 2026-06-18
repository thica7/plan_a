from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from packages.research.models import RepairTask
from packages.schema.enterprise import BusinessQAFinding, ReportReleaseGate

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

    def metadata(self) -> dict[str, Any]:
        return {
            "changed": self.changed or bool(self.targets) or self.before_issue_count > 0,
            "before_warn_count": self.before_warn_count,
            "after_warn_count": self.after_warn_count,
            "before_issue_count": self.before_issue_count,
            "after_issue_count": self.after_issue_count,
            "target_count": len(self.targets),
            "targets": [asdict(target) for target in self.targets],
        }


def apply_release_gate_warning_report_repair(
    report_md: str,
    *,
    gate: ReportReleaseGate,
    tasks: list[RepairTask],
    after_gate: ReportReleaseGate | None = None,
) -> ReleaseReportRepairResult:
    targets = release_repair_targets(gate, tasks)
    should_record_status = not gate.allowed or bool(targets)
    if not should_record_status:
        return ReleaseReportRepairResult(
            report_md=report_md,
            changed=False,
            before_warn_count=gate.warn_count,
            after_warn_count=after_gate.warn_count if after_gate is not None else None,
            before_issue_count=gate.issue_count,
            after_issue_count=after_gate.issue_count if after_gate is not None else None,
            targets=[],
        )

    repaired = remove_release_repair_section(report_md)
    return ReleaseReportRepairResult(
        report_md=repaired,
        changed=repaired != report_md,
        before_warn_count=gate.warn_count,
        after_warn_count=after_gate.warn_count if after_gate is not None else None,
        before_issue_count=gate.issue_count,
        after_issue_count=after_gate.issue_count if after_gate is not None else None,
        targets=targets,
    )


def remove_release_repair_section(report_md: str) -> str:
    stripped = report_md.rstrip()
    pattern = re.compile(
        rf"(^##\s+{re.escape(RELEASE_REPAIR_HEADING)}\s*$.*?)(?=^##\s+|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("", stripped).rstrip()


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


def release_repair_section(
    targets: list[ReleaseRepairTarget],
    *,
    gate: ReportReleaseGate,
    before_warn_count: int,
    after_warn_count: int | None,
    after_issue_count: int | None,
) -> str:
    after_label = str(after_warn_count) if after_warn_count is not None else str(gate.warn_count)
    after_issue_label = (
        str(after_issue_count) if after_issue_count is not None else str(gate.issue_count)
    )
    rule_counts = _issue_rule_counts(gate.issues)
    section_counts = Counter(target.target_section for target in targets)
    action_counts = Counter(target.required_action for target in targets)
    lines = [
        f"## {RELEASE_REPAIR_HEADING}",
        (
            f"- Release gate status: {gate.status}; {gate.blocker_count} blocker(s), "
            f"{gate.warn_count} warning(s), {gate.issue_count} total issue(s)."
        ),
        (
            f"- Warning repair status: {before_warn_count} warning(s) before targeted "
            f"repair; {after_label} warning(s) after re-evaluation."
        ),
        f"- Release gate issue re-evaluation: {after_issue_label} total issue(s) after repair.",
        (
            f"- Follow-up targets: {len(targets)} warning(s) grouped for reviewer attention."
            if targets
            else "- Follow-up targets: no warning follow-up targets; blocker details remain "
            "in release_gate.warning_repair metadata."
        ),
        (
            "- Scope: detailed release-gate issue rationale, claim IDs, evidence IDs, "
            "and acceptance rules are retained in release_gate.warning_repair metadata."
        ),
        "- By rule: " + _format_issue_rule_counts(rule_counts) + ".",
        "- By target section: " + _format_counts(section_counts) + ".",
        "- By required action: " + _format_counts(action_counts) + ".",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _issue_rule_counts(issues: list[BusinessQAFinding]) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = {}
    for issue in issues:
        counts.setdefault(issue.rule_id, Counter())[issue.severity] += 1
    return counts


def _format_issue_rule_counts(counts: dict[str, Counter[str]]) -> str:
    if not counts:
        return "none"
    parts: list[str] = []
    severity_order = {"blocker": 0, "warn": 1, "info": 2}
    for rule_id, severity_counts in sorted(counts.items()):
        severity_parts = [
            f"{count} {_display_severity(severity)}(s)"
            for severity, count in sorted(
                severity_counts.items(),
                key=lambda item: severity_order.get(item[0], 99),
            )
        ]
        parts.append(f"{rule_id}: {', '.join(severity_parts)}")
    return ", ".join(parts)


def _display_severity(severity: str) -> str:
    if severity == "warn":
        return "warning"
    return severity


def _format_counts(counts: Counter[str]) -> str:
    if not counts:
        return "none"
    return ", ".join(
        f"{label or 'unspecified'}: {count} warning(s)"
        for label, count in sorted(counts.items())
    )


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
