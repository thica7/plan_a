from __future__ import annotations

import math
import sys
from types import ModuleType

import pytest

# isort: split
from packages.knowledge.local_models import LocalEmbeddingProvider, LocalRerankerProvider
from packages.knowledge.product_benchmark import provider_readiness


class FakeEmbeddingModel:
    def __init__(self, vectors=None):
        self.vectors = vectors
        self.calls = []
        self.max_seq_length = None

    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        if self.vectors is not None:
            return self.vectors
        return [[1.0, 0.0] for _ in texts]


class FakeRerankerModel:
    def __init__(self, outputs=None):
        self.outputs = outputs
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        return self.outputs if self.outputs is not None else [1.0] * len(pairs)


@pytest.fixture
def local_dir(tmp_path):
    path = tmp_path / "model"
    path.mkdir()
    return path


def test_embedding_prefix_batch_status_and_empty(local_dir, monkeypatch):
    model = FakeEmbeddingModel()
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_sentence_transformer", lambda *a, **k: model
    )
    provider = LocalEmbeddingProvider(
        local_dir, model_id="intfloat/multilingual-e5-small", revision="abc"
    )
    assert provider.status()["effective_provider"] == "uninitialized"
    assert provider_readiness(provider.status())["semantic_ready"] is False
    assert provider.embed_documents([]) == []
    assert model.calls == []
    assert provider.embed_documents(["a", "b", "c", "d", "e"]) == [[1.0, 0.0]] * 5
    assert provider.embed_query("q") == [1.0, 0.0]
    assert [call[0] for call in model.calls] == [
        ["passage: a", "passage: b", "passage: c", "passage: d"],
        ["passage: e"],
        ["query: q"],
    ]
    assert all(call[1]["normalize_embeddings"] is True for call in model.calls)
    assert all(call[1]["batch_size"] == 4 for call in model.calls)
    status = provider.status()
    assert (
        status["requested_provider"] == status["effective_provider"] == "local-sentence-transformer"
    )
    assert status["model_version"] == "intfloat/multilingual-e5-small@abc"
    assert status["model_id"] == provider.model_id == "intfloat/multilingual-e5-small"
    assert status["revision"] == provider.revision == "abc"
    assert status["dimensions"] == 2
    assert status["device"] == "cpu"
    assert status["batch_size"] == 4
    assert status["max_length"] == 512
    assert status["prefix"] == {"query": "query: ", "document": "passage: "}
    assert status["load_time_ms"] >= 0
    assert status["inference_calls"] == 3
    assert provider_readiness(status)["semantic_ready"] is True
    assert model.max_seq_length == 512


def test_bge_embedding_has_no_prefix(local_dir, monkeypatch):
    model = FakeEmbeddingModel()
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_sentence_transformer", lambda *a, **k: model
    )
    provider = LocalEmbeddingProvider(local_dir, model_id="BAAI/bge-m3", revision="v1")
    provider.embed_query("q")
    assert model.calls[0][0] == ["q"]
    assert provider.status()["prefix"] == {"query": "", "document": ""}


@pytest.mark.parametrize(
    ("vectors", "message"),
    [
        ([[0.0, 0.0], [1.0, 0.0]], "unit vector"),
        ([[math.nan, 0.0], [1.0, 0.0]], "nonfinite"),
        ([[2.0, 0.0], [1.0, 0.0]], "unit vector"),
    ],
)
def test_embedding_rejects_invalid_vectors(local_dir, monkeypatch, vectors, message):
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_sentence_transformer",
        lambda *a, **k: FakeEmbeddingModel(vectors),
    )
    provider = LocalEmbeddingProvider(local_dir, model_id="BAAI/bge-m3", revision="v1")
    with pytest.raises(ValueError, match=message):
        provider.embed_documents(["one", "two"])
    assert provider.status()["degraded"] is True
    assert provider.status()["effective_provider"] == "degraded"
    assert provider.status()["inference_calls"] == 1
    assert provider_readiness(provider.status())["semantic_ready"] is False


def test_embedding_rejects_count_mismatch(local_dir, monkeypatch):
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_sentence_transformer",
        lambda *a, **k: FakeEmbeddingModel([[1.0, 0.0]]),
    )
    provider = LocalEmbeddingProvider(local_dir, model_id="BAAI/bge-m3", revision="v1")
    with pytest.raises(ValueError, match="count mismatch"):
        provider.embed_documents(["one", "two"])


def test_embedding_rejects_mixed_dimensions_in_one_batch(local_dir, monkeypatch):
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_sentence_transformer",
        lambda *a, **k: FakeEmbeddingModel([[1.0, 0.0], [1.0, 0.0, 0.0]]),
    )
    provider = LocalEmbeddingProvider(local_dir, model_id="BAAI/bge-m3", revision="v1")
    with pytest.raises(ValueError, match="dimension mismatch"):
        provider.embed_documents(["one", "two"])


def test_embedding_rejects_dimension_change(local_dir, monkeypatch):
    model = FakeEmbeddingModel()
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_sentence_transformer", lambda *a, **k: model
    )
    provider = LocalEmbeddingProvider(local_dir, model_id="BAAI/bge-m3", revision="v1")
    provider.embed_query("one")
    model.vectors = [[1.0, 0.0, 0.0]]
    with pytest.raises(ValueError, match="dimension"):
        provider.embed_query("two")
    assert provider.status()["degraded"] is True


def test_embedding_rejects_missing_path_and_blank_query(tmp_path, local_dir):
    with pytest.raises(FileNotFoundError):
        LocalEmbeddingProvider(tmp_path / "absent", model_id="BAAI/bge-m3", revision="v1")
    provider = LocalEmbeddingProvider(local_dir, model_id="BAAI/bge-m3", revision="v1")
    with pytest.raises(ValueError):
        provider.embed_query(" ")


def test_reranker_scores_batches_and_status(local_dir, monkeypatch):
    model = FakeRerankerModel()
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_cross_encoder", lambda *a, **k: model
    )
    provider = LocalRerankerProvider(local_dir, model_id="BAAI/bge-reranker-v2-m3", revision="abc")
    assert provider.status()["effective_provider"] == "uninitialized"
    assert provider.rerank("query", []) == []
    scores = provider.rerank("query", ["a", "b", "c", "d", "e"])
    assert scores == pytest.approx([1 / (1 + math.exp(-1))] * 5)
    assert [call[0] for call in model.calls] == [
        [("query", "a"), ("query", "b"), ("query", "c"), ("query", "d")],
        [("query", "e")],
    ]
    assert all(call[1]["batch_size"] == 4 for call in model.calls)
    status = provider.status()
    assert status["requested_provider"] == status["effective_provider"] == "local-cross-encoder"
    assert status["model_version"] == "BAAI/bge-reranker-v2-m3@abc"
    assert status["model_id"] == provider.model_id == "BAAI/bge-reranker-v2-m3"
    assert status["revision"] == provider.revision == "abc"
    assert status["device"] == "cpu"
    assert status["batch_size"] == 4
    assert status["max_length"] == 512
    assert status["inference_calls"] == 2
    assert status["load_time_ms"] >= 0


@pytest.mark.parametrize(
    ("logit", "expected"),
    [
        (-1000.0, 0.0),
        (-2.0, 1 / (1 + math.exp(2))),
        (0.0, 0.5),
        (2.0, 1 / (1 + math.exp(-2))),
        (1000.0, 1.0),
    ],
)
def test_reranker_sigmoid_is_stable_and_bounded(local_dir, monkeypatch, logit, expected):
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_cross_encoder",
        lambda *a, **k: FakeRerankerModel([logit]),
    )
    provider = LocalRerankerProvider(local_dir, model_id="BAAI/bge-reranker-v2-m3", revision="v1")
    score = provider.rerank("q", ["a"])[0]
    assert math.isfinite(score)
    assert 0.0 <= score <= 1.0
    assert score == pytest.approx(expected)


def test_reranker_loader_failure_raises_and_marks_degraded(local_dir, monkeypatch):
    failure = ImportError("sentence-transformers required")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("packages.knowledge.local_models._load_cross_encoder", fail)
    provider = LocalRerankerProvider(local_dir, model_id="BAAI/bge-reranker-v2-m3", revision="v1")
    with pytest.raises(ImportError) as caught:
        provider.rerank("q", ["a"])
    assert caught.value is failure
    status = provider.status()
    assert status["requested_provider"] == "local-cross-encoder"
    assert status["effective_provider"] == "degraded"
    assert status["degraded"] is True
    assert "sentence-transformers" in status["reason"]
    assert status["load_time_ms"] is not None
    assert status["load_time_ms"] >= 0
    assert status["inference_calls"] == 0


@pytest.mark.parametrize("outputs", [[], [math.nan], [math.inf]])
def test_reranker_rejects_invalid_logits(local_dir, monkeypatch, outputs):
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_cross_encoder",
        lambda *a, **k: FakeRerankerModel(outputs),
    )
    provider = LocalRerankerProvider(local_dir, model_id="BAAI/bge-reranker-v2-m3", revision="v1")
    with pytest.raises(ValueError):
        provider.rerank("q", ["a"])
    assert provider.status()["degraded"] is True
    assert provider.status()["inference_calls"] == 1


def test_loader_failure_is_explicit_and_degraded(local_dir, monkeypatch):
    def fail(*args, **kwargs):
        raise ImportError("sentence-transformers required")

    monkeypatch.setattr("packages.knowledge.local_models._load_sentence_transformer", fail)
    provider = LocalEmbeddingProvider(local_dir, model_id="BAAI/bge-m3", revision="v1")
    with pytest.raises(ImportError, match="sentence-transformers"):
        provider.embed_query("query")
    assert provider.status()["effective_provider"] == "degraded"
    assert provider.status()["inference_calls"] == 0


def test_loaders_require_local_files_and_cpu_float32(local_dir, monkeypatch):
    from packages.knowledge.local_models import _load_cross_encoder, _load_sentence_transformer

    seen = []
    module = ModuleType("sentence_transformers")

    def sentence_transformer(path, **kwargs):
        seen.append(("embedding", path, kwargs))
        return FakeEmbeddingModel()

    def cross_encoder(path, **kwargs):
        seen.append(("reranker", path, kwargs))
        return FakeRerankerModel()

    fake_torch = ModuleType("torch")
    fake_torch.float32 = object()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    module.SentenceTransformer = sentence_transformer
    module.CrossEncoder = cross_encoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    _load_sentence_transformer(local_dir, 512, "cpu")
    _load_cross_encoder(local_dir, 512, "cpu")
    assert [entry[0] for entry in seen] == ["embedding", "reranker"]
    for _, path, kwargs in seen:
        assert path == str(local_dir)
        assert kwargs["local_files_only"] is True
        assert kwargs["trust_remote_code"] is False
        assert kwargs["device"] == "cpu"
        assert kwargs["model_kwargs"]["torch_dtype"] is fake_torch.float32
    assert seen[1][2]["max_length"] == 512
    assert seen[1][2]["activation_fn"](17) == 17
