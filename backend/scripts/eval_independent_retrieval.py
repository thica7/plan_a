"""Opt-in offline retrieval comparison with explicit review and product scopes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from packages.knowledge.embeddings import get_embedding_provider_from_env
from packages.knowledge.product_benchmark import (
    _reranker_ready,
    provider_readiness,
    run_product_benchmark,
)
from packages.knowledge.reranker import get_reranker_provider_from_env
from packages.knowledge.product_eval_data import load_dataset
from scripts.eval_live_products import (
    ROOT,
    local_knowledge_environment,
    redacted_json,
    write_redacted_json,
)


def _input_hashes(paths) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def load_evaluation_inputs(prefix: Path, evaluation_mode: str):
    if evaluation_mode not in {"formal", "candidate-diagnostic"}:
        raise ValueError("Unsupported evaluation mode")
    paths = tuple(Path(f"{prefix}-{kind}.jsonl") for kind in ("corpus", "queries", "labels"))
    hashes = _input_hashes(paths)
    dataset = load_dataset(*paths, require_reviewed=evaluation_mode == "formal")
    verify_input_hashes(paths, hashes)
    return paths, hashes, dataset


def verify_input_hashes(paths, expected: dict[str, str]) -> None:
    if _input_hashes(paths) != expected:
        raise ValueError("Dataset inputs changed during evaluation")


def retrieval_code_hashes() -> dict[str, str]:
    """Hash imported modules, including when PYTHONPATH selects a frozen baseline."""
    from importlib import import_module

    names = ("query_intent", "lexical", "repository", "retrieval", "product_benchmark", "ingestion")
    hashes = {name: hashlib.sha256(Path(import_module(f"packages.knowledge.{name}").__file__)
                                  .read_bytes()).hexdigest() for name in names}
    from importlib.util import find_spec
    if find_spec("packages.knowledge.evidence_context") is not None:
        hashes["evidence_context"] = hashlib.sha256(Path(import_module(
            "packages.knowledge.evidence_context").__file__).read_bytes()).hexdigest()
    return hashes


async def compare_retrieval(
    paths, embedding, reranker, *, evaluation_mode="formal", product_scope="broad", ablation=False
) -> dict:
    """Top-1 and top-3 share each arm's one ranking and the exact same corpus."""
    reports = {}
    arms = [(name + suffix, mode, rerank, policy)
            for policy, suffix in (("raw", ""), ("structured", "_structured"))
            for name, mode, rerank in (("sparse", "sparse", False),
                                       ("hybrid", "hybrid", False),
                                       ("hybrid_rerank", "hybrid", True))]
    if ablation:
        arms = [(f"{name}_{strategy}", mode, rerank, policy, fusion, context)
                for strategy, policy, fusion, context in (
                    ("raw", "raw", False, False), ("planned", "structured", False, False),
                    ("dual", "structured", True, False), ("dual_context", "structured", True, True))
                for name, mode, rerank in (("sparse", "sparse", False),
                                           ("hybrid", "hybrid", False),
                                           ("hybrid_rerank", "hybrid", True))]
    else:
        arms = [(*arm, None, None) for arm in arms]
    for name, mode, rerank, policy, fusion, context in arms:
        controls = {"enable_query_fusion": fusion, "expand_context": context} if ablation else {}
        reports[name] = await run_product_benchmark(
            *paths,
            mode=evaluation_mode,
            top_k=3,
            candidate_top_k=20,
            product_scope=product_scope,
            retrieval_mode=mode,
            enable_rerank=rerank,
            intent_policy=policy,
            embedding_provider=embedding if mode != "sparse" else None,
            reranker_provider=reranker if rerank else None,
            **controls,
        )
    return reports


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-prefix", type=Path,
                        default=ROOT / "eval/product-research-independent-v1")
    parser.add_argument("--mode", choices=("formal", "candidate-diagnostic"), default="formal")
    parser.add_argument("--product-scope", choices=("broad", "product"), default="broad")
    parser.add_argument("--ablation", action="store_true",
                        help="Compare raw/planned/dual/dual-context with 12 controlled arms")
    parser.add_argument(
        "--run", action="store_true", help="Run local models; default only lists fixed inputs"
    )
    args = parser.parse_args()
    prefix = args.dataset_prefix
    paths, inputs, dataset = load_evaluation_inputs(prefix, args.mode)
    code_hashes = retrieval_code_hashes()
    if not args.run:
        print(redacted_json({"status": "list_only", "input_sha256": inputs,
                             "mode": args.mode, "product_scope": args.product_scope,
                             "ablation": args.ablation,
                             "counts": dataset.counts, "retrieval_code_sha256": code_hashes}))
        return
    network_attempts = 0

    def deny_network(*_args, **_kwargs):
        nonlocal network_attempts
        network_attempts += 1
        raise RuntimeError("Network disabled during independent local retrieval evaluation")

    with tempfile.TemporaryDirectory(prefix="independent-retrieval-") as directory:
        with local_knowledge_environment(args.local_profile, Path(directory)) as profile:
            with (
                patch.object(socket.socket, "connect", deny_network),
                patch.object(socket.socket, "connect_ex", deny_network),
                patch.object(socket.socket, "sendto", deny_network),
            ):
                import torch

                torch.set_num_threads(2)
                embedding = get_embedding_provider_from_env()
                reranker = get_reranker_provider_from_env()
                before_embedding = embedding.status().get("inference_calls", 0)
                before_reranker = reranker.status().get("inference_calls", 0) if reranker else 0
                embedding.embed_query("本地检索初始化")
                if reranker:
                    reranker.rerank("初始化", ["本地精排初始化"])
                if not provider_readiness(embedding.status())["semantic_ready"] or not (
                    reranker and _reranker_ready(reranker.status())
                ):
                    raise ValueError("Initialized local E5 and cross-encoder models are required")
                warmup = {
                    "embedding": embedding.status()["inference_calls"] - before_embedding,
                    "reranker": reranker.status()["inference_calls"] - before_reranker,
                }
                arms = await compare_retrieval(paths, embedding, reranker,
                    evaluation_mode=args.mode, product_scope=args.product_scope, ablation=args.ablation)
    if network_attempts:
        raise RuntimeError("Local model evaluation attempted network access")
    verify_input_hashes(paths, inputs)
    if retrieval_code_hashes() != code_hashes:
        raise ValueError("Retrieval code changed during evaluation")
    report = {
        "dataset": prefix.name,
        "mode": args.mode,
        "product_scope": args.product_scope,
        "ablation": args.ablation,
        "counts": dataset.counts,
        "blind_holdout": False,
        "semantic_quality_verified": False,
        "limitations": (
            "Small local sample; candidate labels are not independent human acceptance. "
            "Products or sources may have been exposed. Retrieval metrics do not establish "
            "answer accuracy, clarification behavior, or large-corpus ranking quality."
        ),
        "input_sha256": inputs,
        "retrieval_code_sha256": code_hashes,
        "profile": profile,
        "top_k": [1, 3],
        "top_1_scope": "recall_at_1 in each top-3 ranking",
        "warmup_inference_calls": warmup,
        "external_model_calls": 0,
        "network_attempts": network_attempts,
        "arms": arms,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_redacted_json(args.output, report)
    print(
        redacted_json(
            {
                "status": "completed",
                "output": str(args.output),
                "external_model_calls": 0,
                "network_attempts": network_attempts,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
