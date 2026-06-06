from __future__ import annotations

import re
from urllib.parse import urlparse

from packages.business_intel.claim_validator import validate_project_claims
from packages.business_intel.evaluator import BAD_QUALITY_LABELS, evaluate_business_qa
from packages.business_intel.planning import build_business_intel_plan
from packages.business_intel.scorer import score_project_readiness
from packages.business_intel.source_reconciliation import (
    evidence_by_source_token,
    malformed_source_tokens,
    normalize_source_token,
    source_tokens,
)
from packages.identity import compute_release_gate_issue_id
from packages.schema.enterprise import (
    BusinessQAFinding,
    ClaimRecord,
    CompetitorRecord,
    EvidenceRecord,
    ProjectReadinessScore,
    ProjectRecord,
    ReportReleaseGate,
    ReportVersionRecord,
    SourceRegistryRecord,
)

MIN_VERIFIED_EVIDENCE_RATE = 0.8
MIN_READY_SCORE = 85
MIN_RELEASE_SOURCE_CONFIDENCE = 0.75
MIN_REPORT_STRUCTURE_SCORE = 0.7
MIN_REPORT_BODY_CHARS = 900
STRONG_CONCLUSION_RE = re.compile(
    r"\b("
    r"winner|leading option|best option|safer|safest|recommended|recommendation|"
    r"dimension winner|executive summary|soc\s*2|iso\s*/?\s*iec|ip indemnity|"
    r"sso|saml|scim|audit log|pricing transparency"
    r")\b",
    flags=re.IGNORECASE,
)


def evaluate_report_release_gate(
    *,
    project: ProjectRecord,
    report_version: ReportVersionRecord,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
    source_registry: list[SourceRegistryRecord] | None = None,
) -> ReportReleaseGate:
    """Strict enterprise gate for approving or publishing a report version."""

    report_scoped_evidence = _scope_evidence(report_version, evidence)
    scoped_evidence = _apply_source_registry_policy(
        report_scoped_evidence, source_registry or []
    )
    scoped_claims = _scope_claims(report_version, claims)
    dimensions = sorted({item.dimension for item in scoped_evidence}) or [
        "pricing",
        "feature",
        "persona",
    ]
    plan = build_business_intel_plan(
        topic=project.topic,
        competitors=[item.name for item in competitors],
        dimensions=dimensions,
        requested_layer=project.competitor_layer if project.competitor_layer != "unknown" else None,
        requested_scenario_id=project.scenario_id,
    )
    qa_evaluation = evaluate_business_qa(
        project_id=project.id,
        plan=plan,
        competitors=competitors,
        evidence=scoped_evidence,
        claims=scoped_claims,
    )
    readiness = score_project_readiness(
        project_id=project.id,
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=scoped_evidence,
        claims=scoped_claims,
    )
    issues = [
        *_report_status_issues(report_version),
        *_report_integrity_issues(report_version, scoped_evidence, scoped_claims),
        *_report_structure_issues(report_version),
        *_report_depth_issues(report_version),
        *_source_quality_issues(scoped_evidence),
        *_claim_evidence_quality_issues(scoped_claims, scoped_evidence),
        *_claim_validation_issues(scoped_claims, scoped_evidence),
        *_missing_report_citation_issues(report_version, report_scoped_evidence),
        *_report_citation_quality_issues(report_version, report_scoped_evidence),
        *_run_quality_issues(report_version),
        *_readiness_issues(readiness),
        *_strict_qa_issues(qa_evaluation.findings),
    ]
    blocker_count = len([item for item in issues if item.severity == "blocker"])
    warn_count = len([item for item in issues if item.severity == "warn"])
    allowed = blocker_count == 0 and qa_evaluation.finding_count == 0
    return ReportReleaseGate(
        report_version_id=report_version.id,
        workspace_id=report_version.workspace_id,
        project_id=report_version.project_id,
        allowed=allowed,
        status="pass" if allowed else "blocked",
        readiness=readiness,
        qa_evaluation=qa_evaluation,
        issue_count=len(issues),
        blocker_count=blocker_count,
        warn_count=warn_count,
        issues=issues,
    )


def _scope_evidence(
    report_version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
) -> list[EvidenceRecord]:
    allowed_ids = set(report_version.evidence_ids)
    return [item for item in evidence if item.id in allowed_ids]


def _apply_source_registry_policy(
    evidence: list[EvidenceRecord],
    source_registry: list[SourceRegistryRecord],
) -> list[EvidenceRecord]:
    if not source_registry:
        return evidence
    by_id = {item.id: item for item in source_registry}
    by_key = {
        (item.workspace_id, item.domain.casefold(), item.source_type.casefold()): item
        for item in source_registry
    }
    result: list[EvidenceRecord] = []
    for item in evidence:
        registry = by_id.get(str(item.metadata.get("source_registry_id") or ""))
        if registry is None:
            registry = by_key.get(_source_registry_key(item))
        if registry is None:
            result.append(item)
            continue
        metadata = dict(item.metadata)
        if registry.policy_review_status != "not_required":
            metadata["policy_review_status"] = registry.policy_review_status
        if registry.policy_review_reason:
            metadata["policy_review_reason"] = registry.policy_review_reason
        if registry.robots_status != "unknown":
            metadata["robots_status"] = registry.robots_status
        metadata["source_registry_id"] = registry.id
        result.append(item.model_copy(update={"metadata": metadata}))
    return result


def _source_registry_key(evidence: EvidenceRecord) -> tuple[str, str, str]:
    url_value = evidence.canonical_url or (str(evidence.url) if evidence.url else "")
    host = urlparse(url_value).hostname or ""
    domain = host.casefold()
    if domain.startswith("www."):
        domain = domain[4:]
    return (evidence.workspace_id, domain, evidence.source_type.casefold())


def _scope_claims(
    report_version: ReportVersionRecord,
    claims: list[ClaimRecord],
) -> list[ClaimRecord]:
    allowed_ids = set(report_version.claim_ids)
    return [item for item in claims if item.id in allowed_ids]


def _report_status_issues(report_version: ReportVersionRecord) -> list[BusinessQAFinding]:
    if report_version.status not in {"rejected", "archived"}:
        return []
    return [
        _gate_issue(
            "report_status_releasable",
            "Report status releasable",
            f"Report version status is {report_version.status}; it cannot be released.",
            recommendation="Create a new draft or restart approval before publishing this report.",
        )
    ]


def _report_integrity_issues(
    report_version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> list[BusinessQAFinding]:
    issues: list[BusinessQAFinding] = []
    if not report_version.report_md.strip():
        issues.append(
            _gate_issue(
                "report_body_required",
                "Report body required",
                "Report body is empty; approval is blocked until a readable report exists.",
                recommendation="Regenerate the report after evidence and claims are available.",
            )
        )
    if not evidence:
        issues.append(
            _gate_issue(
                "report_evidence_required",
                "Report evidence required",
                "Report version has no scoped evidence records.",
                recommendation="Collect and attach verified EvidenceRecord items before approval.",
            )
        )
    if not claims:
        issues.append(
            _gate_issue(
                "report_claim_required",
                "Report claims required",
                "Report version has no scoped knowledge claims.",
                recommendation="Project structured claims from accepted evidence before approval.",
            )
        )
    evidence_ids = {item.id for item in evidence}
    for claim in claims:
        missing = [item for item in claim.evidence_ids if item not in evidence_ids]
        if not missing:
            continue
        issues.append(
            _gate_issue(
                "claim_evidence_in_report",
                "Claim evidence must be in report",
                f"Claim {claim.id} cites evidence outside this report version.",
                claim_ids=[claim.id],
                evidence_ids=missing,
                recommendation="Attach the cited evidence to this report or remove the claim.",
            )
        )
    return issues


def _source_quality_issues(evidence: list[EvidenceRecord]) -> list[BusinessQAFinding]:
    if not evidence:
        return []
    issues: list[BusinessQAFinding] = []
    policy_review_evidence = [
        item
        for item in evidence
        if _source_policy_review_status(item) in {"pending", "rejected"}
        or _source_robots_status(item) in {"blocked", "error"}
    ]
    if policy_review_evidence:
        statuses = sorted(
            {
                (
                    f"{item.id}:policy={_source_policy_review_status(item)},"
                    f"robots={_source_robots_status(item)}"
                )
                for item in policy_review_evidence
            }
        )
        issues.append(
            _gate_issue(
                "source_policy_review_required",
                "Source policy review required",
                (
                    "Report evidence includes source(s) that are pending or rejected by "
                    f"robots/source policy review: {'; '.join(statuses)}."
                ),
                evidence_ids=[item.id for item in policy_review_evidence],
                recommendation=(
                    "Resolve the Source Registry review queue or replace these evidence records "
                    "before approval."
                ),
            )
        )
    verified = [
        item
        for item in evidence
        if item.source_type == "webpage_verified"
        and item.quality_label not in BAD_QUALITY_LABELS
        and item.reliability_score >= 0.5
    ]
    verified_rate = len(verified) / len(evidence)
    if verified_rate >= MIN_VERIFIED_EVIDENCE_RATE:
        return issues
    issues.append(
        _gate_issue(
            "verified_evidence_rate",
            "Verified evidence rate",
            (
                f"Only {verified_rate:.0%} of report evidence is verified and usable; "
                f"minimum is {MIN_VERIFIED_EVIDENCE_RATE:.0%}."
            ),
            evidence_ids=[item.id for item in evidence],
            recommendation=(
                "Replace weak sources with verified webpages or mark bad evidence stale/rejected."
            ),
        )
    )
    return issues


def _source_policy_review_status(evidence: EvidenceRecord) -> str:
    status = str(
        evidence.metadata.get("policy_review_status")
        or evidence.metadata.get("source_policy_review_status")
        or "not_required"
    ).casefold()
    if status in {"not_required", "pending", "approved", "rejected"}:
        return status
    return "not_required"


def _source_robots_status(evidence: EvidenceRecord) -> str:
    status = str(evidence.metadata.get("robots_status") or "unknown").casefold()
    if status in {"allowed", "blocked", "error"}:
        return status
    source_type = evidence.source_type.casefold()
    if "robots" in source_type and "blocked" in source_type:
        return "blocked"
    return "unknown"


def _claim_evidence_quality_issues(
    claims: list[ClaimRecord],
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    evidence_by_id = {item.id: item for item in evidence}
    issues: list[BusinessQAFinding] = []
    for claim in claims:
        weak = [
            item
            for evidence_id in claim.evidence_ids
            if (item := evidence_by_id.get(evidence_id)) is not None
            and (
                item.source_type != "webpage_verified"
                or item.reliability_score < MIN_RELEASE_SOURCE_CONFIDENCE
                or item.quality_label in BAD_QUALITY_LABELS
            )
        ]
        if not weak:
            continue
        issues.append(
            _gate_issue(
                "claim_uses_low_confidence_evidence",
                "Claim evidence confidence",
                (
                    f"Claim {claim.id} depends on {len(weak)} weak evidence item(s); "
                    "release claims require verified webpage evidence with confidence >= "
                    f"{MIN_RELEASE_SOURCE_CONFIDENCE:.2f}."
                ),
                claim_ids=[claim.id],
                evidence_ids=[item.id for item in weak],
                recommendation=(
                    "Redo collection for this claim using official or fetched webpages before "
                    "publishing."
                ),
            )
        )
    return issues


def _report_structure_issues(report_version: ReportVersionRecord) -> list[BusinessQAFinding]:
    score, missing = _report_structure_score(report_version)
    hard_missing = [name for name in missing if name == "Claim Validation & Evidence Risk"]
    if score >= MIN_REPORT_STRUCTURE_SCORE and not hard_missing:
        return []
    return [
        _gate_issue(
            "report_structure_required",
            "Report structure required",
            (
                "Report is missing required decision-grade section(s): "
                f"{', '.join(missing)}. Structure score={score:.2f}; "
                f"minimum is {MIN_REPORT_STRUCTURE_SCORE:.2f}."
            ),
            recommendation=(
                "Regenerate or revise the report with executive summary, source quality, "
                "decision matrix, scenario QA checklist, layer-specific analysis, claim "
                "validation risk, next collection plan, and evidence appendix."
            ),
        )
    ]


def _report_structure_score(report_version: ReportVersionRecord) -> tuple[float, list[str]]:
    checks = [
        (
            "Executive Summary",
            _has_heading(report_version.report_md, ("executive summary", "executive overview")),
        ),
        (
            "Source Quality & Coverage",
            _has_heading(report_version.report_md, ("source quality", "source coverage")),
        ),
        (
            "Decision Matrix",
            _has_heading(report_version.report_md, ("matrix", "dimension winners", "side-by-side")),
        ),
        (
            "Scenario QA Checklist",
            _has_heading(report_version.report_md, ("scenario qa", "scenario checklist")),
        ),
        (
            "Claim Validation & Evidence Risk",
            _has_heading(report_version.report_md, ("claim validation", "evidence risk")),
        ),
        (
            "Next Collection / Verification Plan",
            _has_heading(
                report_version.report_md,
                ("next collection", "verification plan", "evidence gap"),
            ),
        ),
        (
            "Evidence Appendix",
            _has_heading(report_version.report_md, ("evidence appendix", "source appendix")),
        ),
        ("Layer-Specific Analysis", _has_layer_heading(report_version)),
    ]
    passed = sum(1 for _name, ok in checks if ok)
    missing = [name for name, ok in checks if not ok]
    return passed / len(checks), missing


def _report_depth_issues(report_version: ReportVersionRecord) -> list[BusinessQAFinding]:
    body_chars = len(report_version.report_md.strip())
    if body_chars >= MIN_REPORT_BODY_CHARS:
        return []
    return [
        _gate_issue(
            "report_depth_required",
            "Report depth required",
            (
                f"Report body has {body_chars} character(s); enterprise release requires "
                f"at least {MIN_REPORT_BODY_CHARS} characters of decision-grade analysis."
            ),
            recommendation=(
                "Regenerate or revise the report with concrete evidence-backed analysis, "
                "tradeoffs, risk notes, and next validation tasks before release."
            ),
        )
    ]


def _has_layer_heading(report_version: ReportVersionRecord) -> bool:
    layer = report_version.competitor_layer
    if layer == "L1":
        return _has_heading(report_version.report_md, ("battlecard", "sales objection"))
    if layer == "L2":
        return _has_heading(report_version.report_md, ("workflow", "enterprise risk", "switching"))
    if layer == "L3":
        return _has_heading(
            report_version.report_md, ("market landscape", "segmentation", "benchmark")
        )
    return _has_heading(report_version.report_md, ("business implication", "strategy"))


def _has_heading(markdown: str, needles: tuple[str, ...]) -> bool:
    headings = [
        match.group(1).casefold()
        for match in re.finditer(r"^\s*#{1,4}\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    ]
    return any(any(needle in heading for needle in needles) for heading in headings)


def _claim_validation_issues(
    claims: list[ClaimRecord],
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    if not claims:
        return []
    project_id = claims[0].project_id
    validation = validate_project_claims(project_id=project_id, claims=claims, evidence=evidence)
    claims_by_id = {claim.id: claim for claim in claims}
    validation_issues_by_id = {issue.id: issue for issue in validation.issues}
    issues: list[BusinessQAFinding] = []
    for result in validation.results:
        if result.status == "supported":
            continue
        claim = claims_by_id.get(result.claim_id)
        severity = "blocker" if result.status in {"blocked", "unsupported"} else "warn"
        claim_issue_types = [
            issue.issue_type
            for issue_id in result.issue_ids
            if (issue := validation_issues_by_id.get(issue_id)) is not None
        ]
        failed_checkers = [
            sample.checker for sample in result.validation_samples if sample.vote == "fail"
        ]
        issue_summary = f"; issue_types={', '.join(claim_issue_types)}" if claim_issue_types else ""
        checker_summary = f"; failed_checks={', '.join(failed_checkers)}" if failed_checkers else ""
        issues.append(
            _gate_issue(
                "claim_self_consistency_required",
                "Claim self-consistency",
                (
                    f"Claim {result.claim_id} validation is {result.status}; "
                    f"self-consistency={result.self_consistency_score}, "
                    f"text={result.text_support_score}, "
                    f"evidence={result.evidence_quality_score}, "
                    f"triangulation={result.triangulation_score}"
                    f"{issue_summary}{checker_summary}."
                ),
                severity=severity,
                competitor_id=claim.competitor_id if claim is not None else None,
                dimension=claim.claim_type if claim is not None else None,
                claim_ids=[result.claim_id],
                evidence_ids=result.usable_evidence_ids,
                recommendation=(
                    "Collect stronger independent evidence, resolve the listed claim-validation "
                    "issue types, or downgrade the claim before release."
                ),
                metadata={
                    "claim_validation_status": result.status,
                    "claim_validation_issue_types": claim_issue_types,
                    "failed_checkers": failed_checkers,
                    "support_score": result.support_score,
                    "text_support_score": result.text_support_score,
                    "evidence_quality_score": result.evidence_quality_score,
                    "triangulation_score": result.triangulation_score,
                    "self_consistency_score": result.self_consistency_score,
                },
            )
        )
    return issues


def _report_citation_quality_issues(
    report_version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    evidence_by_token = evidence_by_source_token(evidence)

    issues: list[BusinessQAFinding] = []
    for line in report_version.report_md.splitlines():
        if not STRONG_CONCLUSION_RE.search(line):
            continue
        weak = [
            evidence_by_token[normalized]
            for token in _cited_source_tokens(line)
            if (normalized := normalize_source_token(token)) in evidence_by_token
            and (
                evidence_by_token[normalized].source_type != "webpage_verified"
                or evidence_by_token[normalized].reliability_score < MIN_RELEASE_SOURCE_CONFIDENCE
                or evidence_by_token[normalized].quality_label in BAD_QUALITY_LABELS
            )
        ]
        if not weak:
            continue
        issues.append(
            _gate_issue(
                "strong_conclusion_uses_weak_source",
                "Strong conclusion source quality",
                (
                    "A strong report conclusion cites weak or search-only evidence. "
                    f"Line: {line.strip()[:220]}"
                ),
                evidence_ids=[item.id for item in weak],
                recommendation=(
                    "Rewrite the conclusion as tentative or recollect official/verified sources."
                ),
            )
        )
    return issues


def _missing_report_citation_issues(
    report_version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    evidence_by_token = evidence_by_source_token(evidence)
    malformed = malformed_source_tokens(report_version.report_md)
    missing = sorted(
        {
            token
            for token in _cited_source_tokens(report_version.report_md)
            if normalize_source_token(token) not in evidence_by_token
        }
    )
    issues: list[BusinessQAFinding] = []
    if malformed:
        issues.append(
            _gate_issue(
                "report_citation_token_format",
                "Report citation token format",
                (
                    "Report contains malformed source token(s): "
                    f"{', '.join(malformed[:8])}."
                ),
                recommendation=(
                    "Remove malformed [source:...] markers or replace them with canonical "
                    "RawSource ids."
                ),
            )
        )
    if not missing:
        return issues
    issues.append(
        _gate_issue(
            "report_citation_resolves",
            "Report citations resolve",
            (
                "Report contains source token(s) that do not resolve to the report evidence "
                f"scope: {', '.join(missing[:8])}."
            ),
            recommendation=(
                "Attach the cited evidence to this report version, replace the token with a "
                "canonical RawSource id, or remove the unsupported sentence."
            ),
        )
    )
    return issues


def _run_quality_issues(report_version: ReportVersionRecord) -> list[BusinessQAFinding]:
    issues: list[BusinessQAFinding] = []
    schema_pass_rate = report_version.quality_metadata.get("schema_pass_rate")
    if isinstance(schema_pass_rate, (int, float)) and float(schema_pass_rate) < 1.0:
        issues.append(
            _gate_issue(
                "run_schema_validation_failed",
                "Run schema validation",
                (
                    "Report release requires all schema-first outputs to validate; "
                    f"schema pass rate is {float(schema_pass_rate):.0%}."
                ),
                recommendation=(
                    "Redo the failing agent branch or repair the typed output before approval."
                ),
            )
        )

    rag_gap_fill = report_version.quality_metadata.get("rag_gap_fill")
    if isinstance(rag_gap_fill, dict):
        chain_closed = rag_gap_fill.get("gap_fill_chain_closed")
        after_gap_count = rag_gap_fill.get("after_gap_count")
        unfilled_gap_ids = _string_list(
            rag_gap_fill.get("unfilled_gap_ids") or rag_gap_fill.get("remaining_gap_ids")
        )
        gap_evidence_links = rag_gap_fill.get("gap_evidence_links")
        has_links = isinstance(gap_evidence_links, dict) and any(gap_evidence_links.values())
        unresolved_count = (
            int(after_gap_count) if isinstance(after_gap_count, int) else len(unfilled_gap_ids)
        )
        if chain_closed is False or unresolved_count > 0 or not has_links:
            unfilled_summary = ", ".join(unfilled_gap_ids[:5]) or "n/a"
            online_failure_summary = _online_failure_summary(rag_gap_fill.get("online_failures"))
            online_failure_sentence = (
                f" online_failures={online_failure_summary}." if online_failure_summary else ""
            )
            issues.append(
                _gate_issue(
                    "rag_gap_fill_chain_unclosed",
                    "RAG gap-fill chain",
                    (
                        "Report release requires the RAG evidence-gap fill chain to close; "
                        f"chain_closed={bool(chain_closed)}, remaining_gap_count="
                        f"{unresolved_count}, unfilled_gap_ids={unfilled_summary}."
                        f"{online_failure_sentence}"
                    ),
                    recommendation=(
                        "Run online gap fill again, attach verified evidence for each remaining "
                        "gap, review any online search/fetch/robots failures, or keep the report "
                        "in draft with the gap explicitly unresolved."
                    ),
                )
            )

    findings = report_version.quality_metadata.get("run_qa_findings", [])
    if not isinstance(findings, list) or not findings:
        return issues
    blocker_count = sum(1 for item in findings if _mapping_value(item, "severity") == "blocker")
    warn_count = sum(1 for item in findings if _mapping_value(item, "severity") == "warn")
    resolution = report_version.quality_metadata.get("run_qa_findings_resolution")
    if (
        blocker_count == 0
        and isinstance(resolution, dict)
        and resolution.get("status") == "mitigated_by_release_controls"
    ):
        issues.append(
            _gate_issue(
                "run_qa_findings_mitigated",
                "Run QA findings mitigated",
                (
                    "Run-level QA warnings were converted into release controls; "
                    f"{warn_count} warning(s) remain visible for reviewer awareness."
                ),
                severity="warn",
                recommendation=(
                    "Review the Claim Release Controls section and execute queued repair "
                    "tasks before treating withheld claims as publishable."
                ),
                metadata={
                    "resolution_status": resolution.get("status"),
                    "mitigated_warning_ids": _string_list(
                        resolution.get("mitigated_warning_ids")
                    ),
                    "withheld_claim_count": resolution.get("withheld_claim_count"),
                },
            )
        )
        return issues
    top_problems = [
        str(_mapping_value(item, "problem") or _mapping_value(item, "id") or "quality issue")
        for item in findings[:3]
    ]
    issues.append(
        _gate_issue(
            "run_qa_findings_unresolved",
            "Run QA findings unresolved",
            (
                "Report release requires a clean run-level QA result; "
                f"current run has {blocker_count} blocker(s) and {warn_count} warning(s). "
                f"Top issue(s): {'; '.join(top_problems)}"
            ),
            recommendation=(
                "Run scoped redo for the affected collector/analyst/comparator branches before "
                "publishing."
            ),
        )
    )
    return issues


def _readiness_issues(readiness: ProjectReadinessScore) -> list[BusinessQAFinding]:
    if readiness.risk_level == "ready" and readiness.score >= MIN_READY_SCORE:
        return []
    return [
        _gate_issue(
            "readiness_required",
            "Readiness threshold",
            (
                f"Readiness is {readiness.risk_level} with score {readiness.score}; "
                f"approval requires ready and score >= {MIN_READY_SCORE}."
            ),
            recommendation="Resolve evidence, coverage, claim, and QA gaps before approval.",
        )
    ]


def _strict_qa_issues(findings: list[BusinessQAFinding]) -> list[BusinessQAFinding]:
    if not findings:
        return []
    warn_count = len([item for item in findings if item.severity == "warn"])
    blocker_count = len([item for item in findings if item.severity == "blocker"])
    return [
        _gate_issue(
            "business_qa_clean_required",
            "Business QA must be clean",
            (
                "Report approval requires zero business QA findings; "
                f"current evaluation has {blocker_count} blocker(s) and {warn_count} warning(s)."
            ),
            recommendation="Resolve all Business QA findings or keep the report in draft.",
        )
    ]


def _gate_issue(
    rule_id: str,
    rule_name: str,
    message: str,
    *,
    evidence_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
    competitor_id: str | None = None,
    competitor_name: str | None = None,
    dimension: str | None = None,
    severity: str = "blocker",
    recommendation: str,
    metadata: dict[str, object] | None = None,
) -> BusinessQAFinding:
    return BusinessQAFinding(
        id=compute_release_gate_issue_id(rule_id, message, evidence_ids, claim_ids),
        rule_id=rule_id,
        rule_name=rule_name,
        severity=severity,  # type: ignore[arg-type]
        competitor_id=competitor_id,
        competitor_name=competitor_name,
        dimension=dimension,
        message=message,
        evidence_ids=evidence_ids or [],
        claim_ids=claim_ids or [],
        recommendation=recommendation,
        metadata=metadata or {},
    )


def _cited_source_tokens(line: str) -> list[str]:
    return source_tokens(line)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _online_failure_summary(value: object) -> str:
    if not isinstance(value, list) or not value:
        return ""
    summaries: list[str] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "unknown").strip()
        gap_id = str(item.get("gap_id") or "unknown-gap").strip()
        url = str(item.get("url") or "").strip()
        error = str(item.get("error") or "").strip()
        parts = [stage, gap_id]
        if url:
            parts.append(url[:80])
        if error:
            parts.append(error[:120])
        summaries.append(" / ".join(parts))
    if not summaries:
        return f"{len(value)} failure(s)"
    extra = len(value) - len(summaries)
    suffix = f"; +{extra} more" if extra > 0 else ""
    return f"{len(value)} failure(s): " + "; ".join(summaries) + suffix


def _mapping_value(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return None
