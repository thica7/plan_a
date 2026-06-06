"""Embedding providers for the knowledge base."""

from __future__ import annotations

import hashlib
import math
import os
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

import httpx

DEFAULT_EMBEDDING_DIM = 1024
DEFAULT_EMBEDDING_MODEL = "hash-embedding-v1"


class EmbeddingProvider(ABC):
    """Synchronous embedding provider interface."""

    model_version: str

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic offline embedding provider for tests and local fallback."""

    def __init__(
        self,
        *,
        dimensions: int = DEFAULT_EMBEDDING_DIM,
        model_version: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self.dimensions = dimensions
        self.model_version = model_version

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        values: list[float] = []
        seed = text.encode("utf-8", errors="replace")
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for byte in digest:
                values.append((byte / 127.5) - 1.0)
                if len(values) >= self.dimensions:
                    break
            counter += 1

        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return values
        return [value / norm for value in values]


class BgeM3Provider(EmbeddingProvider):
    """BGE-M3 embedding provider with a hash fallback when optional deps are unavailable."""

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-m3",
        batch_size: int = 32,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self.model_version = model_name
        self._fallback = HashEmbeddingProvider(model_version=f"{model_name}:hash-fallback")
        self._model: Any | None = None
        self._load_error: Exception | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        if model is None:
            return self._fallback.embed_documents(texts)

        vectors: list[list[float]] = []
        for batch in _batched(texts, self.batch_size):
            encoded = model.encode(
                batch,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            vectors.extend(_to_vectors(encoded))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def _load_model(self) -> Any | None:
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            return None
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        except Exception as exc:
            self._load_error = exc
            return None
        return self._model


class HttpEmbeddingProvider(EmbeddingProvider):
    """HTTP embedding provider for local or remote embedding services."""

    def __init__(
        self,
        *,
        url: str,
        model_version: str = "http-embedding",
        batch_size: int = 32,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.url = url
        self.model_version = model_version
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self.timeout_seconds) as client:
            for batch in _batched(texts, self.batch_size):
                response = client.post(self.url, json={"texts": batch, "model": self.model_version})
                response.raise_for_status()
                payload = response.json()
                vectors.extend(payload.get("embeddings", payload.get("vectors", [])))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_embedding_provider_from_env() -> EmbeddingProvider | None:
    provider = os.getenv("KB_EMBEDDING_PROVIDER", "hash").strip().lower()
    if provider in {"", "none", "disabled", "off"}:
        return None

    batch_size = _env_int("KB_EMBEDDING_BATCH_SIZE", 32)
    timeout = _env_float("KB_EMBEDDING_TIMEOUT_SECONDS", 30.0)
    if provider == "bge-m3":
        return BgeM3Provider(
            model_name=os.getenv("KB_EMBEDDING_MODEL", "BAAI/bge-m3"),
            batch_size=batch_size,
            timeout_seconds=timeout,
        )
    if provider == "http":
        url = os.getenv("KB_EMBEDDING_HTTP_URL")
        if not url:
            return HashEmbeddingProvider(model_version="http-embedding:hash-fallback")
        return HttpEmbeddingProvider(
            url=url,
            model_version=os.getenv("KB_EMBEDDING_MODEL_VERSION", "http-embedding"),
            batch_size=batch_size,
            timeout_seconds=timeout,
        )
    return HashEmbeddingProvider(
        dimensions=_env_int("KB_EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM),
        model_version=os.getenv("KB_EMBEDDING_MODEL_VERSION", DEFAULT_EMBEDDING_MODEL),
    )


def _batched(items: list[str], batch_size: int) -> Iterable[list[str]]:
    size = max(1, batch_size)
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _to_vectors(encoded: Any) -> list[list[float]]:
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    return [[float(value) for value in vector] for vector in encoded]


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
