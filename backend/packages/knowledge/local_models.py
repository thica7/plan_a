"""Strict local semantic providers for knowledge retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from functools import lru_cache
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
        dimensions: int | None = None,
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
        self.dimensions: int | None = dimensions
        self._model = None
        self._error = None
        self.load_time_ms = None
        self.inference_calls = 0
        self._lock = threading.RLock()

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
        with self._lock:
            return self._embed_locked(texts, prefix)

    def _embed_locked(self, texts: list[str], prefix: str) -> list[list[float]]:
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
        self._lock = threading.RLock()

    def _get_model(self) -> Any:
        if self._model is None:
            start = time.perf_counter()
            try:
                self._model = _load_cross_encoder(self.path, self.max_length, self.device)
            finally:
                self.load_time_ms = (time.perf_counter() - start) * 1000
        return self._model

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        with self._lock:
            return self._rerank_locked(query, texts)

    def _rerank_locked(self, query: str, texts: list[str]) -> list[float]:
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


_MANIFEST_PATH = (Path(__file__).resolve().parents[3] / "docs" / "optimization"
                  / "2026-10-04-local-model-download-manifest.json")
_FROZEN_REVISIONS = {
    "intfloat/multilingual-e5-small": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
    "BAAI/bge-m3": "5617a9f61b028005a4858fdac845db406aefb181",
    "BAAI/bge-reranker-v2-m3": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
}


def local_model_strict() -> bool:
    return os.getenv("KB_LOCAL_MODEL_STRICT", "").lower() in {"1", "true", "yes"}


class UnavailableLocalProvider(EmbeddingProvider, RerankerProvider):
    """Explicit sparse fallback signal; never produces substitute hash vectors/scores."""

    def __init__(self, kind: str, model_id: str, revision: str, reason: str) -> None:
        self.requested_provider = ("local-sentence-transformer" if kind == "embedding"
                                   else "local-cross-encoder")
        self.model_version = f"{model_id}@{revision}"
        self.model_id, self.revision, self.reason = model_id, revision, reason
        self.dimensions = 384 if model_id == "intfloat/multilingual-e5-small" else None

    def status(self) -> dict[str, Any]:
        return {**EmbeddingProvider.status(self), "effective_provider": "unavailable",
                "model_id": self.model_id, "revision": self.revision,
                "degraded": True, "reason": self.reason, "inference_calls": 0}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError(self.reason)

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError(self.reason)

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        raise RuntimeError(self.reason)


def get_local_provider_from_env(kind: str) -> Any:
    """Load only frozen local artifacts. Hash validation and model loading are cached."""
    prefix = f"KB_{kind.upper()}"
    default_id = "intfloat/multilingual-e5-small" if kind == "embedding" else _RERANKER_ID
    if kind == "embedding" and os.getenv(f"{prefix}_PROVIDER", "").strip().lower() == "bge-m3":
        default_id = "BAAI/bge-m3"
    model_id = os.getenv(f"{prefix}_MODEL", default_id)
    revision = os.getenv(f"{prefix}_REVISION", _FROZEN_REVISIONS.get(model_id, ""))
    try:
        manifest_bytes = _MANIFEST_PATH.read_bytes()
        entry = next((item for item in json.loads(manifest_bytes)["models"]
                      if item["model_id"] == model_id), None)
        if (entry is None or revision != _FROZEN_REVISIONS.get(model_id)
                or entry["revision"] != revision):
            raise ValueError("Local model identity/revision is not in the frozen manifest")
        path = Path(os.getenv(f"{prefix}_LOCAL_PATH", entry["local_path"]))
        _check_path(path)
        if path.resolve() != Path(entry["local_path"]).resolve():
            raise ValueError("Local model path does not match the frozen manifest")
        version = os.getenv(f"{prefix}_MODEL_VERSION", f"{model_id}@{revision}")
        if version != f"{model_id}@{revision}":
            raise ValueError("Local model version must match the frozen identity")
        # Stats invalidate the cached verification/provider after local artifact changes.
        signature = tuple((item["file"], (path / item["file"]).stat().st_size,
                           (path / item["file"]).stat().st_mtime_ns) for item in entry["files"])
        return _frozen_provider(
            kind, model_id, revision, str(path), int(os.getenv(f"{prefix}_BATCH_SIZE", "4")),
            int(os.getenv(f"{prefix}_MAX_LENGTH", "512")), manifest_bytes, signature,
        )
    except Exception as exc:
        if local_model_strict():
            raise
        return UnavailableLocalProvider(kind, model_id, revision, str(exc))


@lru_cache(maxsize=8)
def _frozen_provider(
    kind: str, model_id: str, revision: str, path: str, batch_size: int, max_length: int,
    manifest_bytes: bytes, signature: tuple,
) -> Any:
    entry = next(item for item in json.loads(manifest_bytes)["models"]
                 if item["model_id"] == model_id and item["revision"] == revision)
    for item in entry["files"]:
        local_file = Path(path) / item["file"]
        digest = hashlib.sha256()
        with local_file.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if local_file.stat().st_size != item["bytes"] or digest.hexdigest() != item["sha256"]:
            raise ValueError(f"Frozen local model file integrity mismatch: {item['file']}")
    options = dict(model_id=model_id, revision=revision, batch_size=batch_size,
                   max_length=max_length)
    if kind == "embedding":
        return LocalEmbeddingProvider(Path(path), dimensions=384 if model_id.startswith("intfloat/")
                                      else 1024, **options)
    return LocalRerankerProvider(Path(path), **options)
