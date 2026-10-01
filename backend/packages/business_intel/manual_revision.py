"""Rebuild manual draft claims from the edited body and scoped evidence."""

import re

from packages.business_intel.claim_validator import validate_project_claims
from packages.business_intel.source_reconciliation import evidence_by_source_token, source_tokens
from packages.identity import stable_prefixed_id
from packages.schema.enterprise import ClaimRecord, EvidenceRecord, ReportVersionRecord


def validate_manual_revision(
    version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
) -> tuple[list[ClaimRecord], dict[str, object]]:
    by_token = evidence_by_source_token(evidence)
    claims: list[ClaimRecord] = []
    unbound: list[dict[str, object]] = []
    lines = version.report_md.splitlines()
    body_parts = []
    for line_number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text or text.startswith(("#", "<!--")) or re.fullmatch(r"[|:\s-]+", text):
            continue
        if (
            text.startswith("|") and line_number < len(lines)
            and re.fullmatch(r"[|:\s-]+", lines[line_number])
        ):
            continue
        parts = [text] if text.startswith("|") else re.split(
            r"(?<=[.!?])\s+(?!\[)|(?<=\])\s+(?=[A-Z\u4e00-\u9fff])|(?<=[。！？])(?!\s*\[)", text,
        )
        body_parts.extend((line_number, index, part) for index, part in enumerate(parts))
    for line_number, part_index, text in body_parts:
        cited = {
            item.id: item for token in source_tokens(text)
            if (item := by_token.get(token)) is not None
        }
        claim_text = re.sub(
            r"\[\s*(?:source|来源)\s*[:：][^\]]*\]", "", text, flags=re.IGNORECASE,
        ).strip(" |-*")
        if not claim_text:
            continue
        if not cited:
            unbound.append({"line_number": line_number, "claim_text": claim_text})
            continue
        first = next(iter(cited.values()))
        claims.append(ClaimRecord(
            id=stable_prefixed_id(
                "claim-manual", version.id, line_number, part_index, claim_text, length=16,
            ),
            workspace_id=version.workspace_id, project_id=version.project_id, run_id=version.run_id,
            competitor_id=first.competitor_id,
            claim_type=first.dimension, claim_text=claim_text,
            evidence_ids=list(cited),
            confidence=min(item.reliability_score for item in cited.values()),
            created_by_agent="manual_revision",
        ))
    validation = validate_project_claims(
        project_id=version.project_id, claims=claims, evidence=evidence,
    )
    findings = [{
        "id": stable_prefixed_id("qa-manual", version.id, result.claim_id, length=16),
        "severity": "blocker" if (
            result.status in {"blocked", "unsupported"}
            or result.text_support_score < 40 or result.high_risk
        ) else "warn",
        "detected_by": "claim_validator", "target_agent": "writer",
        "field_path": "manual_revision.current_body",
        "problem": f"Current manual claim is {result.status}: {result.claim_id}",
        "metadata": {"claim_ids": [result.claim_id], "evidence_ids": result.usable_evidence_ids},
    } for result in validation.results if result.status != "supported"]
    findings.extend({
        "id": stable_prefixed_id(
            "qa-manual-unbound", version.id, item["line_number"], item["claim_text"], length=16,
        ),
        "severity": "blocker", "detected_by": "citation", "target_agent": "writer",
        "field_path": f"report_md.line[{item['line_number']}]",
        "problem": "Current manual claim has no scoped source citation.",
        "metadata": item,
    } for item in unbound)
    return claims, {
        "run_qa_findings": findings,
        "run_qa_blocker_count": sum(item["severity"] == "blocker" for item in findings),
        "run_qa_warning_count": sum(item["severity"] == "warn" for item in findings),
        "manual_claim_validation": validation.model_dump(mode="json"),
        "unresolved_manual_claims": unbound,
    }
