from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from packages.schema.rag import RetrievalChunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class BM25Score:
    chunk_id: str
    score: float


class BM25Index:
    def __init__(self, chunks: list[RetrievalChunk]) -> None:
        self._chunks = chunks
        self._term_counts = {chunk.id: Counter(tokenize(chunk.text)) for chunk in chunks}
        self._doc_lengths = {
            chunk_id: sum(counts.values()) for chunk_id, counts in self._term_counts.items()
        }
        self._avg_doc_length = (
            sum(self._doc_lengths.values()) / len(self._doc_lengths) if self._doc_lengths else 0.0
        )
        self._doc_frequency = self._build_doc_frequency()

    def score(self, query: str, chunk: RetrievalChunk) -> float:
        if not self._chunks or self._avg_doc_length <= 0:
            return 0.0
        query_terms = tokenize(query)
        if not query_terms:
            return 0.0
        k1 = 1.5
        b = 0.75
        counts = self._term_counts.get(chunk.id, Counter())
        doc_length = self._doc_lengths.get(chunk.id, 0)
        score = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if frequency <= 0:
                continue
            idf = self._idf(term)
            numerator = frequency * (k1 + 1)
            denominator = frequency + k1 * (1 - b + b * doc_length / self._avg_doc_length)
            score += idf * numerator / denominator
        return round(score, 6)

    def scores(self, query: str) -> dict[str, float]:
        return {chunk.id: self.score(query, chunk) for chunk in self._chunks}

    def _build_doc_frequency(self) -> dict[str, int]:
        frequency: Counter[str] = Counter()
        for counts in self._term_counts.values():
            frequency.update(counts.keys())
        return dict(frequency)

    def _idf(self, term: str) -> float:
        documents = len(self._chunks)
        containing = self._doc_frequency.get(term, 0)
        return math.log(1 + (documents - containing + 0.5) / (containing + 0.5))


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())
