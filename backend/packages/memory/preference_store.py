from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from packages.compliance import CompliancePolicy, redact_text
from packages.identity import compute_feedback_id, compute_memory_candidate_id
from packages.schema.enterprise import (
    MemoryCandidate,
    MemoryCandidateKind,
    MemoryRecallContext,
    MemoryStats,
    UserFeedbackRecord,
)

_DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "pricing": ("pricing", "price", "cost", "seat", "package", "费用", "价格", "定价"),
    "security": ("security", "sso", "saml", "soc", "iso", "scim", "安全", "合规"),
    "feature": ("feature", "capability", "workflow", "功能", "能力", "流程"),
    "persona": ("persona", "buyer", "customer", "user", "用户", "客户", "画像"),
    "integration": ("integration", "api", "ecosystem", "plugin", "集成", "生态"),
}
_SOURCE_KEYWORDS = (
    "official",
    "docs",
    "verified",
    "primary source",
    "source",
    "官网",
    "官方",
    "证据",
)
_DOMAIN_FACT_KEYWORDS = (
    "fact",
    "domain",
    "market",
    "category",
    "segment",
    "trend",
    "competitor",
    "customer",
    "buyer",
    "adoption",
    "benchmark",
)
_WRITING_KEYWORDS = (
    "concise",
    "table",
    "matrix",
    "battlecard",
    "executive",
    "简洁",
    "表格",
    "矩阵",
)
_RISK_KEYWORDS = (
    "risk",
    "unsupported",
    "evidence gap",
    "uncertain",
    "block",
    "风险",
    "不确定",
    "证据不足",
)

_FAILURE_KEYWORDS = (
    "failed",
    "failure",
    "regression",
    "retry",
    "redo",
    "re-run",
    "rerun",
    "blocked",
    "blocker",
    "defect",
)
_QA_POLICY_KEYWORDS = (
    "qa",
    "quality gate",
    "release gate",
    "policy",
    "must",
    "require",
    "threshold",
    "acceptance",
)


class PreferenceMemoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._memory_conn: sqlite3.Connection | None = None
        if str(self._db_path) == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_default_path(cls) -> PreferenceMemoryStore:
        return cls(Path("runs") / "preference_memory.db")

    @classmethod
    def in_memory(cls) -> PreferenceMemoryStore:
        return cls(Path(":memory:"))

    def add_feedback(
        self,
        feedback: UserFeedbackRecord,
        *,
        policy: CompliancePolicy | None = None,
    ) -> UserFeedbackRecord:
        redaction = redact_text(feedback.message, policy=policy)
        tags = _unique_tokens([*feedback.tags, *_infer_tags(redaction.text)])
        record = feedback.model_copy(
            update={
                "id": feedback.id or _feedback_id(feedback, redaction.text),
                "message": redaction.text,
                "tags": tags,
                "redaction_counts": {
                    key: value for key, value in redaction.counts.items() if value > 0
                },
            }
        )
        conn = self._connect()
        try:
            conn.execute(
                """
                insert into memory_feedback (id, workspace_id, project_id, record_json, created_at)
                values (?, ?, ?, ?, ?)
                on conflict(id) do update set
                    record_json = excluded.record_json
                """,
                (
                    record.id,
                    record.workspace_id,
                    record.project_id,
                    record.model_dump_json(),
                    record.created_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            self._close(conn)
        return record

    def list_feedback(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[UserFeedbackRecord]:
        where, params = _scope_where(workspace_id=workspace_id, project_id=project_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                select record_json from memory_feedback
                {where}
                order by created_at desc
                limit ?
                """,
                (*params, max(1, limit)),
            ).fetchall()
        finally:
            self._close(conn)
        return [UserFeedbackRecord.model_validate_json(row[0]) for row in rows]

    def extract_candidates(
        self,
        feedback: UserFeedbackRecord,
        *,
        auto_confirm: bool = False,
    ) -> list[MemoryCandidate]:
        tags = _unique_tokens([*feedback.tags, *_infer_tags(feedback.message)])
        candidates: list[MemoryCandidate] = []
        for dimension in sorted(set(tags) & set(_DIMENSION_KEYWORDS)):
            candidates.append(
                self._candidate(
                    feedback,
                    kind="preferred_dimension",
                    statement=(
                        f"Prioritize {dimension} evidence and analysis when this project "
                        "has similar scope."
                    ),
                    tags=[dimension],
                    weight=0.72,
                    confidence=0.78,
                    auto_confirm=auto_confirm,
                )
            )
        if _has_any(feedback.message, _DOMAIN_FACT_KEYWORDS) or "domain_fact" in tags:
            candidates.append(
                self._candidate(
                    feedback,
                    kind="domain_fact",
                    statement=(
                        "Remember this domain fact for similar analysis: "
                        f"{_memory_excerpt(feedback.message)}"
                    ),
                    tags=["domain_fact", *tags[:4]],
                    weight=0.76,
                    confidence=0.76,
                    auto_confirm=auto_confirm,
                )
            )
        if _has_any(feedback.message, _SOURCE_KEYWORDS) or "source" in tags:
            candidates.append(
                self._candidate(
                    feedback,
                    kind="source_preference",
                    statement=(
                        "Prefer official, fetched, or otherwise verified sources before "
                        "search-only leads."
                    ),
                    tags=["source", "verified"],
                    weight=0.82,
                    confidence=0.84,
                    auto_confirm=auto_confirm,
                )
            )
        if _has_any(feedback.message, _WRITING_KEYWORDS) or "writing" in tags:
            candidates.append(
                self._candidate(
                    feedback,
                    kind="writing_preference",
                    statement=(
                        "Use decision-ready tables, battlecard language, and concise "
                        "executive framing when writing the report."
                    ),
                    tags=["writing", "battlecard", "matrix"],
                    weight=0.7,
                    confidence=0.72,
                    auto_confirm=auto_confirm,
                )
            )
        if _has_any(feedback.message, _RISK_KEYWORDS) or feedback.feedback_type == "rejection":
            candidates.append(
                self._candidate(
                    feedback,
                    kind="risk_preference",
                    statement=(
                        "Flag unsupported recommendations and evidence gaps explicitly before "
                        "making a strong conclusion."
                    ),
                    tags=["risk", "evidence_gap"],
                    weight=0.8,
                    confidence=0.8,
                    auto_confirm=auto_confirm,
                )
            )
        if _has_any(feedback.message, _FAILURE_KEYWORDS) or feedback.feedback_type == "rejection":
            candidates.append(
                self._candidate(
                    feedback,
                    kind="failure_pattern",
                    statement=(
                        "Treat repeated blockers, redo requests, or quality regressions as "
                        "failure patterns to check before the next run is released."
                    ),
                    tags=["failure_pattern", "redo", *tags[:3]],
                    weight=0.84,
                    confidence=0.8,
                    auto_confirm=auto_confirm,
                )
            )
        if _has_any(feedback.message, _QA_POLICY_KEYWORDS):
            candidates.append(
                self._candidate(
                    feedback,
                    kind="qa_policy",
                    statement=(
                        "Apply this feedback as a QA policy: enforce explicit evidence, "
                        "release-gate thresholds, and reviewer-required checks before publish."
                    ),
                    tags=["qa_policy", "quality_gate", *tags[:3]],
                    weight=0.86,
                    confidence=0.82,
                    auto_confirm=auto_confirm,
                )
            )
        if feedback.feedback_type == "correction":
            candidates.append(
                self._candidate(
                    feedback,
                    kind="correction",
                    statement=(
                        f"Correction for {feedback.target_type}:{feedback.target_id or 'project'} "
                        f"- {feedback.message}"
                    ),
                    tags=["correction", *tags[:4]],
                    weight=0.88,
                    confidence=0.82,
                    auto_confirm=auto_confirm,
                )
            )
        return _dedupe_candidates(candidates)

    def upsert_candidate(self, candidate: MemoryCandidate) -> MemoryCandidate:
        existing = self.get_candidate(candidate.id)
        updated = candidate
        if existing is not None:
            updated = existing.model_copy(
                update={
                    "status": existing.status
                    if existing.status != "candidate"
                    else candidate.status,
                    "weight": min(1.0, max(existing.weight, candidate.weight) + 0.08),
                    "confidence": max(existing.confidence, candidate.confidence),
                    "source_feedback_ids": _unique_tokens(
                        [*existing.source_feedback_ids, *candidate.source_feedback_ids]
                    ),
                    "tags": _unique_tokens([*existing.tags, *candidate.tags]),
                    "used_count": max(existing.used_count, candidate.used_count),
                    "updated_at": datetime.utcnow(),
                    "metadata": {**existing.metadata, **candidate.metadata},
                }
            )
        conn = self._connect()
        try:
            conn.execute(
                """
                insert into memory_candidates (
                    id, workspace_id, project_id, status, record_json, updated_at
                )
                values (?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    status = excluded.status,
                    record_json = excluded.record_json,
                    updated_at = excluded.updated_at
                """,
                (
                    updated.id,
                    updated.workspace_id,
                    updated.project_id,
                    updated.status,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            self._close(conn)
        return updated

    def get_candidate(self, candidate_id: str) -> MemoryCandidate | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "select record_json from memory_candidates where id = ?",
                (candidate_id,),
            ).fetchone()
        finally:
            self._close(conn)
        if row is None:
            return None
        return MemoryCandidate.model_validate_json(row[0])

    def update_candidate_status(
        self,
        candidate_id: str,
        status: str,
    ) -> MemoryCandidate | None:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            return None
        updated = candidate.model_copy(update={"status": status, "updated_at": datetime.utcnow()})
        return self.upsert_candidate(updated)

    def recall(
        self,
        *,
        workspace_id: str,
        project_id: str,
        query: str = "",
        limit: int = 6,
        include_unconfirmed: bool = False,
        mark_used: bool = False,
    ) -> MemoryRecallContext:
        candidates = self._list_candidates(
            workspace_id=workspace_id,
            project_id=project_id,
            include_unconfirmed=include_unconfirmed,
        )
        query_tags = _unique_tokens(_infer_tags(query))
        ranked = sorted(
            (_score_candidate(candidate, query, query_tags) for candidate in candidates),
            key=lambda item: item.match_score,
            reverse=True,
        )[: max(1, limit)]
        if mark_used:
            ranked = [self._mark_used(candidate) for candidate in ranked]
        return MemoryRecallContext(
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            query_tags=query_tags,
            candidates=ranked,
            prompt_context=[_prompt_line(candidate) for candidate in ranked],
        )

    def stats(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> MemoryStats:
        where, params = _scope_where(workspace_id=workspace_id, project_id=project_id)
        conn = self._connect()
        try:
            feedback_count = conn.execute(
                f"select count(*) from memory_feedback {where}",
                params,
            ).fetchone()[0]
            candidate_count = conn.execute(
                f"select count(*) from memory_candidates {where}",
                params,
            ).fetchone()[0]
            confirmed_count = conn.execute(
                f"""
                select count(*) from memory_candidates
                {where + (" and " if where else " where ")} status = 'confirmed'
                """,
                params,
            ).fetchone()[0]
        finally:
            self._close(conn)
        return MemoryStats(
            workspace_id=workspace_id,
            project_id=project_id,
            feedback_count=int(feedback_count),
            candidate_count=int(candidate_count),
            confirmed_candidate_count=int(confirmed_count),
        )

    def _candidate(
        self,
        feedback: UserFeedbackRecord,
        *,
        kind: MemoryCandidateKind,
        statement: str,
        tags: list[str],
        weight: float,
        confidence: float,
        auto_confirm: bool,
    ) -> MemoryCandidate:
        return MemoryCandidate(
            id=_candidate_id(feedback.workspace_id, feedback.project_id, kind, statement),
            workspace_id=feedback.workspace_id,
            project_id=feedback.project_id,
            kind=kind,
            status="confirmed" if auto_confirm else "candidate",
            statement=statement,
            weight=weight,
            confidence=confidence,
            source_feedback_ids=[feedback.id],
            tags=_unique_tokens(tags),
            metadata={"target_type": feedback.target_type, "target_id": feedback.target_id},
        )

    def _list_candidates(
        self,
        *,
        workspace_id: str,
        project_id: str,
        include_unconfirmed: bool,
    ) -> list[MemoryCandidate]:
        status_clause = "" if include_unconfirmed else "and status = 'confirmed'"
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                select record_json from memory_candidates
                where workspace_id = ? and project_id = ? and status != 'archived'
                {status_clause}
                order by updated_at desc
                """,
                (workspace_id, project_id),
            ).fetchall()
        finally:
            self._close(conn)
        return [MemoryCandidate.model_validate_json(row[0]) for row in rows]

    def _mark_used(self, candidate: MemoryCandidate) -> MemoryCandidate:
        updated = candidate.model_copy(
            update={"used_count": candidate.used_count + 1, "updated_at": datetime.utcnow()}
        )
        return self.upsert_candidate(updated).model_copy(
            update={"match_score": candidate.match_score}
        )

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        return sqlite3.connect(self._db_path)

    def _close(self, conn: sqlite3.Connection) -> None:
        if conn is not self._memory_conn:
            conn.close()

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                create table if not exists memory_feedback (
                    id text primary key,
                    workspace_id text not null,
                    project_id text not null,
                    record_json text not null,
                    created_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists memory_candidates (
                    id text primary key,
                    workspace_id text not null,
                    project_id text not null,
                    status text not null,
                    record_json text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                "create index if not exists idx_memory_feedback_scope "
                "on memory_feedback(workspace_id, project_id, created_at)"
            )
            conn.execute(
                "create index if not exists idx_memory_candidates_scope "
                "on memory_candidates(workspace_id, project_id, status, updated_at)"
            )
            conn.commit()
        finally:
            self._close(conn)


def _feedback_id(feedback: UserFeedbackRecord, message: str) -> str:
    return compute_feedback_id(
        "|".join(
            [
                feedback.workspace_id,
                feedback.project_id,
                feedback.user_id,
                feedback.target_type,
                feedback.target_id,
            ]
        ),
        message.strip().casefold(),
    )


def _candidate_id(
    workspace_id: str,
    project_id: str,
    kind: MemoryCandidateKind,
    statement: str,
) -> str:
    return compute_memory_candidate_id(workspace_id, project_id, kind, statement.strip().casefold())


def _scope_where(
    *,
    workspace_id: str | None,
    project_id: str | None,
) -> tuple[str, tuple[str, ...]]:
    clauses: list[str] = []
    params: list[str] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    return ("where " + " and ".join(clauses) if clauses else ""), tuple(params)


def _infer_tags(text: str) -> list[str]:
    normalized = text.casefold()
    tags: list[str] = []
    for tag, keywords in _DIMENSION_KEYWORDS.items():
        if _has_any(normalized, keywords):
            tags.append(tag)
    if _has_any(normalized, _SOURCE_KEYWORDS):
        tags.append("source")
    if _has_any(normalized, _DOMAIN_FACT_KEYWORDS):
        tags.append("domain_fact")
    if _has_any(normalized, _WRITING_KEYWORDS):
        tags.append("writing")
    if _has_any(normalized, _RISK_KEYWORDS):
        tags.append("risk")
    return tags


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    normalized = text.casefold()
    return any(keyword.casefold() in normalized for keyword in keywords)


def _memory_excerpt(text: str, limit: int = 220) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


def _unique_tokens(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        token = re.sub(r"\s+", "_", str(value).strip().casefold())
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def _dedupe_candidates(candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
    seen: set[str] = set()
    result: list[MemoryCandidate] = []
    for candidate in candidates:
        if candidate.id in seen:
            continue
        seen.add(candidate.id)
        result.append(candidate)
    return result


def _score_candidate(
    candidate: MemoryCandidate,
    query: str,
    query_tags: list[str],
) -> MemoryCandidate:
    normalized_query = query.casefold()
    tag_overlap = len(set(candidate.tags) & set(query_tags))
    text_overlap = sum(1 for tag in candidate.tags if tag and tag in normalized_query)
    status_bonus = 0.12 if candidate.status == "confirmed" else 0.0
    source_bonus = min(0.12, len(candidate.source_feedback_ids) * 0.03)
    score = min(
        1.0,
        candidate.weight * 0.55
        + candidate.confidence * 0.25
        + min(0.18, (tag_overlap + text_overlap) * 0.06)
        + status_bonus
        + source_bonus,
    )
    return candidate.model_copy(update={"match_score": round(score, 3)})


def _prompt_line(candidate: MemoryCandidate) -> str:
    label = candidate.kind.replace("_", " ")
    return f"[{label}; weight={candidate.weight:.2f}] {candidate.statement}"
