"""Seal deterministic shared evidence versions without retrieving or mutating documents."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from datetime import UTC, datetime

from packages.knowledge.models import KnowledgeDocument, KnowledgeScope
from packages.research.evidence.normalization import normalized_fields_from_source
from packages.research.evidence.snapshot_models import (
    EvidenceChanges,
    EvidenceConflict,
    EvidenceFact,
    EvidenceGap,
    EvidencePhase,
    EvidenceSource,
    RunEvidenceSnapshot,
    canonical_json,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource

_VALUE_FIELDS = {
    "pricing": (
        "model_type",
        "tier_name",
        "price",
        "billing_cycle",
        "usage_limit",
        "enterprise_condition",
    ),
    "feature": ("slot", "support_level", "evidence_terms"),
    "persona": ("segment", "role", "company_size", "use_case", "pain_point"),
}
_CONTEXT_FIELDS = ("unit", "market", "model", "capacity")
_SIGNAL_TYPES = {"report", "webpage_search", "web_search_result", "llm_public_knowledge"}
_SIGNAL_MATERIAL_LEVELS = {"summary", "search_summary", "historical_report"}
_KB_REFERENCE_KEYS = {
    "kb_document_id",
    "document_id",
    "kb_document_version",
    "document_version",
    "kb_document_content_hash",
    "kb_content_hash",
    "kb_chunk_id",
    "kb_chunk_ids",
    "chunk_id",
    "kb_document_workspace_id",
    "kb_document_project_id",
    "kb_source_role",
    "kb_document_status",
    "kb_parent_document_id",
    "kb_document_source_type",
    "kb_document_url",
    "kb_canonical_url",
    "kb_competitor",
    "kb_competitor_name",
    "kb_dimension",
    "kb_market",
    "kb_source_type",
    "kb_fetched_at",
    "kb_last_verified_at",
    "kb_source_published_at",
    "kb_source_updated_at",
}
_FORBIDDEN_VALUE_KEYS = {
    "full_text",
    "raw_text",
    "html",
    "credentials",
    "password",
    "api_key",
    "token",
    "instructions",
    "system_prompt",
    "workflow",
    "metadata",
}


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _identity(prefix: str, value: object) -> str:
    return f"{prefix}-{_digest(value)}"


def _key(value: str) -> str:
    return value.strip().casefold()


def _text(value: object, limit: int = 500) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _date(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _safe_value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {
            key: _safe_value(item)
            for key, item in value.items()
            if _key(key) not in _FORBIDDEN_VALUE_KEYS
        }
    raise ValueError("normalized evidence value must be finite JSON")


def _fields(
    source: RawSource,
    allowed_competitors: set[str],
    document: KnowledgeDocument | None,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in normalized_fields_from_source(source):
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _VALUE_FIELDS:
            continue
        competitor = _text(row.get("competitor")) or source.competitor
        dimension = _text(row.get("dimension")) or source.dimension
        if _key(competitor) not in allowed_competitors or _key(dimension) != _key(source.dimension):
            continue
        fields = (*_VALUE_FIELDS[kind], *_CONTEXT_FIELDS)
        try:
            safe = {key: _safe_value(row[key]) for key in fields if key in row}
            if "qualifiers" in row:
                if not isinstance(row["qualifiers"], dict):
                    continue
                safe["qualifiers"] = _safe_value(row["qualifiers"])
        except ValueError:
            continue
        if document:
            safe["market"] = document.market
        confidence = row.get("confidence", source.confidence)
        if (
            not isinstance(confidence, int | float)
            or isinstance(confidence, bool)
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            continue
        ids = row.get("evidence_item_ids", [])
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            continue
        quote_key = "source_quote" if kind == "pricing" else "evidence_quote"
        safe.update(
            {
                "kind": kind,
                "competitor": competitor,
                "dimension": dimension,
                "confidence": confidence,
                "evidence_item_ids": sorted(set(ids)),
                quote_key: row.get(quote_key) if isinstance(row.get(quote_key), str) else "",
                "source_url": str(source.url) if source.url else None,
            }
        )
        result.append(safe)
    return sorted(result, key=canonical_json)


def _gap(source: RawSource, reason: str, document_id: str | None = None) -> EvidenceGap:
    return EvidenceGap(
        id=_identity("evidence-gap", [source.id, reason, document_id]),
        reason=reason,
        source_id=source.id,
        document_id=document_id,
        competitor=source.competitor,
        dimension=source.dimension,
    )


def _document_reference(source: RawSource) -> tuple[str | None, str | None]:
    references = [
        source.metadata[key] for key in ("kb_document_id", "document_id") if key in source.metadata
    ]
    document_id = next(
        (value.strip() for value in references if isinstance(value, str) and value.strip()), None
    )
    if document_id is None:
        return None, None
    if any(not isinstance(value, str) or not value.strip() for value in references):
        return document_id, "canonical_reference_invalid"
    if any(value.strip() != document_id for value in references):
        return document_id, "canonical_reference_mismatch"
    return document_id, None


def _chunk_references(source: RawSource) -> tuple[tuple[str, ...], str | None]:
    singles = [
        source.metadata[key] for key in ("kb_chunk_id", "chunk_id") if key in source.metadata
    ]
    multiple = source.metadata.get("kb_chunk_ids", [])
    if (
        any(not isinstance(item, str) or not item.strip() for item in singles)
        or not isinstance(multiple, list)
        or any(not isinstance(item, str) or not item.strip() for item in multiple)
    ):
        return (), "chunk_reference_invalid"
    normalized_singles = tuple(item.strip() for item in singles)
    if len(set(normalized_singles)) > 1:
        return (), "chunk_reference_mismatch"
    return tuple(sorted(set((*normalized_singles, *(item.strip() for item in multiple))))), None


def _document_problem(
    source: RawSource,
    document: KnowledgeDocument,
    scope: KnowledgeScope,
) -> str | None:
    if document.workspace_id != scope.workspace_id or document.project_id not in {
        scope.project_id,
        None,
    }:
        return "scope_mismatch"
    if not document.is_active or document.status != "active":
        return "document_inactive"
    reference_versions = [source.metadata.get("kb_document_version")]
    if "document_version" in source.metadata:
        reference_versions.append(source.metadata["document_version"])
    if any(
        type(value) is not int or value < 1 or value != document.version
        for value in reference_versions
    ):
        return "version_mismatch"
    reference_hashes = [
        source.metadata[key]
        for key in ("kb_document_content_hash", "kb_content_hash")
        if key in source.metadata
    ]
    if (
        not document.content_hash
        or not reference_hashes
        or any(
            not isinstance(value, str) or value != document.content_hash
            for value in reference_hashes
        )
    ):
        return "hash_mismatch"
    if (
        _key(document.competitor or "") != _key(source.competitor)
        or any(_key(item) != _key(document.competitor or "") for item in source.covered_competitors)
        or _key(document.dimension or "") != _key(source.dimension)
        or (document.url or document.canonical_url or "").rstrip("/")
        != str(source.url or "").rstrip("/")
    ):
        return "identity_mismatch"
    return None


def _source_record(
    source: RawSource,
    detail: RunDetail,
    document: KnowledgeDocument | None,
    normalized: list[dict[str, object]],
    chunk_ids: tuple[str, ...],
) -> EvidenceSource:
    metadata = source.metadata
    published = (
        document.source_published_at if document else _date(metadata.get("source_published_at"))
    )
    updated = document.source_updated_at if document else _date(metadata.get("source_updated_at"))
    fetched = (
        document.fetched_at
        if document
        else _date(metadata.get("fetched_at")) or _date(metadata.get("source_fetched_at"))
    )
    verified = document.last_verified_at if document else _date(metadata.get("last_verified_at"))
    role = (
        document.source_role
        if document
        else ("historical_report" if source.source_type == "report" else "source")
    )
    market = document.market if document else (_text(metadata.get("market")) or None)
    extracted = document.fetched_at if document else source.extracted_at
    canonical_level = document.metadata.get("source_material_level") if document else None
    raw_level = metadata.get("source_material_level")
    if canonical_level in _SIGNAL_MATERIAL_LEVELS:
        material_level = canonical_level
    elif raw_level in _SIGNAL_MATERIAL_LEVELS:
        material_level = raw_level
    else:
        material_level = "kb_document" if document else raw_level
    if material_level not in {
        "full_source",
        "summary",
        "search_summary",
        "historical_report",
        "kb_document",
    }:
        material_level = "unknown"
    safe_metadata: dict[str, object] = {"normalized_fields": normalized, "source_role": role}
    # Conservative provenance flags survive the safe projection. They can weaken
    # synthetic/community evidence, never grant canonical scope or authority.
    for flag in ("fallback_synthetic", "survey_interview_synthetic", "community_evidence"):
        if metadata.get(flag) is True:
            safe_metadata[flag] = True
    safe_metadata["source_material_level"] = material_level
    for name, value in (
        ("source_published_at", published),
        ("source_updated_at", updated),
        ("source_fetched_at", fetched),
        ("last_verified_at", verified),
    ):
        safe_metadata[name] = value.isoformat() if value else None
    safe_metadata["market"] = market
    chunk_id = (
        next(
            (metadata[key].strip() for key in ("kb_chunk_id", "chunk_id") if key in metadata), None
        )
        if document
        else None
    )
    if document:
        safe_metadata.update(
            {
                "kb_document_id": document.id,
                "kb_chunk_id": chunk_id,
                "kb_document_version": document.version,
                "kb_document_content_hash": document.content_hash,
                "kb_document_workspace_id": document.workspace_id,
                "kb_document_project_id": document.project_id,
                "kb_source_role": document.source_role,
                "kb_document_status": document.status,
            }
        )
        if chunk_ids:
            safe_metadata["kb_chunk_ids"] = list(chunk_ids)
    source_type = document.source_type if document else source.source_type
    projection = {
        "id": source.id,
        "competitor": source.competitor,
        "covered_competitors": sorted(set(source.covered_competitors), key=_key),
        "dimension": source.dimension,
        "source_type": source_type,
        "title": _text(document.title if document else source.title, 200),
        "url": str(source.url) if source.url else None,
        "snippet": _text(source.snippet, 400),
        "content_hash": source.content_hash,
        "confidence": source.confidence,
        "candidate_origin": source.candidate_origin,
        "fetch_method": source.fetch_method,
        "quality_score": source.quality_score,
        "failure_reason": _text(source.failure_reason, 180) or None,
        "extracted_at": extracted.isoformat(),
        "metadata": safe_metadata,
    }
    identity = [
        detail.workspace_id,
        detail.project_id,
        source.id,
        source.competitor,
        source.dimension,
        market,
        document.id if document else None,
        chunk_id,
    ]
    if chunk_ids:
        identity.append(chunk_ids)
    return EvidenceSource(
        id=source.id,
        semantic_id=_identity("evidence-source", identity),
        competitor=source.competitor,
        covered_competitors=tuple(projection["covered_competitors"]),
        dimension=source.dimension,
        source_type=source_type,
        title=projection["title"],
        url=projection["url"],
        content_hash=source.content_hash,
        snippet=projection["snippet"],
        role=role,
        market=market,
        confidence=source.confidence,
        status=document.status if document else "active",
        verification_status="verified" if verified else "unknown",
        material_level=material_level,
        source_published_at=published,
        source_updated_at=updated,
        source_fetched_at=fetched,
        last_verified_at=verified,
        extracted_at=extracted,
        document_id=document.id if document else None,
        chunk_id=chunk_id,
        chunk_ids=chunk_ids,
        document_version=document.version if document else None,
        document_content_hash=document.content_hash if document else None,
        document_workspace_id=document.workspace_id if document else None,
        document_project_id=document.project_id if document else None,
        payload_json=canonical_json(projection),
    )


def _facts(source: EvidenceSource, normalized: list[dict[str, object]]) -> list[EvidenceFact]:
    result = []
    for row in normalized:
        kind = row["kind"]
        quote = row.get("source_quote") or row.get("evidence_quote") or ""
        evidence_ids = tuple(row["evidence_item_ids"])
        is_signal = (
            not quote.strip()
            or not evidence_ids
            or source.role == "historical_report"
            or source.source_type in _SIGNAL_TYPES
            or source.material_level in _SIGNAL_MATERIAL_LEVELS
        )
        qualifiers = {
            **row.get("qualifiers", {}),
            **{
                key: row[key]
                for key in (
                    "tier_name",
                    "billing_cycle",
                    "usage_limit",
                    "slot",
                    "model",
                    "capacity",
                )
                if row.get(key) not in (None, "", [])
            },
        }
        market = source.market if source.document_id else _text(row.get("market")) or source.market
        unit = _text(row.get("unit")) or None
        for field in _VALUE_FIELDS[kind]:
            value = row.get(field)
            if value in (None, "", [], {}):
                continue
            identity = [
                source.semantic_id,
                row["competitor"],
                row["dimension"],
                field,
                unit,
                market,
                qualifiers,
            ]
            semantic_id = _identity("evidence-fact", identity)
            result.append(
                EvidenceFact(
                    id=_identity(
                        "evidence-fact-record",
                        [semantic_id, evidence_ids, value, quote, row["confidence"], is_signal],
                    ),
                    semantic_id=semantic_id,
                    evidence_item_ids=evidence_ids,
                    source_id=source.id,
                    competitor=row["competitor"],
                    dimension=row["dimension"],
                    field=field,
                    value_json=canonical_json(value),
                    unit=unit,
                    market=market,
                    qualifiers_json=canonical_json(qualifiers),
                    quote=quote,
                    status="signal" if is_signal else "supported",
                    confidence=row["confidence"],
                )
            )
    return result


def _conflicts(facts: tuple[EvidenceFact, ...]) -> tuple[EvidenceConflict, ...]:
    groups: dict[str, list[EvidenceFact]] = {}
    for fact in facts:
        if fact.status != "supported":
            continue
        identity = [
            fact.competitor,
            fact.dimension,
            fact.field,
            fact.unit,
            fact.market,
            fact.qualifiers_json,
        ]
        groups.setdefault(canonical_json(identity), []).append(fact)
    conflicts = []
    for identity, group in sorted(groups.items()):
        if len({fact.value_json for fact in group}) <= 1:
            continue
        first = group[0]
        unknown = first.market is None or (first.field == "price" and first.unit is None)
        conflicts.append(
            EvidenceConflict(
                id=_identity("evidence-conflict", identity),
                competitor=first.competitor,
                dimension=first.dimension,
                field=first.field,
                unit=first.unit,
                market=first.market,
                qualifiers_json=first.qualifiers_json,
                fact_ids=tuple(sorted(fact.id for fact in group)),
                source_ids=tuple(sorted({fact.source_id for fact in group})),
                status="unknown" if unknown else "unresolved",
                reason="comparison_basis_unknown" if unknown else "inconsistent_values",
            )
        )
    return tuple(conflicts)


def _contract(snapshot: RunEvidenceSnapshot) -> dict[str, object]:
    contract = snapshot.model_dump(
        mode="json",
        exclude={
            "id",
            "version",
            "parent_id",
            "created_at",
            "content_hash",
        },
    )
    # The empty additive v1 field retains Task 1's canonical bytes.
    for source in contract["sources"]:
        if not source["chunk_ids"]:
            source.pop("chunk_ids")
    return contract


def _snapshot_id(snapshot: RunEvidenceSnapshot) -> str:
    return _identity(
        "evidence-snapshot",
        [
            snapshot.run_id,
            snapshot.workspace_id,
            snapshot.project_id,
            snapshot.version,
            snapshot.parent_id,
            snapshot.content_hash,
        ],
    )


def _verify(snapshot: RunEvidenceSnapshot) -> None:
    if _digest(_contract(snapshot)) != snapshot.content_hash:
        raise ValueError("evidence snapshot content hash mismatch")
    if _snapshot_id(snapshot) != snapshot.id:
        raise ValueError("evidence snapshot identity mismatch")


def current_snapshot(detail: RunDetail) -> RunEvidenceSnapshot | None:
    if detail.evidence_snapshot_id is None:
        if detail.evidence_snapshots:
            raise ValueError("evidence snapshot pointer missing for existing history")
        return None
    matches = [item for item in detail.evidence_snapshots if item.id == detail.evidence_snapshot_id]
    if len(matches) != 1:
        raise ValueError(
            "evidence snapshot pointer does not select exactly one historical snapshot"
        )
    snapshot = matches[0]
    _verify(snapshot)
    if snapshot.run_id != detail.id:
        raise ValueError("evidence snapshot run identity mismatch")
    return snapshot


def seal_snapshot(
    detail: RunDetail,
    *,
    phase: EvidencePhase,
    canonical_documents: Mapping[str, KnowledgeDocument],
) -> RunEvidenceSnapshot:
    """Seal admitted fields; invalid canonical references become explicit rejection gaps."""
    return _seal_snapshot(
        detail, phase=phase, canonical_documents=canonical_documents, rejected_sources={}
    )


def _seal_snapshot(
    detail: RunDetail,
    *,
    phase: EvidencePhase,
    canonical_documents: Mapping[str, KnowledgeDocument],
    rejected_sources: Mapping[str, EvidenceGap],
) -> RunEvidenceSnapshot:
    """Shared sealing path, including server-validated reference rejection records."""
    if phase not in {"collect", "analysis"}:
        raise ValueError("evidence snapshot phase must be collect or analysis")
    for document_id, document in canonical_documents.items():
        if not isinstance(document, KnowledgeDocument):
            raise TypeError("canonical_documents accepts only typed KnowledgeDocument records")
        if document.id != document_id:
            raise ValueError("canonical document mapping identity mismatch")
    previous = current_snapshot(detail)
    for snapshot in detail.evidence_snapshots:
        _verify(snapshot)
    scope = KnowledgeScope(
        workspace_id=detail.workspace_id,
        project_id=detail.project_id,
        include_workspace_library=True,
    )
    planned = {_key(item) for item in detail.plan.competitors}
    sources, facts, gaps = [], [], []
    for raw in detail.raw_sources:
        if raw.id in rejected_sources:
            rejected = rejected_sources[raw.id]
            if not isinstance(rejected, EvidenceGap) or rejected.source_id != raw.id:
                raise ValueError("invalid server evidence rejection identity")
            gaps.append(rejected)
            continue
        covered = {_key(item) for item in raw.covered_competitors}
        allowed = covered | ({_key(raw.competitor)} if _key(raw.competitor) in planned else set())
        if not allowed or not allowed <= planned or not covered <= planned:
            gaps.append(_gap(raw, "identity_mismatch"))
            continue
        document_id, reference_problem = _document_reference(raw)
        if reference_problem:
            gaps.append(_gap(raw, reference_problem, document_id))
            continue
        is_kb = (
            bool(_KB_REFERENCE_KEYS & raw.metadata.keys())
            or raw.metadata.get("kb_retrieved") is True
            or raw.metadata.get("kb_sync") is True
            or _text(raw.metadata.get("source_material_level")).startswith("kb_")
        )
        if is_kb and document_id is None:
            gaps.append(_gap(raw, "canonical_reference_missing"))
            continue
        document = canonical_documents.get(document_id) if document_id else None
        if document_id and document is None:
            gaps.append(_gap(raw, "canonical_document_missing", document_id))
            continue
        if document:
            reason = _document_problem(raw, document, scope)
            if reason:
                gaps.append(_gap(raw, reason, document_id))
                continue
            chunk_ids, reason = _chunk_references(raw)
            if reason:
                gaps.append(_gap(raw, reason, document_id))
                continue
        else:
            chunk_ids = ()
        normalized = _fields(raw, allowed, document)
        source = _source_record(raw, detail, document, normalized, chunk_ids)
        sources.append(source)
        facts.extend(_facts(source, normalized))
    source_records = tuple(
        sorted(set(sources), key=lambda item: (item.semantic_id, item.payload_json))
    )
    fact_records = tuple(
        sorted(set(facts), key=lambda item: canonical_json(item.model_dump(mode="json")))
    )
    snapshot = RunEvidenceSnapshot(
        id="",
        run_id=detail.id,
        workspace_id=detail.workspace_id,
        project_id=detail.project_id,
        version=max((item.version for item in detail.evidence_snapshots), default=0) + 1,
        parent_id=previous.id if previous else None,
        phase=phase,
        sources=source_records,
        facts=fact_records,
        conflicts=_conflicts(fact_records),
        gaps=tuple(sorted(set(gaps), key=lambda item: item.id)),
        content_hash="",
        created_at=datetime.now(UTC),
    )
    snapshot = snapshot.model_copy(update={"content_hash": _digest(_contract(snapshot))})
    if previous and previous.content_hash == snapshot.content_hash:
        return previous
    snapshot = snapshot.model_copy(update={"id": _snapshot_id(snapshot)})
    detail.evidence_snapshots = [*detail.evidence_snapshots, snapshot]
    detail.evidence_snapshot_id = snapshot.id
    return snapshot


def changed_evidence(
    previous: RunEvidenceSnapshot,
    current: RunEvidenceSnapshot,
) -> EvidenceChanges:
    """Compare semantic identities, retaining value corrections as changed dependencies."""
    _verify(previous)
    _verify(current)
    result = {}
    for kind in ("sources", "facts"):
        before, after = {}, {}
        for snapshot, target in ((previous, before), (current, after)):
            for item in getattr(snapshot, kind):
                target.setdefault(item.semantic_id, set()).add(
                    canonical_json(item.model_dump(mode="json"))
                )
        common = before.keys() & after.keys()
        result[f"added_{kind}"] = frozenset(after.keys() - before.keys())
        result[f"removed_{kind}"] = frozenset(before.keys() - after.keys())
        result[f"changed_{kind}"] = frozenset(key for key in common if before[key] != after[key])
        result[f"unchanged_{kind}"] = frozenset(key for key in common if before[key] == after[key])
    return EvidenceChanges(**result)
