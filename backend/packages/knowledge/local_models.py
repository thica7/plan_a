"""Strict local semantic providers for knowledge retrieval."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from .embeddings import EmbeddingProvider
from .reranker import RerankerProvider

_EMBEDDING_IDS = {"intfloat/multilingual-e5-small", "BAAI/bge-m3"}
_RERANKER_ID = "BAAI/bge-reranker-v2-m3"


def _identity(value: Any) -> Any:
    return value


def _load_sentence_transformer(path: Path, max_length: int, device: str) -> Any:
    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ImportError("Local embeddings require torch and sentence-transformers") from exc
    return SentenceTransformer(
        str(path),
        device=device,
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs={"torch_dtype": torch.float32},
    )


def _load_cross_encoder(path: Path, max_length: int, device: str) -> Any:
    try:
        import torch
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise ImportError("Local reranking requires torch and sentence-transformers") from exc
    return CrossEncoder(
        str(path),
        device=device,
        max_length=max_length,
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs={"torch_dtype": torch.float32},
        activation_fn=_identity,
    )


def _check_path(path: Path) -> Path:
    local_path = Path(path)
    if not local_path.is_dir():
        raise FileNotFoundError(f"Local model directory does not exist: {local_path}")
    return local_path


def _check_options(
    model_id: str, revision: str, device: str, batch_size: int, max_length: int
) -> None:
    if not model_id or not revision:
        raise ValueError("model_id and revision are required")
    if device != "cpu":
        raise ValueError("Local providers currently require device=cpu")
    if batch_size <= 0 or max_length <= 0:
        raise ValueError("batch_size and max_length must be positive")


class _LocalStatus:
    requested_provider: str
    model_version: str
    model_id: str
    revision: str
    _model: Any | None
    _error: Exception | None
    load_time_ms: float | None
    inference_calls: int
    device: str
    max_length: int
    batch_size: int

    def status(self) -> dict[str, Any]:
        return {
            "requested_provider": self.requested_provider,
            "effective_provider": (
                "degraded"
                if self._error
                else self.requested_provider
                if self._model
                else "uninitialized"
            ),
            "model_version": self.model_version,
            "model_id": self.model_id,
            "revision": self.revision,
            "degraded": self._error is not None,
            "reason": str(self._error) if self._error else None,
            "device": self.device,
            "max_length": self.max_length,
            "batch_size": self.batch_size,
            "load_time_ms": self.load_time_ms,
            "inference_calls": self.inference_calls,
        }


class LocalEmbeddingProvider(_LocalStatus, EmbeddingProvider):
    """Sentence Transformer embeddings from a local directory only."""

    def __init__(
        self,
        path: Path,
        *,
        model_id: str,
        revision: str,
        device: str = "cpu",
        batch_size: int = 4,
        max_length: int = 512,
    ) -> None:
        _check_options(model_id, revision, device, batch_size, max_length)
        if model_id not in _EMBEDDING_IDS:
            raise ValueError(f"Unsupported embedding model: {model_id}")
        self.path = _check_path(path)
        self.model_id, self.revision = model_id, revision
        self.model_version = f"{model_id}@{revision}"
        self.requested_provider = "local-sentence-transformer"
        self.device, self.batch_size, self.max_length = device, batch_size, max_length
        self.prefix = (
            {"query": "query: ", "document": "passage: "}
            if model_id.startswith("intfloat/")
            else {"query": "", "document": ""}
        )
        self.dimensions: int | None = None
        self._model = None
        self._error = None
        self.load_time_ms = None
        self.inference_calls = 0

    def status(self) -> dict[str, Any]:
        return {**super().status(), "dimensions": self.dimensions, "prefix": self.prefix.copy()}

    def _get_model(self) -> Any:
        if self._model is None:
            start = time.perf_counter()
            try:
                model = _load_sentence_transformer(self.path, self.max_length, self.device)
                model.max_seq_length = self.max_length
                self._model = model
            finally:
                self.load_time_ms = (time.perf_counter() - start) * 1000
        return self._model

    def _embed(self, texts: list[str], prefix: str) -> list[list[float]]:
        if not texts:
            return []
        try:
            model = self._get_model()
            vectors: list[list[float]] = []
            for start in range(0, len(texts), self.batch_size):
                batch = [prefix + text for text in texts[start : start + self.batch_size]]
                self.inference_calls += 1
                raw = model.encode(
                    batch,
                    normalize_embeddings=True,
                    batch_size=self.batch_size,
                    show_progress_bar=False,
                )
                converted = [list(map(float, vector)) for vector in raw]
                if len(converted) != len(batch):
                    raise ValueError("Embedding output count mismatch")
                for vector in converted:
                    dimension = self.dimensions or len(vector)
                    if len(vector) != dimension or not vector:
                        raise ValueError("Embedding dimension mismatch")
                    if not all(math.isfinite(value) for value in vector):
                        raise ValueError("Embedding contains nonfinite values")
                    norm = math.sqrt(sum(value * value for value in vector))
                    if not math.isclose(norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
                        raise ValueError("Embedding must be a nonzero unit vector")
                    self.dimensions = dimension
                vectors.extend(converted)
            return vectors
        except Exception as exc:
            self._error = exc
            raise

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, self.prefix["document"])

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("Embedding query must not be empty")
        return self._embed([text], self.prefix["query"])[0]


class LocalRerankerProvider(_LocalStatus, RerankerProvider):
    """Cross Encoder scores from a local directory only."""

    def __init__(
        self,
        path: Path,
        *,
        model_id: str,
        revision: str,
        device: str = "cpu",
        batch_size: int = 4,
        max_length: int = 512,
    ) -> None:
        _check_options(model_id, revision, device, batch_size, max_length)
        if model_id != _RERANKER_ID:
            raise ValueError(f"Unsupported reranker model: {model_id}")
        self.path = _check_path(path)
        self.model_id, self.revision = model_id, revision
        self.model_version = f"{model_id}@{revision}"
        self.requested_provider = "local-cross-encoder"
        self.device, self.batch_size, self.max_length = device, batch_size, max_length
        self._model = None
        self._error = None
        self.load_time_ms = None
        self.inference_calls = 0

    def _get_model(self) -> Any:
        if self._model is None:
            start = time.perf_counter()
            try:
                self._model = _load_cross_encoder(self.path, self.max_length, self.device)
            finally:
                self.load_time_ms = (time.perf_counter() - start) * 1000
        return self._model

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        if not query.strip():
            raise ValueError("Reranking query must not be empty")
        if not texts:
            return []
        try:
            model = self._get_model()
            scores: list[float] = []
            for start in range(0, len(texts), self.batch_size):
                batch = [(query, text) for text in texts[start : start + self.batch_size]]
                self.inference_calls += 1
                raw = model.predict(batch, batch_size=self.batch_size, show_progress_bar=False)
                logits = [float(value) for value in raw]
                if len(logits) != len(batch):
                    raise ValueError("Reranker output count mismatch")
                if not all(math.isfinite(value) for value in logits):
                    raise ValueError("Reranker contains nonfinite logits")
                scores.extend(
                    1 / (1 + math.exp(-value))
                    if value >= 0
                    else math.exp(value) / (1 + math.exp(value))
                    for value in logits
                )
            return scores
        except Exception as exc:
            self._error = exc
            raise
