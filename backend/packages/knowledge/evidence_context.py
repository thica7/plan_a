"""Bounded, verifiable source context around immutable retrieval anchors."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .models import KnowledgeChunk, KnowledgeDocument, RetrievalHit

CONTEXT_PIPELINE_VERSION = "evidence-context-v1"
MAX_CONTEXT_CHARS = 3000
MAX_REQUEST_ADDITIONAL_CHARS = 6000
_SOURCE_FIELDS = ("document_id", "document_version", "content_hash", "workspace_id",
                  "project_id", "competitor", "dimension", "market", "source_role", "source_type")
_METHODS = {"document_parent", "section_parent", "adjacent_chunks"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _data(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else value.model_dump()


def _source(hit: Mapping[str, Any]) -> dict[str, Any]:
    return {field: hit.get(field) for field in _SOURCE_FIELDS}


def _valid_hash(text: str, digest: Any) -> bool:
    return isinstance(digest, str) and len(digest) in {16, 64} and _sha(text)[:len(digest)] == digest


def get_validated_evidence_context(
    hit: RetrievalHit | Mapping[str, Any], *, canonical_text: str | None = None,
) -> dict[str, Any] | None:
    """Validate context identity and the entire anchor; optionally verify canonical bytes.

    Consumers without canonical text must only use contexts returned by RetrievalService,
    which reconstructs and checks them against the current canonical document.
    """
    data = _data(hit)
    metadata = data.get("metadata")
    context = metadata.get("evidence_context") if isinstance(metadata, Mapping) else None
    if not isinstance(context, dict) or context.get("status") != "expanded":
        return None
    if (context.get("pipeline_version") != CONTEXT_PIPELINE_VERSION
            or not isinstance(context.get("method"), str)
            or context["method"] not in _METHODS or context.get("omission_reason") is not None):
        return None
    source, anchor = context.get("source"), context.get("anchor")
    if not isinstance(source, dict) or not isinstance(anchor, dict):
        return None
    if any(field not in source or type(source[field]) is not type(data.get(field))
           or source[field] != data.get(field) for field in _SOURCE_FIELDS):
        return None
    if (not isinstance(source["document_id"], str) or not source["document_id"]
            or type(source["document_version"]) is not int or source["document_version"] < 1
            or not isinstance(source["content_hash"], str) or not source["content_hash"]):
        return None
    if (any(source[field] is not None and not isinstance(source[field], str)
            for field in ("workspace_id", "project_id", "competitor", "dimension", "market"))
            or not isinstance(source["source_role"], str)
            or source["source_role"] not in {"source", "historical_report"}
            or not isinstance(source["source_type"], str) or not source["source_type"]
            or re.fullmatch(r"(?:[0-9a-f]{16}|[0-9a-f]{64})", source["content_hash"]) is None
            or not isinstance(data.get("status", "active"), str)
            or data.get("status", "active") not in {"active", "stale"}):
        return None
    text, anchor_text = context.get("text"), data.get("text")
    if (not isinstance(text, str) or not text or len(text) > MAX_CONTEXT_CHARS
            or not isinstance(anchor_text, str) or not anchor_text):
        return None
    start, end = context.get("start"), context.get("end")
    anchor_start, anchor_end = anchor.get("start"), anchor.get("end")
    if any(type(value) is not int for value in (start, end, anchor_start, anchor_end)):
        return None
    if not (0 <= start <= anchor_start < anchor_end <= end and end - start == len(text)
            and anchor_end - anchor_start == len(anchor_text)):
        return None
    if (anchor.get("chunk_id") != data.get("chunk_id") or not data.get("chunk_id")
            or anchor.get("text_sha256") != _sha(anchor_text)
            or context.get("text_sha256") != _sha(text)
            or text[anchor_start - start:anchor_end - start] != anchor_text):
        return None
    covered = context.get("covered_chunk_ids")
    if (not isinstance(covered, list) or not covered
            or any(not isinstance(item, str) or not item for item in covered)
            or len(set(covered)) != len(covered) or data["chunk_id"] not in covered):
        return None
    if canonical_text is not None and (
        not isinstance(canonical_text, str) or end > len(canonical_text)
        or canonical_text[start:end] != text or not _valid_hash(canonical_text, source["content_hash"])
    ):
        return None
    return context


def evidence_text_for_hit(hit: RetrievalHit | Mapping[str, Any]) -> str:
    """Use verified surrounding context, retaining the anchor as the safe fallback."""
    context = get_validated_evidence_context(hit)
    return context["text"] if context is not None else str(_data(hit).get("text") or "")


def _chunk_span(chunk: KnowledgeChunk, text: str) -> tuple[tuple[int, int] | None, str | None]:
    metadata = chunk.metadata
    if "source_start" in metadata or "source_end" in metadata:
        start, end = metadata.get("source_start"), metadata.get("source_end")
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text) or text[start:end] != chunk.text):
            return None, "invalid_anchor_offsets"
        return (start, end), None
    start = text.find(chunk.text) if chunk.text else -1
    if start < 0:
        return None, "anchor_not_in_source"
    if text.find(chunk.text, start + 1) >= 0:
        return None, "ambiguous_anchor"
    return (start, start + len(chunk.text)), None


def _section_bounds(document: KnowledgeDocument, anchor_start: int) -> tuple[int, int, str]:
    headings = [
        {"level": len(match.group(1)), "text": match.group(2).strip()}
        for line in document.markdown.splitlines()
        if (match := re.match(r"^(#{1,6})\s+(.+?)\s*$", line))
    ] or document.metadata.get("headings", [])
    positions: list[tuple[int, int]] = []
    cursor = 0
    for heading in headings:
        if not isinstance(heading, dict) or not isinstance(heading.get("text"), str):
            continue
        level = heading.get("level", 1)
        if type(level) is not int or not 1 <= level <= 6:
            continue
        value = heading["text"]
        match = re.search(rf"(?m)^(?:#{{1,6}}\s+)?{re.escape(value)}\s*$", document.text[cursor:])
        if match is not None:
            position = cursor + match.start()
            positions.append((position, level))
            cursor = cursor + match.end()
    before = [(position, level) for position, level in positions if position <= anchor_start]
    if not before:
        return 0, positions[0][0] if positions else len(document.text), "document_parent"
    start, level = before[-1]
    end = next((position for position, next_level in positions
                if position > start and next_level <= level), len(document.text))
    return start, end, "section_parent"


def build_evidence_context(
    hit: RetrievalHit, document: KnowledgeDocument | None, chunks: list[KnowledgeChunk], *,
    remaining_budget: int = MAX_REQUEST_ADDITIONAL_CHARS,
    emitted_ranges: list[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Build only from the current document; parent_document_id is a version chain."""
    base: dict[str, Any] = {
        "pipeline_version": CONTEXT_PIPELINE_VERSION, "status": "skipped",
        "source": _source(hit.model_dump()), "anchor": {"chunk_id": hit.chunk_id,
                                                          "text_sha256": _sha(hit.text)},
        "covered_chunk_ids": [hit.chunk_id], "method": None, "omission_reason": None,
    }

    def skip(reason: str) -> dict[str, Any]:
        return {**base, "omission_reason": reason}

    if not isinstance(document, KnowledgeDocument):
        return skip("canonical_unavailable")
    expected = {**document.model_dump(), "document_id": document.id, "document_version": document.version}
    if any(getattr(hit, field) != expected.get(field) for field in _SOURCE_FIELDS):
        return skip("source_identity_mismatch")
    if not document.is_active or document.status not in {"active", "stale"}:
        return skip("inactive_source")
    if not _valid_hash(document.text, document.content_hash):
        return skip("source_hash_mismatch")
    anchor = next((chunk for chunk in chunks if chunk.id == hit.chunk_id), None)
    if anchor is None or anchor.document_id != document.id or anchor.text != hit.text:
        return skip("anchor_mismatch")
    if not _valid_hash(anchor.text, anchor.content_hash):
        return skip("anchor_hash_mismatch")
    span, reason = _chunk_span(anchor, document.text)
    if span is None:
        return skip(reason or "anchor_not_in_source")
    start, end = span
    base["anchor"].update(start=start, end=end)
    if len(hit.text) > MAX_CONTEXT_CHARS:
        return skip("anchor_too_large")
    if anchor.metadata.get("structure_gap") or anchor.metadata.get("structure_gaps"):
        return skip("incomplete_table")
    if any(not isinstance(document.metadata.get(field, []), list)
           for field in ("headings", "tables")):
        return skip("invalid_source_structure")
    section_start, section_end, method = _section_bounds(document, start)
    if not section_start <= start < end <= section_end:
        return skip("anchor_crosses_section")
    located: list[tuple[KnowledgeChunk, int, int]] = []
    for chunk in sorted(chunks, key=lambda item: item.chunk_index):
        if chunk.document_id != document.id:
            continue
        chunk_span, _ = _chunk_span(chunk, document.text)
        if chunk_span is not None:
            located.append((chunk, *chunk_span))
    if section_end - section_start <= MAX_CONTEXT_CHARS:
        context_start, context_end = section_start, section_end
    else:
        context_start, context_end = start, end
        method = "adjacent_chunks"
        for target_index in (anchor.chunk_index - 1, anchor.chunk_index + 1):
            neighbour = next((item for item in located if item[0].chunk_index == target_index), None)
            if neighbour is None:
                continue
            _, left, right = neighbour
            candidate_start, candidate_end = min(context_start, left), max(context_end, right)
            if (section_start <= left < right <= section_end
                    and candidate_end - candidate_start <= MAX_CONTEXT_CHARS):
                context_start, context_end = candidate_start, candidate_end
    for table in document.metadata.get("tables", []):
        table_text = table.get("text") if isinstance(table, dict) else None
        if not isinstance(table_text, str) or not table_text:
            continue
        table_start = document.text.find(table_text)
        while table_start >= 0:
            table_end = table_start + len(table_text)
            if table_start < context_end and context_start < table_end:
                if table.get("structure_gap") or table.get("structure_gaps"):
                    return skip("incomplete_table")
                if not context_start <= table_start < table_end <= context_end:
                    return skip("partial_table")
            table_start = document.text.find(table_text, table_start + 1)
    if context_start == start and context_end == end:
        return skip("no_additional_context")
    covered: list[str] = []
    for chunk, left, right in located:
        if left < context_end and context_start < right:
            if chunk.metadata.get("structure_gap") or chunk.metadata.get("structure_gaps"):
                return skip("incomplete_table")
            if chunk.metadata.get("structure") == "table" and not (
                context_start <= left and right <= context_end
            ):
                return skip("partial_table")
            if context_start <= left and right <= context_end:
                covered.append(chunk.id)
    if any(context_start < right and left < context_end for left, right in emitted_ranges or []):
        return skip("overlapping_context")
    if context_end - context_start - len(hit.text) > remaining_budget:
        return skip("request_budget")
    text = document.text[context_start:context_end]
    expanded = {**base, "status": "expanded", "text": text, "start": context_start,
                "end": context_end, "text_sha256": _sha(text), "covered_chunk_ids": covered,
                "method": method}
    validated = hit.model_copy(update={"metadata": {"evidence_context": expanded}})
    if get_validated_evidence_context(validated, canonical_text=document.text) is None:
        return skip("context_validation_failed")
    return expanded
