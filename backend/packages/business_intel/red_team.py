from __future__ import annotations

import hashlib
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from packages.agents.pydantic_ai_adapter import (
    PydanticAIAgentExecutor,
    pydantic_ai_available,
)
from packages.business_intel.evaluator import BAD_QUALITY_LABELS
from packages.schema.enterprise import (
    BusinessIntelPlan,
    BusinessQAEvaluation,
    ClaimRecord,
    CompetitorRecord,
    EvidenceRecord,
    RedTeamFinding,
    RedTeamReport,
    ReportVersionRecord,
)


class RedTeamInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    plan: BusinessIntelPlan
    qa_evaluation: BusinessQAEvaluation
    competitors: list[CompetitorRecord] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    report_versions: list[ReportVersionRecord] = Field(default_factory=list)


def analyze_red_team(
    *,
    project_id: str,
    plan: BusinessIntelPlan,
    qa_evaluation: BusinessQAEvaluation,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
    report_versions: list[ReportVersionRecord],
) -> RedTeamReport:
    agent_input = RedTeamInput(
        project_id=project_id,
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
        report_versions=report_versions,
    )
    return _red_team_handler(agent_input)


def build_red_team_agent() -> PydanticAIAgentExecutor[RedTeamInput, RedTeamReport]:
    return PydanticAIAgentExecutor(
        name="red_team",
        input_type=RedTeamInput,
        output_type=RedTeamReport,
        handler=_red_team_handler,
        system_prompt=(
            "Challenge unsupported competitive-intelligence claims, weak evidence, "
            "stale sources, homepage verification risk, and report decision risk."
        ),
    )


def _red_team_handler(agent_input: RedTeamInput) -> RedTeamReport:
    findings: list[RedTeamFinding] = []
    findings.extend(_qa_findings(agent_input))
    findings.extend(_claim_findings(agent_input))
    findings.extend(_evidence_findings(agent_input))
    findings.extend(_coverage_bias_findings(agent_input))
    findings.extend(_report_findings(agent_input))
    findings = _dedupe_findings(findings)
    high_count = len([item for item in findings if item.severity in {"critical", "high"}])
    return RedTeamReport(
        project_id=agent_input.project_id,
        finding_count=len(findings),
        high_severity_count=high_count,
        findings=findings,
        pydantic_ai_available=pydantic_ai_available(),
    )


def _qa_findings(agent_input: RedTeamInput) -> list[RedTeamFinding]:
    findings: list[RedTeamFinding] = []
    for finding in agent_input.qa_evaluation.findings:
        if finding.severity not in {"blocker", "warn"}:
            continue
        findings.append(
            _finding(
                severity="critical" if finding.severity == "blocker" else "high",
                finding_type="report_risk",
                competitor_id=finding.competitor_id,
                competitor_name=finding.competitor_name,
                dimension=finding.dimension,
                message=finding.message,
                recommendation=finding.recommendation
                or "Resolve this QA issue before using the report for a decision.",
                evidence_ids=finding.evidence_ids,
                claim_ids=finding.claim_ids,
            )
        )
    return findings


def _claim_findings(agent_input: RedTeamInput) -> list[RedTeamFinding]:
    evidence_by_id = {item.id: item for item in agent_input.evidence}
    competitor_by_id = {item.id: item for item in agent_input.competitors}
    findings: list[RedTeamFinding] = []
    for claim in agent_input.claims:
        linked_evidence = [evidence_by_id.get(item) for item in claim.evidence_ids]
        usable = [
            item
            for item in linked_evidence
            if item is not None and item.quality_label not in BAD_QUALITY_LABELS
        ]
        competitor = competitor_by_id.get(claim.competitor_id)
        if not usable:
            findings.append(
                _finding(
                    severity="critical",
                    finding_type="unsupported_claim",
                    competitor_id=claim.competitor_id,
                    competitor_name=competitor.name if competitor else None,
                    dimension=claim.claim_type,
                    message="A claim is not backed by any usable EvidenceRecord.",
                    recommendation="Attach accepted evidence or remove the claim from the report.",
                    evidence_ids=claim.evidence_ids,
                    claim_ids=[claim.id],
                )
            )
        elif claim.confidence < 0.55:
            findings.append(
                _finding(
                    severity="high",
                    finding_type="weak_evidence",
                    competitor_id=claim.competitor_id,
                    competitor_name=competitor.name if competitor else None,
                    dimension=claim.claim_type,
                    message="A low-confidence claim is still present in the decision record.",
                    recommendation="Collect stronger evidence or mark the claim as disputed.",
                    evidence_ids=[item.id for item in usable],
                    claim_ids=[claim.id],
                )
            )
    return findings


def _evidence_findings(agent_input: RedTeamInput) -> list[RedTeamFinding]:
    competitor_by_id = {item.id: item for item in agent_input.competitors}
    findings: list[RedTeamFinding] = []
    for evidence in agent_input.evidence:
        competitor = competitor_by_id.get(evidence.competitor_id)
        if evidence.quality_label in BAD_QUALITY_LABELS:
            findings.append(
                _finding(
                    severity="high",
                    finding_type="stale_or_rejected_evidence",
                    competitor_id=evidence.competitor_id,
                    competitor_name=competitor.name if competitor else None,
                    dimension=evidence.dimension,
                    message=(
                        f"Evidence is marked {evidence.quality_label} "
                        "but remains in the project."
                    ),
                    recommendation="Replace this evidence with current accepted evidence.",
                    evidence_ids=[evidence.id],
                )
            )
        elif evidence.reliability_score < 0.5:
            findings.append(
                _finding(
                    severity="high",
                    finding_type="weak_evidence",
                    competitor_id=evidence.competitor_id,
                    competitor_name=competitor.name if competitor else None,
                    dimension=evidence.dimension,
                    message="Evidence reliability is below the Phase 3 reporting threshold.",
                    recommendation="Verify with an official page or independent trusted source.",
                    evidence_ids=[evidence.id],
                )
            )
    return findings


def _coverage_bias_findings(agent_input: RedTeamInput) -> list[RedTeamFinding]:
    dimensions = (
        agent_input.plan.scenario_pack.required_dimensions
        or agent_input.plan.requested_dimensions
    )
    evidence_counts = Counter(
        (item.competitor_id, item.dimension)
        for item in agent_input.evidence
        if item.quality_label not in BAD_QUALITY_LABELS
    )
    findings: list[RedTeamFinding] = []
    for competitor in agent_input.competitors:
        missing = [
            dimension
            for dimension in dimensions
            if evidence_counts[(competitor.id, dimension)] == 0
        ]
        if not missing:
            continue
        findings.append(
            _finding(
                severity="high",
                finding_type="competitive_bias",
                competitor_id=competitor.id,
                competitor_name=competitor.name,
                dimension=", ".join(missing),
                message=(
                    "The comparison may bias against a competitor with missing "
                    "required evidence."
                ),
                recommendation="Collect missing evidence before ranking or recommending a winner.",
            )
        )
    return findings


def _report_findings(agent_input: RedTeamInput) -> list[RedTeamFinding]:
    latest = agent_input.report_versions[0] if agent_input.report_versions else None
    if latest is None:
        return [
            _finding(
                severity="high",
                finding_type="report_risk",
                message="No ReportVersion exists for this project.",
                recommendation="Generate a report version after evidence and claims are projected.",
            )
        ]
    if latest.report_md.count("[source:") < max(1, len(latest.claim_ids) // 2):
        return [
            _finding(
                severity="high",
                finding_type="report_risk",
                message="The latest report has weak citation density relative to projected claims.",
                recommendation="Rewrite the report with source references for factual claims.",
                claim_ids=latest.claim_ids,
                evidence_ids=latest.evidence_ids,
            )
        ]
    return []


def _finding(
    *,
    severity: str,
    finding_type: str,
    message: str,
    recommendation: str,
    competitor_id: str | None = None,
    competitor_name: str | None = None,
    dimension: str | None = None,
    evidence_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
) -> RedTeamFinding:
    raw = "|".join(
        [
            severity,
            finding_type,
            competitor_id or "",
            dimension or "",
            message,
            ",".join(evidence_ids or []),
            ",".join(claim_ids or []),
        ]
    )
    return RedTeamFinding(
        id=f"red-team-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
        severity=severity,  # type: ignore[arg-type]
        finding_type=finding_type,  # type: ignore[arg-type]
        competitor_id=competitor_id,
        competitor_name=competitor_name,
        dimension=dimension,
        message=message,
        recommendation=recommendation,
        evidence_ids=evidence_ids or [],
        claim_ids=claim_ids or [],
    )


def _dedupe_findings(findings: list[RedTeamFinding]) -> list[RedTeamFinding]:
    seen: set[str] = set()
    deduped: list[RedTeamFinding] = []
    for finding in findings:
        key = "|".join(
            [
                finding.finding_type,
                finding.competitor_id or "",
                finding.dimension or "",
                ",".join(finding.evidence_ids),
                ",".join(finding.claim_ids),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return sorted(deduped, key=lambda item: (_severity_rank(item.severity), item.finding_type))


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 4)
