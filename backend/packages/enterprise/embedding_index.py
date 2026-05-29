from __future__ import annotations

import hashlib
import math
import re

from packages.schema.enterprise import EvidenceEmbeddingRecord, EvidenceRecord

EMBEDDING_DIMENSIONS = 384
EMBEDDING_MODEL = "hashing-384"
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def build_evidence_embedding_record(evidence: EvidenceRecord) -> EvidenceEmbeddingRecord:
    text = evidence_embedding_text(evidence)
    return EvidenceEmbeddingRecord(
        id=f"embedding-{evidence.id}",
        workspace_id=evidence.workspace_id,
        project_id=evidence.project_id,
        evidence_id=evidence.id,
        embedding_model=EMBEDDING_MODEL,
        embedding_dimensions=EMBEDDING_DIMENSIONS,
        embedding_hash=embedding_hash(text),
        embedding_text=text,
    )


def evidence_embedding_text(evidence: EvidenceRecord) -> str:
    parts = [
        evidence.title,
        evidence.snippet,
        evidence.dimension,
        evidence.source_type,
        evidence.canonical_url,
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def embedding_hash(text: str) -> str:
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()


def deterministic_embedding(text: str, *, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(_normalize_text(text))


def _normalize_text(text: str) -> str:
    return text.casefold().strip()
