from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from packages.memory import PreferenceMemoryStore
from packages.schema.enterprise import EvidenceRecord, MemoryCandidate, ReportVersionRecord

ADVISORY_CONTEXT_POLICY_VERSION = "c5.4"

AdvisoryContextKind = Literal["memory", "rag_retrieval", "project_history"]
AdvisoryContextScope = Literal["advisory_only", "report_scope"]


class AdvisoryContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: AdvisoryContextKind
    scope: AdvisoryContextScope
    entered_report_scope: bool
    report_scope_reason: str
    advisory_reason: str
    source_system: str
    memory_candidate_id: str | None = None
    evidence_id: str | None = None
    raw_source_id: str | None = None
    chunk_id: str | None = None
    retrieval_stage: str = ""
    title: str = ""
    summary: str = ""
    score: float = Field(default=0.0, ge=-1.0, le=1.0)
    status: str = ""
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdvisoryContextReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = ADVISORY_CONTEXT_POLICY_VERSION
    scope_policy: str = "report_version_scope_only"
    history_policy: str = "project_history_and_memory_are_advisory_context"
    workspace_id: str
    project_id: str
    report_version_id: str
    run_id: str | None = None
    report_scope_evidence_ids: list[str] = Field(default_factory=list)
    report_scope_claim_ids: list[str] = Field(default_factory=list)
    memory_candidate_ids: list[str] = Field(default_factory=list)
    rag_retrieval_evidence_ids: list[str] = Field(default_factory=list)
    project_history_evidence_ids: list[str] = Field(default_factory=list)
    item_count: int = 0
    report_scope_item_count: int = 0
    advisory_only_item_count: int = 0
    memory_item_count: int = 0
    rag_item_count: int = 0
    project_history_item_count: int = 0
    items: list[AdvisoryContextItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class AdvisoryContextStore(Protocol):
    def list_evidence(self, project_id: str | None = None) -> list[EvidenceRecord]: ...


def build_run_advisory_context_metadata(
    *,
    version: ReportVersionRecord,
    memory_candidate_ids: Iterable[str],
    memory_prompt_context: Iterable[str],
) -> dict[str, Any]:
    memory_ids = _dedupe_strings(memory_candidate_ids)
    prompt_context = [str(item) for item in memory_prompt_context if str(item).strip()]
    return {
        "policy_version": ADVISORY_CONTEXT_POLICY_VERSION,
        "scope_policy": "report_version_scope_only",
        "history_policy": "project_history_and_memory_are_advisory_context",
        "report_version_id": version.id,
        "run_id": version.run_id,
        "report_scope_evidence_ids": list(version.evidence_ids),
        "report_scope_claim_ids": list(version.claim_ids),
        "memory_candidate_ids": memory_ids,
        "memory_prompt_context": prompt_context,
        "memory_policy": "advisory_only",
        "rag_policy": "report_scope_only_when_evidence_id_is_admitted",
        "project_history_policy": "advisory_only_unless_linked_to_report_version",
    }


def build_advisory_context_report(
    *,
    version: ReportVersionRecord,
    store: AdvisoryContextStore,
    memory: PreferenceMemoryStore | None = None,
) -> AdvisoryContextReport:
    report_evidence_ids = set(version.evidence_ids)
    metadata = version.quality_metadata
    advisory_metadata = _dict_metadata(metadata.get("advisory_context"))
    memory_ids = _dedupe_strings(
        [
            *advisory_metadata.get("memory_candidate_ids", []),
            *_dict_metadata(metadata.get("memory_used")).get("candidate_ids", []),
        ]
    )
    project_evidence = store.list_evidence(project_id=version.project_id)
    evidence_by_id = {item.id: item for item in project_evidence}
    items = [
        *_memory_items(
            memory_ids,
            memory=memory,
            prompt_context=advisory_metadata.get("memory_prompt_context", []),
        ),
        *_rag_items(
            version,
            evidence_by_id=evidence_by_id,
            report_evidence_ids=report_evidence_ids,
        ),
        *_project_history_items(
            project_evidence,
            report_evidence_ids=report_evidence_ids,
        ),
    ]
    items = _dedupe_items(items)
    return AdvisoryContextReport(
        workspace_id=version.workspace_id,
        project_id=version.project_id,
        report_version_id=version.id,
        run_id=version.run_id,
        report_scope_evidence_ids=list(version.evidence_ids),
        report_scope_claim_ids=list(version.claim_ids),
        memory_candidate_ids=memory_ids,
        rag_retrieval_evidence_ids=_dedupe_strings(
            [item.evidence_id for item in items if item.kind == "rag_retrieval"]
        ),
        project_history_evidence_ids=_dedupe_strings(
            [item.evidence_id for item in items if item.kind == "project_history"]
        ),
        item_count=len(items),
        report_scope_item_count=sum(1 for item in items if item.entered_report_scope),
        advisory_only_item_count=sum(1 for item in items if not item.entered_report_scope),
        memory_item_count=sum(1 for item in items if item.kind == "memory"),
        rag_item_count=sum(1 for item in items if item.kind == "rag_retrieval"),
        project_history_item_count=sum(1 for item in items if item.kind == "project_history"),
        items=items,
    )


def _memory_items(
    candidate_ids: list[str],
    *,
    memory: PreferenceMemoryStore | None,
    prompt_context: object,
) -> list[AdvisoryContextItem]:
    prompt_lines = [str(item) for item in prompt_context if str(item).strip()]
    by_id = _prompt_context_by_candidate_id(prompt_lines)
    items: list[AdvisoryContextItem] = []
    for candidate_id in candidate_ids:
        candidate = memory.get_candidate(candidate_id) if memory is not None else None
        items.append(
            _memory_item(
                candidate_id,
                candidate,
                fallback_summary=by_id.get(candidate_id, ""),
            )
        )
    return items


def _memory_item(
    candidate_id: str,
    candidate: MemoryCandidate | None,
    *,
    fallback_summary: str,
) -> AdvisoryContextItem:
    return AdvisoryContextItem(
        id=f"advisory-memory-{candidate_id}",
        kind="memory",
        scope="advisory_only",
        entered_report_scope=False,
        report_scope_reason=(
            "Memory can influence planning, ranking, or writing, but is not "
            "publishable evidence."
        ),
        advisory_reason="Recalled MemoryAgent candidate.",
        source_system="preference_memory",
        memory_candidate_id=candidate_id,
        title=f"Memory candidate {candidate_id}",
        summary=(candidate.statement if candidate is not None else fallback_summary),
        score=(candidate.match_score if candidate is not None else 0.0),
        status=(candidate.status if candidate is not None else "unknown"),
        tags=(candidate.tags if candidate is not None else []),
        metadata=(
            {
                "kind": candidate.kind,
                "weight": candidate.weight,
                "confidence": candidate.confidence,
                "used_count": candidate.used_count,
            }
            if candidate is not None
            else {}
        ),
    )


def _rag_items(
    version: ReportVersionRecord,
    *,
    evidence_by_id: dict[str, EvidenceRecord],
    report_evidence_ids: set[str],
) -> list[AdvisoryContextItem]:
    rag_metadata = _dict_metadata(version.quality_metadata.get("rag_gap_fill"))
    admitted_ids = set(_string_list(rag_metadata.get("admitted_evidence_ids")))
    records = [
        item
        for item in rag_metadata.get("retrieval_records", [])
        if isinstance(item, dict) and str(item.get("evidence_id") or "").strip()
    ]
    items: list[AdvisoryContextItem] = []
    for record in records:
        evidence_id = str(record.get("evidence_id") or "").strip()
        evidence = evidence_by_id.get(evidence_id)
        entered = evidence_id in report_evidence_ids and evidence_id in admitted_ids
        items.append(
            AdvisoryContextItem(
                id=f"advisory-rag-{record.get('chunk_id') or evidence_id}",
                kind="rag_retrieval",
                scope="report_scope" if entered else "advisory_only",
                entered_report_scope=entered,
                report_scope_reason=(
                    "RAG retrieval evidence was admitted into this ReportVersion scope."
                    if entered
                    else (
                        "RAG retrieval stayed advisory because its evidence_id is not "
                        "admitted in this ReportVersion."
                    )
                ),
                advisory_reason="Retrieved by RAG/gap-fill context.",
                source_system="rag",
                evidence_id=evidence_id,
                raw_source_id=evidence.raw_source_id if evidence is not None else None,
                chunk_id=str(record.get("chunk_id") or ""),
                retrieval_stage=str(record.get("retrieval_stage") or ""),
                title=str(record.get("title") or (evidence.title if evidence is not None else "")),
                summary=str(
                    record.get("snippet") or (evidence.snippet if evidence is not None else "")
                ),
                score=float(record.get("score") or 0.0),
                status=evidence.quality_label if evidence is not None else "unknown",
                tags=_dedupe_strings(
                    [
                        "rag",
                        str(record.get("dimension") or ""),
                        str(record.get("source_type") or ""),
                    ]
                ),
                metadata={
                    "vector_score": record.get("vector_score", 0.0),
                    "bm25_score": record.get("bm25_score", 0.0),
                    "rerank_score": record.get("rerank_score", 0.0),
                    "source_url": record.get("source_url", ""),
                    "admitted": evidence_id in admitted_ids,
                },
            )
        )
    return items


def _project_history_items(
    evidence: list[EvidenceRecord],
    *,
    report_evidence_ids: set[str],
) -> list[AdvisoryContextItem]:
    items: list[AdvisoryContextItem] = []
    for item in evidence:
        if item.id in report_evidence_ids:
            continue
        items.append(
            AdvisoryContextItem(
                id=f"advisory-history-{item.id}",
                kind="project_history",
                scope="advisory_only",
                entered_report_scope=False,
                report_scope_reason=(
                    "Project history is excluded unless its evidence_id is linked to "
                    "this ReportVersion."
                ),
                advisory_reason=(
                    "Historical project evidence remains available as planning context."
                ),
                source_system="enterprise_store",
                evidence_id=item.id,
                raw_source_id=item.raw_source_id,
                title=item.title,
                summary=item.snippet,
                score=item.reliability_score,
                status=item.quality_label,
                tags=_dedupe_strings(["history", item.dimension, item.source_type]),
                metadata={
                    "run_id": item.run_id,
                    "first_seen_run_id": item.first_seen_run_id,
                    "last_seen_run_id": item.last_seen_run_id,
                    "seen_count": item.seen_count,
                },
            )
        )
    return items


def _prompt_context_by_candidate_id(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines:
        if not line.startswith("[") or "]" not in line:
            continue
        candidate_id = line[1 : line.index("]")].strip()
        if candidate_id:
            result[candidate_id] = line
    return result


def _dict_metadata(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_strings(value)


def _dedupe_strings(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dedupe_items(items: Iterable[AdvisoryContextItem]) -> list[AdvisoryContextItem]:
    seen: set[str] = set()
    result: list[AdvisoryContextItem] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result
