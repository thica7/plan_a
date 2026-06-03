from __future__ import annotations

import hashlib
import re
from pathlib import Path
from collections.abc import Iterable
from typing import Protocol

from pydantic import ValidationError

from packages.schema.enterprise import (
    EvidenceRecord,
    EvidenceReindexResult,
    EvidenceSeedIngestResult,
    EvidenceSeedRow,
)

DEFAULT_EVIDENCE_SEED_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "evidence_seed.jsonl"
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class EvidenceSeedStore(Protocol):
    def upsert_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord: ...

    def reindex_evidence_embeddings(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> EvidenceReindexResult: ...


def load_evidence_seed_rows(
    path: str | Path = DEFAULT_EVIDENCE_SEED_PATH,
) -> list[EvidenceSeedRow]:
    seed_path = Path(path)
    rows: list[EvidenceSeedRow] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(seed_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = EvidenceSeedRow.model_validate_json(line)
        except ValidationError as exc:
            raise ValueError(f"Invalid evidence seed row at line {line_number}") from exc
        if row.id in seen_ids:
            raise ValueError(f"Duplicate evidence seed id: {row.id}")
        seen_ids.add(row.id)
        rows.append(row)
    if not rows:
        raise ValueError(f"Evidence seed corpus is empty: {seed_path}")
    return rows


def filter_evidence_seed_rows(
    rows: list[EvidenceSeedRow],
    *,
    topic: str | None = None,
    competitors: list[str] | None = None,
    dimensions: list[str] | None = None,
    limit: int | None = None,
) -> list[EvidenceSeedRow]:
    competitor_keys = {_normalize_key(item) for item in competitors or [] if item.strip()}
    dimension_keys = {_normalize_key(item) for item in dimensions or [] if item.strip()}
    matched = [
        row
        for row in rows
        if _topic_matches(row.topic, topic)
        and (not competitor_keys or _normalize_key(row.competitor) in competitor_keys)
        and (not dimension_keys or _normalize_key(row.dimension) in dimension_keys)
    ]
    return matched[:limit] if limit is not None else matched


def ingest_evidence_seed_corpus(
    *,
    store: EvidenceSeedStore,
    workspace_id: str,
    project_id: str,
    topic: str | None = None,
    competitors: list[str] | None = None,
    dimensions: list[str] | None = None,
    run_id: str | None = None,
    limit: int | None = None,
    competitor_id_map: dict[str, str] | None = None,
    path: str | Path = DEFAULT_EVIDENCE_SEED_PATH,
) -> EvidenceSeedIngestResult:
    rows = load_evidence_seed_rows(path)
    matched = filter_evidence_seed_rows(
        rows,
        topic=topic,
        competitors=competitors,
        dimensions=dimensions,
        limit=limit,
    )
    evidence = [
        seed_row_to_evidence_record(
            row,
            workspace_id=workspace_id,
            project_id=project_id,
            run_id=run_id,
            competitor_id_map=competitor_id_map or {},
        )
        for row in matched
    ]
    stored = [store.upsert_evidence(item) for item in evidence]
    reindex = store.reindex_evidence_embeddings(
        workspace_id=workspace_id,
        project_id=project_id,
    )
    return EvidenceSeedIngestResult(
        workspace_id=workspace_id,
        project_id=project_id,
        seed_path=str(Path(path).resolve()),
        loaded_count=len(rows),
        matched_count=len(matched),
        ingested_count=len(stored),
        indexed_count=reindex.indexed_count,
        duplicate_count=reindex.duplicate_count,
        evidence_ids=[item.id for item in stored],
        topics=_sorted_unique(row.topic for row in matched),
        competitors=_sorted_unique(row.competitor for row in matched),
        dimensions=_sorted_unique(row.dimension for row in matched),
    )


def seed_row_to_evidence_record(
    row: EvidenceSeedRow,
    *,
    workspace_id: str,
    project_id: str,
    run_id: str | None = None,
    competitor_id_map: dict[str, str] | None = None,
) -> EvidenceRecord:
    source_url = str(row.url) if row.url else ""
    title = f"{row.competitor} {row.dimension} seed source"
    snippet = (
        f"Seed evidence for {row.topic}: {row.competitor} {row.dimension} source "
        f"from {row.source_type} with reliability {row.reliability:.2f}."
    )
    if source_url:
        snippet = f"{snippet} URL: {source_url}."
    full_text = (
        f"{snippet} Topic={row.topic}. Competitor={row.competitor}. "
        f"Dimension={row.dimension}. Source type={row.source_type}."
    )
    return EvidenceRecord(
        id=_stable_evidence_id(workspace_id, project_id, row.id),
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id or "seed-corpus",
        raw_source_id=f"raw-{row.id}",
        competitor_id=_competitor_id(row.competitor, competitor_id_map or {}),
        dimension=row.dimension,
        source_type=row.source_type,
        title=title,
        url=row.url,
        canonical_url=source_url,
        snippet=snippet,
        content_hash=_content_hash(row),
        reliability_score=row.reliability,
        freshness_score=max(0.5, min(row.reliability, 0.9)),
        quality_label="accepted" if row.reliability >= 0.8 else "unreviewed",
        metadata={
            "seed_corpus": True,
            "seed_id": row.id,
            "seed_topic": row.topic,
            "seed_competitor": row.competitor,
            "seed_dimension": row.dimension,
            "source_material_level": "url_seed",
            "full_text": full_text,
            "robots_status": "unknown",
        },
    )


def _stable_evidence_id(workspace_id: str, project_id: str, seed_id: str) -> str:
    digest = hashlib.sha256(f"{workspace_id}|{project_id}|{seed_id}".encode()).hexdigest()
    return f"evidence-seed-{digest[:20]}"


def _content_hash(row: EvidenceSeedRow) -> str:
    raw = "|".join(
        [
            row.id,
            row.topic,
            row.competitor,
            row.dimension,
            row.source_type,
            str(row.url or ""),
            f"{row.reliability:.4f}",
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _competitor_id(competitor: str, competitor_id_map: dict[str, str]) -> str:
    key = _normalize_key(competitor)
    return competitor_id_map.get(key) or f"competitor-seed-{key}"


def _topic_matches(seed_topic: str, requested_topic: str | None) -> bool:
    if not requested_topic or not requested_topic.strip():
        return True
    seed_key = _normalize_key(seed_topic)
    requested_key = _normalize_key(requested_topic)
    if seed_key in requested_key or requested_key in seed_key:
        return True
    seed_tokens = set(_TOKEN_RE.findall(seed_key))
    requested_tokens = set(_TOKEN_RE.findall(requested_key))
    return bool(seed_tokens) and seed_tokens.issubset(requested_tokens)


def _normalize_key(value: str) -> str:
    tokens = _TOKEN_RE.findall(value.casefold())
    return "-".join(tokens)


def _sorted_unique(values: Iterable[str]) -> list[str]:
    return sorted({str(item) for item in values})
