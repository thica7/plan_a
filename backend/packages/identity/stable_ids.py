from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_digest(*parts: object, length: int | None = None) -> str:
    raw = "|".join(_identity_part(part) for part in parts)
    digest = _sha256_hex(raw)
    return digest[:length] if length else digest


def stable_prefixed_id(prefix: str, *parts: object, length: int = 16) -> str:
    return f"{prefix}-{stable_digest(*parts, length=length)}"


def runtime_prefixed_id(prefix: str, *, entropy: str | None = None, length: int = 32) -> str:
    value = (entropy or uuid4().hex).strip()
    return f"{prefix}-{value[:length]}"


def new_subagent_context_id(run_id: str, agent: str, subagent: str) -> str:
    entropy = uuid4().hex[:8]
    return f"{run_id}:{normalize_key(agent)}:{normalize_key(subagent)}:{entropy}"


def _identity_part(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return ",".join(
            f"{_identity_part(key)}={_identity_part(value[key])}" for key in sorted(value)
        )
    if isinstance(value, set):
        return ",".join(_identity_part(item) for item in sorted(value, key=str))
    if isinstance(value, (list, tuple)):
        return ",".join(_identity_part(item) for item in value)
    return str(value).strip()


def normalize_url(url: str | None) -> str:
    """Canonicalize source URLs for stable evidence identity."""
    if not url:
        return ""

    raw = url.strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")

    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower().strip())


def normalize_dimension_key(dimension: str | None) -> str:
    if not dimension:
        return ""
    return re.sub(r"[^a-z0-9_]+", "_", normalize_text(dimension)).strip("_")


def compute_content_hash(content: str | bytes | None) -> str:
    if content is None:
        return _sha256_hex("")
    if isinstance(content, bytes):
        return hashlib.sha256(content).hexdigest()
    return _sha256_hex(content)


def compute_raw_source_id(
    *,
    source_type: str | None,
    competitor: str | None,
    dimension: str | None,
    url: str | None = None,
    content_hash: str | None = None,
    title: str | None = None,
    snippet: str | None = None,
    run_id: str | None = None,
    source_role: str | None = None,
) -> str:
    stable_url = normalize_url(url)
    stable_content = content_hash or compute_content_hash(snippet or title or "")
    return stable_prefixed_id(
        "raw-source",
        source_role or "source",
        source_type or "",
        normalize_text(competitor),
        normalize_dimension_key(dimension),
        stable_url,
        stable_content,
        run_id if not stable_url and not stable_content else "",
        length=20,
    )


def compute_evidence_id(
    canonical_url: str | None,
    content_hash: str | None,
    competitor_id: str | None,
    dimension_key: str | None,
) -> str:
    raw = "|".join(
        [
            normalize_url(canonical_url),
            content_hash or "",
            competitor_id or "",
            normalize_dimension_key(dimension_key),
        ]
    )
    return _sha256_hex(raw)


def compute_claim_id(
    evidence_id: str | None,
    claim_text: str | None,
    claim_type: str | None,
) -> str:
    raw = "|".join(
        [
            evidence_id or "",
            normalize_text(claim_text),
            normalize_dimension_key(claim_type),
        ]
    )
    return _sha256_hex(raw)


def compute_report_version_id(
    *,
    run_id: str | None,
    version_number: int,
    topic_normalized: str | None = None,
    competitor_set_hash: str | None = None,
) -> str:
    return stable_prefixed_id(
        "report-version",
        run_id or "",
        version_number,
        topic_normalized or "",
        competitor_set_hash or "",
        length=20,
    )


def compute_gap_fill_report_version_id(
    source_report_version_id: str,
    filled_gap_ids: Iterable[str],
    candidate_ids: Iterable[str],
) -> str:
    return stable_prefixed_id(
        "report-version-gap-fill",
        source_report_version_id,
        list(filled_gap_ids),
        list(candidate_ids),
        length=16,
    )


def compute_project_id(
    workspace_id: str,
    topic: str,
    competitor_ids: Iterable[str],
) -> str:
    return stable_prefixed_id(
        "project",
        workspace_id,
        compute_topic_normalized(topic),
        compute_competitor_set_hash(list(competitor_ids)),
        length=16,
    )


def compute_competitor_id(workspace_id: str, name: str) -> str:
    return stable_prefixed_id("competitor", workspace_id, normalize_key(name), length=16)


def compute_source_registry_id(workspace_id: str, domain: str, source_type: str) -> str:
    return stable_prefixed_id(
        "source-registry",
        workspace_id,
        normalize_key(domain),
        normalize_key(source_type),
        length=16,
    )


def compute_graph_thread_id(run_id: str, purpose: str, *parts: object) -> str:
    return stable_prefixed_id("graph-thread", run_id, purpose, *parts, length=24)


def compute_survey_respondent_id(
    run_id: str,
    competitor: str,
    dimension: str,
    ordinal: int,
) -> str:
    return stable_prefixed_id(
        "survey-respondent",
        run_id,
        normalize_text(competitor),
        normalize_dimension_key(dimension),
        ordinal,
        length=16,
    )


def compute_evidence_gap_id(
    *,
    severity: str,
    gap_type: str,
    competitor_id: str | None = None,
    dimension: str | None = None,
    message: str = "",
    evidence_ids: Iterable[str] | None = None,
    claim_ids: Iterable[str] | None = None,
) -> str:
    return stable_prefixed_id(
        "evidence-gap",
        severity,
        gap_type,
        competitor_id or "",
        normalize_dimension_key(dimension),
        message,
        list(evidence_ids or []),
        list(claim_ids or []),
        length=16,
    )


def compute_schema_suggestion_id(dimension_key: str, gap_ids: Iterable[str]) -> str:
    return stable_prefixed_id("schema-suggestion", dimension_key, list(gap_ids), length=16)


def compute_business_qa_finding_id(
    rule_id: str,
    competitor_id: str | None,
    dimension: str | None,
    message: str,
) -> str:
    return stable_prefixed_id(
        "business-qa",
        rule_id,
        competitor_id or "",
        normalize_dimension_key(dimension),
        message,
        length=16,
    )


def compute_release_gate_issue_id(
    rule_id: str,
    message: str,
    evidence_ids: Iterable[str] | None = None,
    claim_ids: Iterable[str] | None = None,
) -> str:
    return stable_prefixed_id(
        "release-gate",
        rule_id,
        message,
        list(evidence_ids or []),
        list(claim_ids or []),
        length=16,
    )


def compute_red_team_finding_id(
    finding_type: str,
    competitor_id: str | None,
    dimension: str | None,
    message: str,
    *,
    severity: str | None = None,
    evidence_ids: Iterable[str] | None = None,
    claim_ids: Iterable[str] | None = None,
) -> str:
    return stable_prefixed_id(
        "red-team",
        severity or "",
        finding_type,
        competitor_id or "",
        normalize_dimension_key(dimension),
        message,
        list(evidence_ids or []),
        list(claim_ids or []),
        length=16,
    )


def compute_recommendation_id(
    project_id: str,
    recommendation_type: str,
    title: str,
    stable_parts: Iterable[object] | None = None,
) -> str:
    return stable_prefixed_id(
        "recommendation",
        project_id,
        recommendation_type,
        title,
        list(stable_parts or []),
        length=16,
    )


def compute_artifact_id(
    *,
    workspace_id: str,
    project_id: str,
    evidence_id: str | None,
    artifact_type: str,
    filename: str,
    content_hash: str,
) -> str:
    return stable_prefixed_id(
        "artifact",
        workspace_id,
        project_id,
        evidence_id or "",
        artifact_type,
        filename.casefold(),
        content_hash,
        length=32,
    )


def compute_workflow_idempotency_key(request_payload: Mapping[str, object]) -> str:
    return f"workflow:{stable_digest(request_payload, length=32)}"


def compute_run_id_for_idempotency_key(idempotency_key: str) -> str:
    return stable_prefixed_id("run", idempotency_key, length=32)


def new_run_id() -> str:
    return runtime_prefixed_id("run")


def new_ui_run_idempotency_key() -> str:
    return f"ui-run:{uuid4().hex}"


def compute_cutover_bucket(key: str, *, namespace: str = "temporal-cutover") -> int:
    return int(stable_digest(namespace, key, length=8), 16) % 100


def compute_workflow_id(prefix: str, *parts: object, length: int = 32) -> str:
    return stable_prefixed_id(prefix, *parts, length=length)


def compute_notification_id(*parts: object) -> str:
    return stable_prefixed_id("notification", *parts, length=24)


def compute_monitor_anomaly_id(*parts: object) -> str:
    return stable_prefixed_id("anomaly", *parts, length=16)


def compute_compliance_finding_id(run_id: str, rule_id: str, message: str) -> str:
    return stable_prefixed_id("compliance", run_id, rule_id, message, length=16)


def compute_knowledge_graph_edge_id(source_id: str, target_id: str, relation: str) -> str:
    return stable_prefixed_id("kg-edge", source_id, target_id, relation, length=24)


def compute_retrieval_chunk_id(evidence_id: str, index: int, text: str) -> str:
    return stable_prefixed_id("chunk", evidence_id, index, text, length=24)


def compute_trace_id(run_id: str) -> str:
    return stable_digest("competiscope-trace", run_id, length=32)


def compute_otel_span_id(run_id: str, span_id: str) -> str:
    return stable_digest("competiscope-span", run_id, span_id, length=16)


def compute_feedback_id(feedback_id: str, message: str) -> str:
    return stable_prefixed_id("feedback", feedback_id, message, length=20)


def compute_memory_candidate_id(*parts: object) -> str:
    return stable_prefixed_id("memory", *parts, length=20)


def compute_competitor_set_hash(
    competitor_ids: list[str] | tuple[str, ...] | set[str] | None,
) -> str:
    if not competitor_ids:
        return _sha256_hex("")
    normalized = sorted({item.strip() for item in competitor_ids if item and item.strip()})
    return _sha256_hex("|".join(normalized))


def compute_topic_normalized(topic: str | None) -> str:
    text = normalize_text(topic)
    text = re.sub(r"[、，。！？,.;:!?]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_text(value)).strip("-") or "unknown"
