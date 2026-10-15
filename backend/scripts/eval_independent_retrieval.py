"""Opt-in offline comparison of the exposed, human-reviewed independent v1 set."""

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
from scripts.eval_live_products import (
    ROOT,
    local_knowledge_environment,
    redacted_json,
    write_redacted_json,
)


async def compare_retrieval(paths, embedding, reranker) -> dict:
    """Top-1 and top-3 share each arm's one ranking and the exact same corpus."""
    reports = {}
    arms = [(name + suffix, mode, rerank, policy)
            for policy, suffix in (("raw", ""), ("structured", "_structured"))
            for name, mode, rerank in (("sparse", "sparse", False),
                                       ("hybrid", "hybrid", False),
                                       ("hybrid_rerank", "hybrid", True))]
    for name, mode, rerank, policy in arms:
        reports[name] = await run_product_benchmark(
            *paths,
            top_k=3,
            candidate_top_k=20,
            product_scope="broad",
            retrieval_mode=mode,
            enable_rerank=rerank,
            intent_policy=policy,
            embedding_provider=embedding if mode != "sparse" else None,
            reranker_provider=reranker if rerank else None,
        )
    return reports


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--run", action="store_true", help="Run local models; default only lists fixed inputs"
    )
    args = parser.parse_args()
    prefix = ROOT / "eval/product-research-independent-v1"
    paths = tuple(Path(f"{prefix}-{kind}.jsonl") for kind in ("corpus", "queries", "labels"))
    inputs = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if not args.run:
        print(redacted_json({"status": "list_only", "input_sha256": inputs}))
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
                arms = await compare_retrieval(paths, embedding, reranker)
    if network_attempts:
        raise RuntimeError("Local model evaluation attempted network access")
    report = {
        "dataset": "independent-v1",
        "blind_holdout": False,
        "semantic_quality_verified": False,
        "limitations": (
            "Exposed 8-question sample; 6 answer, 1 insufficient, 1 clarify. "
            "Retrieval metrics do not establish answer accuracy."
        ),
        "input_sha256": inputs,
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
