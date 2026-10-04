"""Compare fixed-corpus sparse and local semantic retrieval in one offline process."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
_EMBEDDINGS = {"intfloat/multilingual-e5-small", "BAAI/bge-m3"}
_RERANKER = "BAAI/bge-reranker-v2-m3"
_SOURCE_FILES = (
    "packages/knowledge/product_benchmark.py",
    "packages/knowledge/local_models.py",
    "packages/knowledge/retrieval.py",
    "packages/knowledge/models.py",
    "packages/knowledge/repository.py",
    "packages/knowledge/lexical.py",
    "packages/knowledge/vector_store.py",
    "packages/knowledge/ingestion.py",
    "packages/knowledge/product_eval_data.py",
    "packages/knowledge/query_intent.py",
    "packages/knowledge/eval.py",
)


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def validate_manifest(path: Path, embedding_model: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify exact offline files for the selected embedding and reranker."""
    if embedding_model not in _EMBEDDINGS:
        raise ValueError("unsupported embedding model")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be an object")
    models = data.get("models")
    if not isinstance(models, list):
        raise ValueError("manifest models must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    for record in models:
        if not isinstance(record, dict) or not isinstance(record.get("model_id"), str):
            raise ValueError("invalid model record")
        model_id = record["model_id"]
        if model_id in by_id:
            raise ValueError("duplicate model id")
        by_id[model_id] = record
    for model_id in (embedding_model, _RERANKER):
        if model_id not in by_id:
            raise ValueError(f"missing model record: {model_id}")
        record = by_id[model_id]
        if not re.fullmatch(r"[0-9a-f]{40}", str(record.get("revision", ""))):
            raise ValueError(f"invalid revision: {model_id}")
        local_path = record.get("local_path")
        if not isinstance(local_path, str) or not local_path:
            raise ValueError(f"model local path is invalid: {model_id}")
        directory = Path(local_path)
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError(f"model local path is unavailable: {model_id}")
        files = record.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError(f"model files missing: {model_id}")
        names: set[str] = set()
        root = directory.resolve()
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("invalid file record")
            name = item.get("file")
            if not isinstance(name, str) or not name:
                raise ValueError("invalid model file")
            relative = Path(name)
            file = (root / relative).resolve()
            if relative.is_absolute() or ".." in relative.parts or not file.is_relative_to(root):
                raise ValueError("model file path escapes local directory")
            normalized = file.relative_to(root).as_posix()
            if normalized in names:
                raise ValueError("duplicate model file")
            names.add(normalized)
            if not file.is_file() or file.stat().st_size != item.get("bytes"):
                raise ValueError(f"model file bytes mismatch: {model_id}/{name}")
            if _digest(file) != item.get("sha256"):
                raise ValueError(f"model file hash mismatch: {model_id}/{name}")
        actual = {
            entry.relative_to(root).as_posix()
            for entry in root.rglob("*")
            if (entry.is_file() or entry.is_symlink())
            and entry.relative_to(root).parts[:2] != (".cache", "huggingface")
        }
        extra = actual - names
        if extra:
            raise ValueError(f"unlisted model file: {model_id}/{sorted(extra)[0]}")
    return by_id[embedding_model], by_id[_RERANKER]


def _snapshot(args: argparse.Namespace) -> dict[str, Any]:
    inputs = {
        name: _digest(getattr(args, name)) for name in ("manifest", "corpus", "queries", "labels")
    }
    sources = {name: _digest(_BACKEND / name) for name in _SOURCE_FILES}
    sources["scripts/compare_local_retrieval_models.py"] = _digest(Path(__file__))
    return {"input_sha256": inputs, "source_sha256": sources, "code_revision": _code_revision()}


def _code_revision() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=_BACKEND, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _scrub_environment() -> None:
    for key in tuple(os.environ):
        upper = key.upper()
        if (
            "API_KEY" in upper
            or "APIKEY" in upper
            or "TOKEN" in upper
            or upper in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "HF_TOKEN"}
        ):
            os.environ.pop(key, None)
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "COMPETISCOPE_LOAD_ENV_FILES": "0",
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--embedding-model", choices=sorted(_EMBEDDINGS), required=True)
    for name in ("corpus", "queries", "labels", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("formal", "candidate-diagnostic", "tuning-diagnostic"), default="formal"
    )
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        if args.threads <= 0:
            raise ValueError("threads must be positive")
        _scrub_environment()
        before = _snapshot(args)
        embedding_record, reranker_record = validate_manifest(args.manifest, args.embedding_model)
        sys.path.insert(0, str(_BACKEND))
        import torch

        from packages.knowledge.local_models import LocalEmbeddingProvider, LocalRerankerProvider
        from packages.knowledge.product_benchmark import run_product_benchmark

        torch.set_num_threads(args.threads)
        embedding = LocalEmbeddingProvider(
            Path(embedding_record["local_path"]),
            model_id=embedding_record["model_id"],
            revision=embedding_record["revision"],
            device="cpu",
            max_length=512,
        )
        reranker = LocalRerankerProvider(
            Path(reranker_record["local_path"]),
            model_id=reranker_record["model_id"],
            revision=reranker_record["revision"],
            device="cpu",
            max_length=512,
        )
        started = time.perf_counter()
        embedding.embed_query("model readiness probe")
        reranker.rerank("model readiness probe", ["model readiness probe"])
        initialization_calls = {
            "embedding": embedding.status()["inference_calls"],
            "reranker": reranker.status()["inference_calls"],
        }
        reports: dict[str, Any] = {}
        for intent in ("raw", "structured"):
            for arm, retrieval_mode, enabled in (
                ("sparse", "sparse", False),
                ("dense", "dense", False),
                ("hybrid", "hybrid", False),
                ("hybrid_rerank", "hybrid", True),
            ):
                key = f"{intent}_{arm}"
                reports[key] = asyncio.run(
                    run_product_benchmark(
                        args.corpus,
                        args.queries,
                        args.labels,
                        mode=args.mode,
                        intent_policy=intent,
                        retrieval_mode=retrieval_mode,
                        enable_rerank=enabled,
                        embedding_provider=embedding if retrieval_mode != "sparse" else None,
                        reranker_provider=reranker if enabled else None,
                    )
                )
                print(f"completed {key} ({len(reports)}/8)", file=sys.stderr, flush=True)
        after = _snapshot(args)
        if before != after:
            raise RuntimeError("input or source file changed during run")
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_rss_scope = {
            "scope": "process_lifetime",
            "includes_embedding_and_reranker": True,
            "resident_model_ids": [embedding_record["model_id"], reranker_record["model_id"]],
        }
        for report in reports.values():
            report["peak_rss_scope"] = peak_rss_scope.copy()
            report["model_calls_scope"] = "arm_delta_excluding_initialization"
        result = {
            "mode": args.mode,
            "embedding_model": args.embedding_model,
            "code_revision": _code_revision(),
            "before": before,
            "after": after,
            "model_manifest_sha256": before["input_sha256"]["manifest"],
            "model_revisions": {
                record["model_id"]: record["revision"]
                for record in (embedding_record, reranker_record)
            },
            "threads": args.threads,
            "device": "cpu",
            "precision": "float32",
            "max_length": 512,
            "load_time_ms": {
                "embedding": embedding.status()["load_time_ms"],
                "reranker": reranker.status()["load_time_ms"],
            },
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
            "peak_rss_scope": peak_rss_scope,
            "model_calls_scope": "process_lifetime_including_initialization",
            "initialization_model_calls": initialization_calls,
            "model_calls": {
                "embedding": embedding.status()["inference_calls"],
                "reranker": reranker.status()["inference_calls"],
            },
            "external_model_calls": 0,
            "answer_generated": False,
            "ragas_status": "not_run",
            "whole_rag_verified": False,
            "reports": reports,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, json.JSONDecodeError) as exc:
        print(f"local retrieval comparison unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
