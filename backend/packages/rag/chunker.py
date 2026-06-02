from __future__ import annotations

import hashlib
import re

from packages.schema.enterprise import EvidenceRecord
from packages.schema.rag import RetrievalChunk

MAX_CHUNK_CHARS = 700
CHUNK_OVERLAP_CHARS = 120
_WHITESPACE_RE = re.compile(r"\s+")


def chunk_evidence(
    evidence: EvidenceRecord,
    *,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[RetrievalChunk]:
    text = _evidence_text(evidence)
    if not text:
        return []
    chunks = _chunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
    return [
        RetrievalChunk(
            id=_chunk_id(evidence.id, index, chunk),
            evidence_id=evidence.id,
            chunk_index=index,
            title=evidence.title,
            source_type=evidence.source_type,
            dimension=evidence.dimension,
            text=chunk,
            source_url=str(evidence.url or evidence.canonical_url or ""),
        )
        for index, chunk in enumerate(chunks)
    ]


def chunk_corpus(evidence: list[EvidenceRecord]) -> list[RetrievalChunk]:
    chunks: list[RetrievalChunk] = []
    for item in evidence:
        chunks.extend(chunk_evidence(item))
    return chunks


def _evidence_text(evidence: EvidenceRecord) -> str:
    metadata_text = _metadata_text(evidence)
    parts = [
        evidence.title,
        evidence.snippet,
        metadata_text,
        evidence.dimension,
        evidence.source_type,
        evidence.canonical_url,
    ]
    return _normalize(" ".join(part for part in parts if part))


def _metadata_text(evidence: EvidenceRecord) -> str:
    values: list[str] = []
    for key in ("full_text", "content", "text", "raw_text", "extracted_text", "summary"):
        value = evidence.metadata.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    return " ".join(values)


def _chunk_text(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    safe_overlap = max(0, min(overlap_chars, max_chars // 2))
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            sentence_end = max(text.rfind(". ", start, end), text.rfind("; ", start, end))
            if sentence_end > start + max_chars // 2:
                end = sentence_end + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - safe_overlap, start + 1)
    return chunks


def _chunk_id(evidence_id: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{evidence_id}|{index}|{text}".encode()).hexdigest()
    return f"chunk-{digest[:24]}"


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()
