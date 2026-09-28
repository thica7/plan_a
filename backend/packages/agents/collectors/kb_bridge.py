from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from packages.agents import SubagentContext
from packages.identity import compute_raw_source_id
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


def _metadata_number(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


KB_INGEST_ALLOWED_SOURCE_TYPES = {
    "official",
    "official_site",
    "official_docs",
    "official_pricing",
    "official_api",
    "trust_center",
    "webpage_verified",
    "verified_webpage",
    "verified_document",
    "review_site",
    "manual_transcript",
    "manual_note",
    "manual",
}


class CollectorKBBridgeMixin:
    """Convert KB chunks to collector sources and persist accepted collector evidence."""

    async def _collect_competitor_from_kb(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
        *,
        target_source_count: int,
    ) -> list[RawSource]:
        query = self._kb_retrieval_query(detail, competitor, dimension)
        request = {
            "query": query,
            "competitors": [competitor],
            "dimensions": [dimension],
            "top_k": max(target_source_count * 3, 5),
            "mode": "sparse",
        }
        try:
            from packages.tools.rag_retrieve import rag_retrieve_tool

            raw_hits = await rag_retrieve_tool.ainvoke(request)
        except Exception as exc:  # noqa: BLE001 - KB reuse is a warm-start, not a hard dependency.
            self._trace_local_tool(
                record,
                agent="collector",
                subagent=context.subagent,
                name="rag_kb_warm_start",
                input_text=json.dumps(request, ensure_ascii=False),
                output_text=json.dumps({"error": str(exc), "degraded": True}, ensure_ascii=False),
                context=context,
                metadata={"degraded": True, "source_count": 0},
            )
            return []

        hits = raw_hits if isinstance(raw_hits, list) else []
        sources: list[RawSource] = []
        rejections: list[dict[str, object]] = []
        for rank, hit in enumerate(hits):
            if not isinstance(hit, dict):
                rejections.append({"rank": rank, "reason": "invalid_hit"})
                continue
            rejection_reason = self._kb_hit_rejection_reason(hit)
            if rejection_reason is not None:
                rejections.append(
                    self._kb_hit_rejection_diagnostic(
                        hit,
                        rank=rank,
                        reason=rejection_reason,
                    )
                )
                continue
            source = self._raw_source_from_kb_hit(
                detail,
                competitor,
                dimension,
                hit,
                rank=rank,
                query=query,
            )
            if source is None:
                rejections.append(
                    self._kb_hit_rejection_diagnostic(
                        hit,
                        rank=rank,
                        reason="raw_source_build_failed",
                    )
                )
                continue
            if self._candidate_already_collected(
                detail,
                sources,
                competitor=competitor,
                dimension=dimension,
                url=str(source.url) if source.url else None,
            ):
                rejections.append(
                    self._kb_hit_rejection_diagnostic(
                        hit,
                        rank=rank,
                        reason="duplicate_source",
                        source_id=source.id,
                    )
                )
                continue
            problem = self._source_quality_problem(source)
            if problem is not None:
                rejections.append(
                    self._kb_hit_rejection_diagnostic(
                        hit,
                        rank=rank,
                        reason="source_quality_problem",
                        source_id=source.id,
                        detail=problem,
                    )
                )
                continue
            sources.append(source)
            if len(sources) >= target_source_count:
                break

        self._trace_local_tool(
            record,
            agent="collector",
            subagent=context.subagent,
            name="rag_kb_warm_start",
            input_text=json.dumps(request, ensure_ascii=False),
            output_text=json.dumps(
                {
                    "hit_count": len(hits),
                    "source_ids": [source.id for source in sources],
                    "rejections": rejections[:8],
                },
                ensure_ascii=False,
            ),
            context=context,
            metadata={
                "hit_count": len(hits),
                "source_count": len(sources),
                "rejection_count": len(rejections),
                "top_rejection_reason": self._top_kb_rejection_reason(rejections),
            },
        )
        return sources

    @staticmethod
    def _kb_hit_rejection_reason(hit: dict[str, object]) -> str | None:
        text = str(hit.get("text") or "").strip()
        url = str(hit.get("url") or "").strip()
        source_type = str(hit.get("source_type") or "webpage_verified").strip()
        if not text:
            return "missing_text"
        if not url:
            return "missing_url"
        if not url.startswith(("http://", "https://")):
            return "non_http_url"
        if source_type in {"llm_public_knowledge", "web_search_result"}:
            return "disallowed_source_type"
        return None

    @staticmethod
    def _kb_hit_rejection_diagnostic(
        hit: dict[str, object],
        *,
        rank: int,
        reason: str,
        source_id: str | None = None,
        detail: str | None = None,
    ) -> dict[str, object]:
        diagnostic: dict[str, object] = {"rank": rank, "reason": reason}
        field_map = {
            "document_id": "document_id",
            "chunk_id": "chunk_id",
            "source_type": "source_type",
            "url": "url",
            "title": "title",
            "status": "status",
            "competitor": "competitor",
            "dimension": "dimension",
        }
        for source_key, target_key in field_map.items():
            value = hit.get(source_key)
            if value not in (None, ""):
                diagnostic[target_key] = str(value)
        score = _metadata_number(hit.get("rerank_score"))
        if score is None:
            score = _metadata_number(hit.get("score"))
        if score is not None:
            diagnostic["score"] = score
        if source_id:
            diagnostic["source_id"] = source_id
        if detail:
            diagnostic["detail"] = detail[:300]
        hit_metadata = hit.get("metadata")
        if isinstance(hit_metadata, dict):
            raw_source_id = hit_metadata.get("raw_source_id") or hit_metadata.get(
                "kb_raw_source_id"
            )
            collector_run_id = hit_metadata.get("run_id") or hit_metadata.get("kb_collector_run_id")
            if raw_source_id not in (None, ""):
                diagnostic["kb_raw_source_id"] = str(raw_source_id)
            if collector_run_id not in (None, ""):
                diagnostic["kb_collector_run_id"] = str(collector_run_id)
        return diagnostic

    @staticmethod
    def _top_kb_rejection_reason(rejections: list[dict[str, object]]) -> str | None:
        counts: dict[str, int] = {}
        for item in rejections:
            reason = str(item.get("reason") or "").strip()
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda item: item[1])[0]

    @staticmethod
    def _copy_kb_source_metadata(
        metadata: dict[str, object],
        hit_metadata: dict[str, Any],
    ) -> None:
        key_map = {
            "raw_source_id": "kb_raw_source_id",
            "kb_raw_source_id": "kb_raw_source_id",
            "run_id": "kb_collector_run_id",
            "collector_run_id": "kb_collector_run_id",
            "kb_collector_run_id": "kb_collector_run_id",
            "collector_candidate_origin": "kb_collector_candidate_origin",
            "kb_collector_candidate_origin": "kb_collector_candidate_origin",
            "collector_fetch_method": "kb_collector_fetch_method",
            "kb_collector_fetch_method": "kb_collector_fetch_method",
            "source_published_at": "source_published_at",
            "published_at": "source_published_at",
            "source_updated_at": "source_updated_at",
            "updated_at": "source_updated_at",
            "last_verified_at": "last_verified_at",
            "fetched_at": "source_fetched_at",
        }
        for source_key, target_key in key_map.items():
            value = hit_metadata.get(source_key)
            if value not in (None, "") and target_key not in metadata:
                metadata[target_key] = str(value)
        confidence = hit_metadata.get("collector_confidence")
        if confidence is None:
            confidence = hit_metadata.get("kb_collector_confidence")
        if confidence is not None:
            metadata["kb_collector_confidence"] = confidence

    def _kb_retrieval_query(self, detail: RunDetail, competitor: str, dimension: str) -> str:
        skill = self._skill_registry.get(dimension)
        parts = [
            self._web_search_query(detail, competitor, dimension),
            detail.topic,
            competitor,
            dimension,
            skill.description if skill is not None else "",
        ]
        seen: set[str] = set()
        terms: list[str] = []
        for part in parts:
            value = " ".join(str(part).split())
            key = value.casefold()
            if not value or key in seen:
                continue
            seen.add(key)
            terms.append(value)
        return " ".join(terms)

    def _raw_source_from_kb_hit(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        hit: dict[str, object],
        *,
        rank: int,
        query: str,
    ) -> RawSource | None:
        text = str(hit.get("text") or "").strip()
        url = str(hit.get("url") or "").strip()
        if not text or not url.startswith(("http://", "https://")):
            return None
        source_type = (
            str(hit.get("source_type") or "webpage_verified").strip() or "webpage_verified"
        )
        if source_type in {"llm_public_knowledge", "web_search_result"}:
            return None
        title = str(hit.get("title") or f"{competitor} {dimension} KB evidence").strip()
        snippet = self._dimension_evidence_snippet(text, dimension, text[:1000])
        content_hash = (
            str(hit.get("content_hash") or "").strip()
            or hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        )
        score = self._coerce_confidence(
            hit.get("rerank_score") if hit.get("rerank_score") is not None else hit.get("score"),
            default=0.5,
        )
        hit_metadata = hit.get("metadata")
        if not isinstance(hit_metadata, dict):
            hit_metadata = {}
        stored_confidence = _metadata_number(
            hit_metadata.get("collector_confidence")
            or hit_metadata.get("kb_collector_confidence")
        )
        confidence = min(0.75, max(0.3, stored_confidence if stored_confidence is not None else 0.6))
        metadata = {
            "kb_retrieved": True,
            "kb_retrieval_query": query,
            "kb_document_id": str(hit.get("document_id") or ""),
            "kb_chunk_id": str(hit.get("chunk_id") or ""),
            "kb_hit_score": score,
            "kb_rerank_score": hit.get("rerank_score"),
            "kb_source_type": source_type,
            "kb_competitor": str(hit.get("competitor") or ""),
            "kb_dimension": str(hit.get("dimension") or ""),
            "kb_document_status": str(hit.get("status") or "active"),
            "kb_fetched_at": str(hit.get("fetched_at") or ""),
            "kb_last_seen_at": str(hit.get("last_seen_at") or ""),
            "source_material_level": "kb_retrieval_chunk",
            "kb_confidence_policy": "reuse_requires_current_verification",
        }
        self._copy_kb_source_metadata(metadata, hit_metadata)
        try:
            return RawSource(
                id=compute_raw_source_id(
                    source_type=source_type,
                    competitor=competitor,
                    dimension=dimension,
                    url=url,
                    content_hash=content_hash,
                    title=title,
                    snippet=snippet,
                    run_id=detail.id,
                    source_role="kb-retrieved",
                ),
                competitor=competitor,
                dimension=dimension,
                source_type=source_type,
                title=title,
                url=url,
                snippet=snippet,
                content_hash=content_hash,
                confidence=confidence,
                candidate_origin="rag_kb",
                candidate_rank=rank,
                candidate_confidence=score,
                fetch_method="rag_kb_retrieve",
                quality_score=confidence,
                metadata=metadata,
            )
        except Exception:
            return None

    async def _sync_collected_sources_to_kb(
        self,
        record: RunRecord,
        detail: RunDetail,
        sources: list[RawSource],
        context: SubagentContext | None = None,
    ) -> dict[str, object]:
        try:
            from packages.tools.ingest_document import ingest_document_tool
        except Exception as exc:  # noqa: BLE001 - KB persistence is non-blocking.
            return {"attempted": 0, "ingested": 0, "error": str(exc)}

        attempted = 0
        ingested = 0
        skipped: list[dict[str, str]] = []
        errors: list[str] = []
        for source in sources:
            text = self._kb_text_from_raw_source(source)
            skip_reason = self._kb_ingest_skip_reason(source, text)
            if skip_reason:
                skipped.append({"source_id": source.id, "reason": skip_reason})
                continue
            attempted += 1
            try:
                await ingest_document_tool.ainvoke(
                    {
                        "url": str(source.url) if source.url else "",
                        "title": source.title or source.id,
                        "text": text[:50000],
                        "competitor": source.competitor or "",
                        "dimension": source.dimension or "",
                        "source_type": source.source_type or "webpage_verified",
                        "metadata": {
                            **source.metadata,
                            "run_id": detail.id,
                            "raw_source_id": source.id,
                            "collector_confidence": source.confidence,
                            "collector_candidate_origin": source.candidate_origin,
                            "collector_fetch_method": source.fetch_method,
                        },
                        "crawl_run_id": detail.id,
                        "index_vectors": False,
                    }
                )
                ingested += 1
            except Exception as exc:  # noqa: BLE001 - one bad KB write must not block the run.
                errors.append(f"{source.id}: {str(exc)[:160]}")

        summary: dict[str, object] = {
            "attempted": attempted,
            "ingested": ingested,
            "skipped": skipped[:12],
            "errors": errors[:5],
        }
        self._trace_local_tool(
            record,
            agent="collect_join",
            subagent="collect_join",
            name="kb_ingest_collected_sources",
            input_text=json.dumps(
                {"source_ids": [source.id for source in sources]}, ensure_ascii=False
            ),
            output_text=json.dumps(summary, ensure_ascii=False),
            context=context,
            metadata={
                "attempted": attempted,
                "ingested": ingested,
                "skipped": len(skipped),
                "errors": len(errors),
            },
        )
        return summary

    def _kb_text_from_raw_source(self, source: RawSource) -> str:
        pieces = [source.title, source.snippet]
        full_text = source.metadata.get("full_text")
        if isinstance(full_text, str):
            pieces.append(full_text)
        return "\n\n".join(
            part.strip() for part in pieces if isinstance(part, str) and part.strip()
        )

    def _kb_ingest_skip_reason(self, source: RawSource, text: str) -> str:
        if source.metadata.get("kb_retrieved"):
            return "already_from_kb"
        if not source.url:
            return "missing_url"
        if source.source_type.casefold() not in KB_INGEST_ALLOWED_SOURCE_TYPES:
            return "source_type_not_allowlisted"
        if source.failure_reason:
            return "failed_source"
        if source.confidence < 0.75:
            return "low_confidence"
        if len(text.strip()) < 40:
            return "text_too_short"
        if self._source_quality_problem(source) is not None:
            return "source_quality_problem"
        return ""
