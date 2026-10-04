from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.compare_local_retrieval_models import validate_manifest


def _record(tmp_path: Path, model_id: str):
    directory = tmp_path / model_id.replace("/", "--")
    directory.mkdir()
    file = directory / "config.json"
    file.write_text("{}")
    return {
        "model_id": model_id,
        "revision": "a" * 40,
        "local_path": str(directory),
        "files": [{"file": "config.json", "bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}],
        "conversion": None,
    }


def test_manifest_selected_models_are_verified(tmp_path):
    embedding = _record(tmp_path, "intfloat/multilingual-e5-small")
    reranker = _record(tmp_path, "BAAI/bge-reranker-v2-m3")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    selected = validate_manifest(manifest, embedding["model_id"])
    assert selected[0]["revision"] == "a" * 40
    assert selected[1]["model_id"] == reranker["model_id"]
    (Path(embedding["local_path"]) / "config.json").write_text("tampered")
    with pytest.raises(ValueError, match="hash|bytes"):
        validate_manifest(manifest, embedding["model_id"])


def test_manifest_rejects_path_escape_and_duplicate_ids(tmp_path):
    embedding = _record(tmp_path, "BAAI/bge-m3")
    reranker = _record(tmp_path, "BAAI/bge-reranker-v2-m3")
    manifest = tmp_path / "manifest.json"
    reranker["files"][0]["file"] = "../config.json"
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    with pytest.raises(ValueError, match="path"):
        validate_manifest(manifest, embedding["model_id"])
    reranker["files"][0]["file"] = "config.json"
    manifest.write_text(json.dumps({"models": [embedding, embedding, reranker]}))
    with pytest.raises(ValueError, match="duplicate"):
        validate_manifest(manifest, embedding["model_id"])


def test_cli_runs_eight_arms_without_gold_query_rewrites(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from packages.knowledge import local_models, product_benchmark
    from scripts import compare_local_retrieval_models as cli

    embedding = _record(tmp_path, "intfloat/multilingual-e5-small")
    reranker = _record(tmp_path, "BAAI/bge-reranker-v2-m3")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    paths = {}
    for name in ("corpus", "queries", "labels"):
        paths[name] = tmp_path / f"{name}.jsonl"
        paths[name].write_text('{"private":"gold must stay in labels"}\n')

    class FakeProvider:
        def __init__(self, path, **kwargs):
            self.model_version = kwargs["model_id"] + "@" + kwargs["revision"]
            self.dimensions = 2
            self.inference_calls = 0

        def embed_query(self, query):
            self.inference_calls += 1
            return [1.0, 0.0]

        def rerank(self, query, texts):
            self.inference_calls += 1
            return [1.0 for _ in texts]

        def status(self):
            return {"inference_calls": self.inference_calls, "load_time_ms": 1.0}

    calls = []

    async def fake_run(corpus, queries, labels, **kwargs):
        calls.append(kwargs)
        return {
            "queries": [{"original_query": "saved query", "proofs": ["saved proof"]}],
            "model_calls": 0,
        }

    monkeypatch.setattr(local_models, "LocalEmbeddingProvider", FakeProvider)
    monkeypatch.setattr(local_models, "LocalRerankerProvider", FakeProvider)
    monkeypatch.setattr(product_benchmark, "run_product_benchmark", fake_run)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda n: None))
    output = tmp_path / "output.json"
    argv = [
        "--manifest",
        str(manifest),
        "--embedding-model",
        embedding["model_id"],
        "--corpus",
        str(paths["corpus"]),
        "--queries",
        str(paths["queries"]),
        "--labels",
        str(paths["labels"]),
        "--mode",
        "candidate-diagnostic",
        "--output",
        str(output),
    ]
    assert cli.main(argv) == 0
    result = json.loads(output.read_text())
    assert len(calls) == 8
    assert set(result["reports"]) == {
        f"{intent}_{arm}"
        for intent in ("raw", "structured")
        for arm in ("sparse", "dense", "hybrid", "hybrid_rerank")
    }
    assert all(call.get("intent_plan_path") is None for call in calls)
    assert all(
        call.get("embedding_provider") is None
        for call in calls
        if call["retrieval_mode"] == "sparse"
    )
    assert result["before"] == result["after"]
    assert result["reports"]["raw_sparse"]["queries"][0]["proofs"] == ["saved proof"]
    assert result["external_model_calls"] == 0
    assert result["initialization_model_calls"] == {"embedding": 1, "reranker": 1}


def test_cli_rejects_mutated_input_before_writing(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from packages.knowledge import local_models, product_benchmark
    from scripts import compare_local_retrieval_models as cli

    embedding = _record(tmp_path, "BAAI/bge-m3")
    reranker = _record(tmp_path, "BAAI/bge-reranker-v2-m3")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    paths = {name: tmp_path / f"{name}.jsonl" for name in ("corpus", "queries", "labels")}
    for path in paths.values():
        path.write_text("{}\n")

    class FakeProvider:
        def __init__(self, path, **kwargs):
            self.inference_calls = 0

        def embed_query(self, query):
            self.inference_calls += 1
            return [1.0]

        def rerank(self, query, texts):
            self.inference_calls += 1
            return [1.0]

        def status(self):
            return {"inference_calls": self.inference_calls, "load_time_ms": 0.0}

    async def fake_run(*args, **kwargs):
        paths["queries"].write_text('{"changed":true}\n')
        return {"queries": []}

    monkeypatch.setattr(local_models, "LocalEmbeddingProvider", FakeProvider)
    monkeypatch.setattr(local_models, "LocalRerankerProvider", FakeProvider)
    monkeypatch.setattr(product_benchmark, "run_product_benchmark", fake_run)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda n: None))
    output = tmp_path / "output.json"
    assert (
        cli.main(
            [
                "--manifest",
                str(manifest),
                "--embedding-model",
                embedding["model_id"],
                "--corpus",
                str(paths["corpus"]),
                "--queries",
                str(paths["queries"]),
                "--labels",
                str(paths["labels"]),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()


@pytest.mark.parametrize(
    "manifest_value", [[], {"models": [{}]}, {"models": [{"model_id": "x", "local_path": []}]}]
)
def test_manifest_malformed_top_or_fields_return_value_error(tmp_path, manifest_value):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest_value))
    with pytest.raises(ValueError):
        validate_manifest(path, "BAAI/bge-m3")


def test_manifest_rejects_unlisted_actual_file_and_normalized_duplicate(tmp_path):
    embedding = _record(tmp_path, "BAAI/bge-m3")
    reranker = _record(tmp_path, "BAAI/bge-reranker-v2-m3")
    manifest = tmp_path / "manifest.json"
    (Path(embedding["local_path"]) / "extra.safetensors").write_bytes(b"weight")
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    with pytest.raises(ValueError, match="unlisted|extra"):
        validate_manifest(manifest, embedding["model_id"])
    (Path(embedding["local_path"]) / "extra.safetensors").unlink()
    embedding["files"].append({**embedding["files"][0], "file": "./config.json"})
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    with pytest.raises(ValueError, match="duplicate"):
        validate_manifest(manifest, embedding["model_id"])


def test_manifest_ignores_exact_huggingface_cache_only(tmp_path):
    embedding = _record(tmp_path, "BAAI/bge-m3")
    reranker = _record(tmp_path, "BAAI/bge-reranker-v2-m3")
    root = Path(embedding["local_path"])
    cache = root / ".cache" / "huggingface"
    cache.mkdir(parents=True)
    (cache / "download.lock").write_text("cache")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    validate_manifest(manifest, embedding["model_id"])
    (root / ".other").mkdir()
    (root / ".other" / "unlisted").write_text("not cache")
    with pytest.raises(ValueError, match="unlisted"):
        validate_manifest(manifest, embedding["model_id"])


def test_environment_scrub_disables_dotenv_and_removes_api_credentials(monkeypatch):
    import os

    from scripts.compare_local_retrieval_models import _scrub_environment

    monkeypatch.setenv("COMPETISCOPE_LOAD_ENV_FILES", "1")
    monkeypatch.setenv("SOME_APIKEY", "secret-value")
    monkeypatch.setenv("SOME_TOKEN_SUFFIX", "secret-value")
    _scrub_environment()
    assert os.environ["COMPETISCOPE_LOAD_ENV_FILES"] == "0"
    assert "SOME_APIKEY" not in os.environ
    assert "SOME_TOKEN_SUFFIX" not in os.environ
    assert os.environ["HF_HUB_OFFLINE"] == "1"


def test_cli_report_records_process_lifetime_rss_scope(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from packages.knowledge import local_models, product_benchmark
    from scripts import compare_local_retrieval_models as cli

    embedding = _record(tmp_path, "BAAI/bge-m3")
    reranker = _record(tmp_path, "BAAI/bge-reranker-v2-m3")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    paths = {name: tmp_path / f"{name}.jsonl" for name in ("corpus", "queries", "labels")}
    for path in paths.values():
        path.write_text("{}\n")

    class FakeProvider:
        def __init__(self, path, **kwargs):
            self.inference_calls = 0

        def embed_query(self, query):
            self.inference_calls += 1
            return [1.0]

        def rerank(self, query, texts):
            self.inference_calls += 1
            return [1.0]

        def status(self):
            return {"inference_calls": self.inference_calls, "load_time_ms": 0.0}

    async def fake_run(*args, **kwargs):
        return {"queries": [], "peak_rss_bytes": 1}

    monkeypatch.setattr(local_models, "LocalEmbeddingProvider", FakeProvider)
    monkeypatch.setattr(local_models, "LocalRerankerProvider", FakeProvider)
    monkeypatch.setattr(product_benchmark, "run_product_benchmark", fake_run)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda n: None))
    output = tmp_path / "output.json"
    assert (
        cli.main(
            [
                "--manifest",
                str(manifest),
                "--embedding-model",
                embedding["model_id"],
                "--corpus",
                str(paths["corpus"]),
                "--queries",
                str(paths["queries"]),
                "--labels",
                str(paths["labels"]),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    data = json.loads(output.read_text())
    assert data["peak_rss_scope"]["scope"] == "process_lifetime"
    assert data["peak_rss_scope"]["includes_embedding_and_reranker"] is True
    assert set(data["peak_rss_scope"]["resident_model_ids"]) == {
        embedding["model_id"],
        reranker["model_id"],
    }
    assert data["model_calls_scope"] == "process_lifetime_including_initialization"
    assert data["reports"]["raw_sparse"]["peak_rss_scope"] == data["peak_rss_scope"]
    assert (
        data["reports"]["raw_sparse"]["model_calls_scope"] == "arm_delta_excluding_initialization"
    )


def test_snapshot_freezes_intent_and_evaluation_logic(tmp_path):
    from argparse import Namespace

    from scripts.compare_local_retrieval_models import _snapshot

    paths = {}
    for name in ("manifest", "corpus", "queries", "labels"):
        paths[name] = tmp_path / name
        paths[name].write_text("{}")
    frozen = _snapshot(Namespace(**paths))["source_sha256"]
    assert len(frozen["packages/knowledge/query_intent.py"]) == 64
    assert len(frozen["packages/knowledge/eval.py"]) == 64


@pytest.mark.parametrize("bad_field,value", [("local_path", []), ("files", "config.json")])
def test_manifest_selected_record_invalid_fields_raise_value_error(tmp_path, bad_field, value):
    embedding = _record(tmp_path, "BAAI/bge-m3")
    reranker = _record(tmp_path, "BAAI/bge-reranker-v2-m3")
    embedding[bad_field] = value
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"models": [embedding, reranker]}))
    with pytest.raises(ValueError):
        validate_manifest(manifest, embedding["model_id"])


def test_cli_malformed_manifest_returns_two_without_traceback(tmp_path, capsys):
    from scripts.compare_local_retrieval_models import main

    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]")
    paths = {name: tmp_path / f"{name}.jsonl" for name in ("corpus", "queries", "labels")}
    for path in paths.values():
        path.write_text("{}\n")
    output = tmp_path / "report.json"
    code = main(
        [
            "--manifest",
            str(manifest),
            "--embedding-model",
            "BAAI/bge-m3",
            "--corpus",
            str(paths["corpus"]),
            "--queries",
            str(paths["queries"]),
            "--labels",
            str(paths["labels"]),
            "--output",
            str(output),
        ]
    )
    assert code == 2
    assert not output.exists()
    assert "Traceback" not in capsys.readouterr().err
