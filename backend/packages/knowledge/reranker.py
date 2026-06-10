"""Reranker providers for knowledge retrieval."""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

import httpx

DEFAULT_RERANK_MODEL = "hash-reranker-v1"


class RerankerProvider(ABC):
    """Synchronous reranker provider interface."""

    model_version: str

    @abstractmethod
    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """Return relevance scores for texts in their original order."""


class HashRerankerProvider(RerankerProvider):
    """Deterministic offline reranker provider."""

    def __init__(self, *, model_version: str = DEFAULT_RERANK_MODEL) -> None:
        self.model_version = model_version

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        return [self._score(query, text) for text in texts]

    @staticmethod
    def _score(query: str, text: str) -> float:
        query_terms = {term.lower() for term in query.split() if term.strip()}
        text_terms = {term.lower() for term in text.split() if term.strip()}
        lexical = len(query_terms & text_terms) / max(1, len(query_terms))
        digest = hashlib.sha256(f"{query}\0{text}".encode("utf-8", errors="replace")).digest()
        jitter = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
        return min(1.0, lexical * 0.9 + jitter * 0.1)


class BgeRerankerV2M3Provider(RerankerProvider):
    """BGE reranker provider with a hash fallback when optional deps are unavailable."""

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        batch_size: int = 32,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self.model_version = model_name
        self._fallback = HashRerankerProvider(model_version=f"{model_name}:hash-fallback")
        self._model: Any | None = None
        self._load_error: Exception | None = None

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        model = self._load_model()
        if model is None:
            return self._fallback.rerank(query, texts)

        scores: list[float] = []
        for batch in _batched(texts, self.batch_size):
            pairs = [[query, text] for text in batch]
            encoded = model.compute_score(pairs, normalize=True)
            if isinstance(encoded, int | float):
                scores.append(float(encoded))
            else:
                scores.extend(float(score) for score in encoded)
        return scores

    def _load_model(self) -> Any | None:
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            return None
        try:
            from FlagEmbedding import FlagReranker

            self._model = FlagReranker(self.model_name, use_fp16=True)
        except Exception as exc:
            self._load_error = exc
            return None
        return self._model


class HttpRerankerProvider(RerankerProvider):
    """HTTP reranker provider for local or remote reranking services."""

    def __init__(
        self,
        *,
        url: str,
        model_version: str = "http-reranker",
        batch_size: int = 32,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.url = url
        self.model_version = model_version
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        scores: list[float] = []
        with httpx.Client(timeout=self.timeout_seconds) as client:
            for batch in _batched(texts, self.batch_size):
                response = client.post(
                    self.url,
                    json={"query": query, "texts": batch, "model": self.model_version},
                )
                response.raise_for_status()
                payload = response.json()
                scores.extend(payload.get("scores", []))
        return [float(score) for score in scores]


def get_reranker_provider_from_env() -> RerankerProvider | None:
    provider = os.getenv("KB_RERANKER_PROVIDER", "hash").strip().lower()
    if provider in {"", "none", "disabled", "off"}:
        return None

    batch_size = _env_int("KB_RERANKER_BATCH_SIZE", 32)
    timeout = _env_float("KB_RERANKER_TIMEOUT_SECONDS", 30.0)
    if provider in {"bge-reranker-v2-m3", "bge-v2-m3", "bge"}:
        return BgeRerankerV2M3Provider(
            model_name=os.getenv("KB_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            batch_size=batch_size,
            timeout_seconds=timeout,
        )
    if provider == "http":
        url = os.getenv("KB_RERANKER_HTTP_URL")
        if not url:
            return HashRerankerProvider(model_version="http-reranker:hash-fallback")
        return HttpRerankerProvider(
            url=url,
            model_version=os.getenv("KB_RERANKER_MODEL_VERSION", "http-reranker"),
            batch_size=batch_size,
            timeout_seconds=timeout,
        )
    return HashRerankerProvider(
        model_version=os.getenv("KB_RERANKER_MODEL_VERSION", DEFAULT_RERANK_MODEL)
    )


def _batched(items: list[str], batch_size: int) -> Iterable[list[str]]:
    size = max(1, batch_size)
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
