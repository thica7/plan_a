from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from packages.agents import SubagentContext
from packages.identity import compute_raw_source_id
from packages.knowledge.models import KnowledgeScope, RetrievalHit, RetrievalRequest
from packages.memory.report_reuse import FACT_TTL_DAYS, PRICE_VERSION_TTL_DAYS
from packages.research.evidence.admission import capture_fact_verification_time
from packages.research.models import ResearchResult
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

    @staticmethod
    def _kb_scope(detail: RunDetail) -> KnowledgeScope:
        return KnowledgeScope(
            workspace_id=detail.workspace_id,
            project_id=detail.project_id,
            include_workspace_library=True,
        )

    @staticmethod
    def _kb_market(detail: RunDetail) -> str | None:
        product = detail.plan.target_product
        return product.market.strip() or None if product is not None else None

    @staticmethod
    def _kb_max_age_days(dimension: str) -> int:
        return (
            PRICE_VERSION_TTL_DAYS
            if any(
                term in dimension.casefold() for term in ("pric", "version", "版本", "价格", "定价")
            )
            else FACT_TTL_DAYS
        )

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
            **self._kb_scope(detail).model_dump(),
            "market": self._kb_market(detail),
            "source_roles": ["source"],
            "max_age_days": self._kb_max_age_days(dimension),
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
            if rejection_reason is None:
                rejection_reason = self._kb_scoped_hit_rejection_reason(hit, request)
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
            retrieved_keys = getattr(record, "_kb_retrieved_source_keys", None)
            if retrieved_keys is None:
                retrieved_keys = record._kb_retrieved_source_keys = set()
            retrieved_keys.add(self._kb_retrieved_source_key(source))
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
    def _kb_retrieved_source_key(source: RawSource) -> tuple[str, str, str, str]:
        return (
            source.id,
            str(source.metadata.get("kb_document_id") or ""),
            str(source.metadata.get("kb_document_version") or ""),
            str(source.metadata.get("kb_document_content_hash") or ""),
        )

    @staticmethod
    def _kb_scoped_hit_rejection_reason(
        hit: dict[str, object],
        request: dict[str, object],
    ) -> str | None:
        try:
            typed = RetrievalHit.model_validate(hit)
            expected = RetrievalRequest.model_validate(request)
        except ValueError:
            return "invalid_scoped_hit"
        scope = expected.scope
        if scope is None or typed.workspace_id != scope.workspace_id:
            return "wrong_workspace"
        if typed.project_id not in {scope.project_id, None}:
            return "wrong_project"
        if (typed.competitor or "").casefold() != expected.competitors[0].casefold():
            return "wrong_competitor"
        if (typed.dimension or "").casefold() != expected.dimensions[0].casefold():
            return "wrong_dimension"
        if expected.market is not None and typed.market != expected.market:
            return "wrong_market"
        if typed.source_role != "source" or typed.source_type == "report":
            return "wrong_source_role"
        if typed.status != "active":
            return "inactive_document"
        if typed.document_version < 1 or not typed.content_hash:
            return "missing_document_reference"
        observed = (typed.last_verified_at or typed.source_updated_at
                    or typed.source_published_at or typed.fetched_at)
        if observed is None:
            return "missing_source_time"
        now = datetime.now(UTC)
        observed = observed.replace(tzinfo=UTC) if observed.tzinfo is None else observed
        if observed > now:
            return "future_source_time"
        if observed < now - timedelta(days=expected.max_age_days or 0):
            return "expired_source"
        return None

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
        if detail.plan.target_product is not None:
            return self._web_search_query(detail, competitor, dimension)
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
        content_hash = str(hit_metadata.get("capture_content_hash") or content_hash)
        confidence_value = hit_metadata.get("collector_confidence")
        if confidence_value is None:
            confidence_value = hit_metadata.get("kb_collector_confidence")
        stored_confidence = _metadata_number(confidence_value)
        confidence = min(
            0.75, max(0.0, stored_confidence if stored_confidence is not None else 0.6)
        )
        metadata = {
            "kb_retrieved": True,
            "kb_retrieval_query": query,
            "kb_document_id": str(hit.get("document_id") or ""),
            "kb_document_workspace_id": hit.get("workspace_id"),
            "kb_document_project_id": hit.get("project_id"),
            "kb_document_version": hit.get("document_version"),
            "kb_document_content_hash": hit.get("content_hash"),
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
        for field, target in (
            ("fetched_at", "source_fetched_at"),
            ("source_published_at", "source_published_at"),
            ("source_updated_at", "source_updated_at"),
            ("last_verified_at", "last_verified_at"),
        ):
            if hit.get(field):
                metadata[target] = str(hit[field])
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
                extracted_at=_source_datetime(hit.get("fetched_at")) or datetime.now(UTC),
            )
        except Exception:
            return None

    async def _persist_captured_sources_to_kb(
        self,
        record: RunRecord | None,
        detail: RunDetail,
        sources: list[RawSource],
        result: ResearchResult,
        context: SubagentContext | None = None,
    ) -> None:
        from packages.tools.ingest_document import ingest_document_reference

        diagnostics: list[dict[str, object]] = []
        failures = getattr(record, "_kb_capture_ingest_failures", None)
        if failures is None:
            failures = set()
            if record is not None:
                record._kb_capture_ingest_failures = failures
        for source in sources:
            failure_key = (detail.id, detail.workspace_id, detail.project_id, source.id)
            failures.add(failure_key)
            capture_hash = str(source.metadata.get("capture_content_hash") or "").strip()
            pages = [
                page
                for page in result.captured_pages
                if page.id == source.metadata.get("captured_page_id")
                and page.final_url.rstrip("/") == str(source.url or "").rstrip("/")
                and capture_hash
                and page.content_hash.strip() == capture_hash
                and _source_datetime(source.metadata.get("fetched_at"))
                == _source_datetime(page.captured_at)
            ]
            source.metadata["kb_full_source_ingest_status"] = "failed"
            if (
                len(pages) != 1
                or pages[0].status != "ok"
                or pages[0].failure_reason
                or source.failure_reason
                or source.source_type.casefold() not in KB_INGEST_ALLOWED_SOURCE_TYPES
                or not (pages[0].text.strip() or pages[0].markdown.strip())
            ):
                diagnostics.append(
                    {"source_id": source.id, "error": "capture_identity_or_status_invalid"}
                )
                continue
            page = pages[0]
            captured_at = _source_datetime(page.captured_at)
            try:
                reference = await ingest_document_reference(
                    url=str(source.url),
                    title=source.title or page.title,
                    text=page.text if page.text.strip() else page.markdown,
                    markdown=page.markdown,
                    competitor=source.competitor,
                    dimension=source.dimension,
                    source_type=source.source_type,
                    workspace_id=detail.workspace_id,
                    project_id=detail.project_id,
                    market=self._kb_market(detail),
                    source_role="source",
                    fetched_at=captured_at,
                    last_verified_at=capture_fact_verification_time(
                        source.dimension, captured_at,
                        source_published_at=source.metadata.get("source_published_at"),
                        source_updated_at=source.metadata.get("source_updated_at"),
                    ),
                    source_published_at=_source_datetime(
                        source.metadata.get("source_published_at")
                    ),
                    source_updated_at=_source_datetime(source.metadata.get("source_updated_at")),
                    metadata={
                        **source.metadata,
                        "source_material_level": "full_source",
                        "run_id": detail.id,
                        "raw_source_id": source.id,
                        "collector_confidence": source.confidence,
                        "collector_candidate_origin": source.candidate_origin,
                        "collector_fetch_method": source.fetch_method,
                    },
                    crawl_run_id=detail.id,
                    index_vectors=False,
                )
                source.metadata.update(
                    kb_document_id=reference["document_id"],
                    kb_document_workspace_id=reference["workspace_id"],
                    kb_document_project_id=reference["project_id"],
                    kb_document_version=reference["document_version"],
                    kb_document_content_hash=reference["content_hash"],
                    kb_fetched_at=reference["fetched_at"],
                    kb_last_verified_at=reference["last_verified_at"],
                    kb_source_updated_at=reference["source_updated_at"],
                    kb_full_source_ingest_status="stored",
                )
                failures.discard(failure_key)
                diagnostics.append(
                    {"source_id": source.id, "document_id": reference["document_id"]}
                )
            except Exception as exc:  # noqa: BLE001 - persistence must not block true evidence.
                diagnostics.append({"source_id": source.id, "error": str(exc)[:160]})
        if record is not None and diagnostics:
            self._trace_local_tool(
                record,
                agent="collector",
                subagent=context.subagent if context else "collector",
                name="kb_ingest_captured_sources",
                input_text=json.dumps({"source_ids": [s.id for s in sources]}),
                output_text=json.dumps({"results": diagnostics}, ensure_ascii=False),
                context=context,
                metadata={
                    "source_count": len(sources),
                    "errors": sum("error" in d for d in diagnostics),
                },
            )

    async def _full_source_reference_is_valid(
        self,
        detail: RunDetail,
        source: RawSource,
        *,
        require_full: bool = True,
    ) -> bool:
        from packages.knowledge.repository import KnowledgeRepository

        async with KnowledgeRepository() as repo:
            doc = await repo.get_document(
                str(source.metadata.get("kb_document_id") or ""), scope=self._kb_scope(detail)
            )
        return bool(
            doc
            and doc.is_active
            and doc.status == "active"
            and doc.workspace_id == detail.workspace_id
            and (not require_full or doc.project_id == detail.project_id)
            and doc.competitor == source.competitor
            and doc.dimension == source.dimension
            and doc.market == self._kb_market(detail)
            and doc.source_role == "source"
            and doc.version == source.metadata.get("kb_document_version")
            and doc.content_hash == source.metadata.get("kb_document_content_hash")
            and (doc.url or "").rstrip("/") == str(source.url or "").rstrip("/")
            and (not require_full or doc.metadata.get("source_material_level") == "full_source")
        )

    async def _has_stored_full_source(self, detail: RunDetail, source: RawSource) -> bool:
        from packages.knowledge.repository import KnowledgeRepository

        # Legacy/manual evidence can lack references; check existing material before replacement.
        scope = KnowledgeScope(workspace_id=detail.workspace_id, project_id=detail.project_id)
        async with KnowledgeRepository() as repo:
            return await repo.has_active_full_source_for_url(
                str(source.url or ""),
                scope=scope,
                competitor=source.competitor,
                dimension=source.dimension,
                market=self._kb_market(detail),
            )

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
            if (detail.id, detail.workspace_id, detail.project_id, source.id) in getattr(
                record, "_kb_capture_ingest_failures", set()
            ):
                skipped.append({"source_id": source.id, "reason": "full_source_ingest_failed"})
                continue
            if source.metadata.get("kb_document_id"):
                retrieved = self._kb_retrieved_source_key(source) in getattr(
                    record, "_kb_retrieved_source_keys", set()
                )
                try:
                    valid = await self._full_source_reference_is_valid(
                        detail,
                        source,
                        require_full=not retrieved,
                    )
                except Exception as exc:  # noqa: BLE001 - never replace full text on lookup failure.
                    errors.append(f"{source.id}: {str(exc)[:160]}")
                    skipped.append({"source_id": source.id, "reason": "full_source_lookup_failed"})
                    continue
                if valid:
                    skipped.append(
                        {
                            "source_id": source.id,
                            "reason": "already_from_kb"
                            if retrieved
                            else "full_source_already_stored",
                        }
                    )
                    continue
                for field in ("kb_document_id", "kb_document_version", "kb_document_content_hash"):
                    source.metadata.pop(field, None)
            source.metadata.pop("kb_retrieved", None)
            source.metadata.pop("kb_full_source_ingest_status", None)
            text = self._kb_text_from_raw_source(source)
            skip_reason = self._kb_ingest_skip_reason(source, text)
            if skip_reason:
                skipped.append({"source_id": source.id, "reason": skip_reason})
                continue
            try:
                if await self._has_stored_full_source(detail, source):
                    skipped.append({"source_id": source.id, "reason": "full_source_already_stored"})
                    continue
            except Exception as exc:  # noqa: BLE001 - lookup failure must not replace full material.
                errors.append(f"{source.id}: {str(exc)[:160]}")
                skipped.append({"source_id": source.id, "reason": "full_source_lookup_failed"})
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
                        "workspace_id": detail.workspace_id,
                        "project_id": detail.project_id,
                        "market": self._kb_market(detail),
                        "source_role": "source",
                        "fetched_at": _source_datetime(source.metadata.get("fetched_at"))
                        or _source_datetime(source.extracted_at),
                        "source_published_at": _source_datetime(
                            source.metadata.get("source_published_at")
                        ),
                        "source_updated_at": _source_datetime(
                            source.metadata.get("source_updated_at")
                        ),
                        "last_verified_at": _source_datetime(
                            source.metadata.get("last_verified_at")
                        ),
                        "metadata": {
                            **source.metadata,
                            "run_id": detail.id,
                            "raw_source_id": source.id,
                            "collector_confidence": source.confidence,
                            "collector_candidate_origin": source.candidate_origin,
                            "collector_fetch_method": source.fetch_method,
                            "source_material_level": "summary",
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
        return "\n\n".join(
            part.strip() for part in pieces if isinstance(part, str) and part.strip()
        )

    def _kb_ingest_skip_reason(self, source: RawSource, text: str) -> str:
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


def _source_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result
