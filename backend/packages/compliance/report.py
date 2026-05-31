from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from packages.compliance.pii import compliance_policy_from_settings, redact_text
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource, TraceSpan


class ComplianceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Literal["info", "warn", "blocker"]
    category: Literal["pii", "source", "robots", "policy", "trace"]
    target_type: Literal["run", "source", "trace_span"]
    target_id: str
    message: str
    recommendation: str


class RunComplianceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["pass", "warn", "fail"]
    policy: dict[str, object] = Field(default_factory=dict)
    source_count: int = Field(ge=0)
    trace_span_count: int = Field(ge=0)
    redaction_count: int = Field(ge=0)
    finding_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    warn_count: int = Field(ge=0)
    findings: list[ComplianceFinding] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


NO_URL_SOURCE_TYPES = {
    "demo",
    "fixture",
    "manual",
    "memory",
    "synthetic",
    "survey",
    "survey_simulated",
}


def build_run_compliance_report(
    detail: RunDetail,
    *,
    settings: object,
) -> RunComplianceReport:
    findings: list[ComplianceFinding] = []
    policy = compliance_policy_from_settings(settings)
    policy_snapshot = {
        "redaction_enabled": policy.redaction_enabled,
        "redact_api_keys": policy.redact_api_keys,
        "redact_emails": policy.redact_emails,
        "redact_phones": policy.redact_phones,
        "allowed_domains": list(getattr(settings, "compliance_allowed_domains", ())),
        "blocked_domains": list(getattr(settings, "compliance_blocked_domains", ())),
        "require_source_urls": bool(
            getattr(settings, "compliance_require_source_urls", False)
        ),
        "require_trace_context": bool(
            getattr(settings, "compliance_require_trace_context", True)
        ),
    }

    findings.extend(_policy_findings(detail.id, policy_snapshot))
    findings.extend(_source_findings(detail.raw_sources, settings=settings))
    findings.extend(_trace_findings(detail.trace_spans, settings=settings))
    findings.extend(_pii_findings(detail, policy=policy))
    findings = _dedupe_findings(findings)
    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    warn_count = sum(1 for finding in findings if finding.severity == "warn")
    status: Literal["pass", "warn", "fail"] = "pass"
    if blocker_count:
        status = "fail"
    elif warn_count:
        status = "warn"
    return RunComplianceReport(
        run_id=detail.id,
        status=status,
        policy=policy_snapshot,
        source_count=len(detail.raw_sources),
        trace_span_count=len(detail.trace_spans),
        redaction_count=detail.metrics.compliance_redaction_count,
        finding_count=len(findings),
        blocker_count=blocker_count,
        warn_count=warn_count,
        findings=findings,
    )


def _policy_findings(run_id: str, policy_snapshot: dict[str, object]) -> list[ComplianceFinding]:
    findings: list[ComplianceFinding] = []
    if not policy_snapshot["redaction_enabled"]:
        findings.append(
            _finding(
                severity="warn",
                category="policy",
                target_type="run",
                target_id=run_id,
                message="Compliance redaction is disabled for this environment.",
                recommendation="Enable COMPLIANCE_REDACTION_ENABLED before real enterprise runs.",
            )
        )
    for key in ("redact_api_keys", "redact_emails", "redact_phones"):
        if policy_snapshot[key]:
            continue
        findings.append(
            _finding(
                severity="warn",
                category="policy",
                target_type="run",
                target_id=run_id,
                message=f"{key} is disabled in the compliance policy.",
                recommendation=(
                    "Keep all PII and credential redaction switches enabled in production."
                ),
            )
        )
    return findings


def _source_findings(
    sources: list[RawSource],
    *,
    settings: object,
) -> list[ComplianceFinding]:
    findings: list[ComplianceFinding] = []
    require_source_urls = bool(getattr(settings, "compliance_require_source_urls", False))
    allowed_domains = tuple(getattr(settings, "compliance_allowed_domains", ()))
    blocked_domains = tuple(getattr(settings, "compliance_blocked_domains", ()))
    for source in sources:
        source_type = source.source_type.lower()
        if "robots" in source_type and "blocked" in source_type:
            findings.append(
                _finding(
                    severity="blocker",
                    category="robots",
                    target_type="source",
                    target_id=source.id,
                    message="Source is marked as blocked by robots/source policy.",
                    recommendation=(
                        "Remove this source or route it through a compliant approval flow."
                    ),
                )
            )
        if source.url is None:
            if require_source_urls and source_type not in NO_URL_SOURCE_TYPES:
                findings.append(
                    _finding(
                        severity="warn",
                        category="source",
                        target_type="source",
                        target_id=source.id,
                        message="Source has no URL while source URL enforcement is enabled.",
                        recommendation=(
                            "Attach a source URL or mark the source as manual/synthetic."
                        ),
                    )
                )
            continue
        host = _url_host(str(source.url))
        if _domain_matches(host, blocked_domains):
            findings.append(
                _finding(
                    severity="blocker",
                    category="source",
                    target_type="source",
                    target_id=source.id,
                    message=f"Source domain {host} is blocked by compliance policy.",
                    recommendation="Replace this source with an allowed domain.",
                )
            )
        if allowed_domains and not _domain_matches(host, allowed_domains):
            findings.append(
                _finding(
                    severity="warn",
                    category="source",
                    target_type="source",
                    target_id=source.id,
                    message=f"Source domain {host} is outside the allowlist.",
                    recommendation="Review the source domain or update COMPLIANCE_ALLOWED_DOMAINS.",
                )
            )
    return findings


def _trace_findings(
    spans: list[TraceSpan],
    *,
    settings: object,
) -> list[ComplianceFinding]:
    if not bool(getattr(settings, "compliance_require_trace_context", True)):
        return []
    findings: list[ComplianceFinding] = []
    for span in spans:
        missing = [
            field
            for field, value in (
                ("trace_id", span.trace_id),
                ("otel_span_id", span.otel_span_id),
                ("traceparent", span.traceparent),
            )
            if not value
        ]
        if not missing:
            continue
        findings.append(
            _finding(
                severity="blocker",
                category="trace",
                target_type="trace_span",
                target_id=span.id,
                message=f"Trace span is missing required context: {', '.join(missing)}.",
                recommendation="Emit W3C trace context for every span before production release.",
            )
        )
    return findings


def _pii_findings(detail: RunDetail, *, policy: object) -> list[ComplianceFinding]:
    findings: list[ComplianceFinding] = []
    candidates: list[tuple[str, str, str]] = [("run", detail.id, detail.report_md)]
    candidates.extend(("source", source.id, source.snippet) for source in detail.raw_sources)
    candidates.extend(
        ("trace_span", span.id, f"{span.full_input}\n{span.full_output}")
        for span in detail.trace_spans
    )
    for target_type, target_id, text in candidates:
        if not text:
            continue
        result = redact_text(text, policy)  # type: ignore[arg-type]
        if result.total_count == 0:
            continue
        findings.append(
            _finding(
                severity="blocker",
                category="pii",
                target_type=target_type,  # type: ignore[arg-type]
                target_id=target_id,
                message=(
                    "Potential unredacted sensitive text remains in persisted content: "
                    f"{result.counts}."
                ),
                recommendation="Apply redaction before storing or exposing this artifact.",
            )
        )
    return findings


def _finding(
    *,
    severity: Literal["info", "warn", "blocker"],
    category: Literal["pii", "source", "robots", "policy", "trace"],
    target_type: Literal["run", "source", "trace_span"],
    target_id: str,
    message: str,
    recommendation: str,
) -> ComplianceFinding:
    raw = "|".join([severity, category, target_type, target_id, message])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return ComplianceFinding(
        id=f"compliance-{digest}",
        severity=severity,
        category=category,
        target_type=target_type,
        target_id=target_id,
        message=message,
        recommendation=recommendation,
    )


def _dedupe_findings(findings: list[ComplianceFinding]) -> list[ComplianceFinding]:
    seen: set[str] = set()
    deduped: list[ComplianceFinding] = []
    for finding in findings:
        if finding.id in seen:
            continue
        seen.add(finding.id)
        deduped.append(finding)
    return sorted(deduped, key=lambda item: (_severity_rank(item.severity), item.category))


def _severity_rank(severity: str) -> int:
    return {"blocker": 0, "warn": 1, "info": 2}.get(severity, 3)


def _url_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _domain_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)
