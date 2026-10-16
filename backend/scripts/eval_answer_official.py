"""Bounded official-document diagnostics with explicit candidate/human review modes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from packages.business_intel.official_registry import registered_document, registry_snapshot
from scripts.eval_official_writer import ROOT, run_live, runtime_questions


def digest(data):
    return hashlib.sha256(data).hexdigest()


def runtime_payload(case):
    """Only questions and source identities cross into production execution."""
    return {key: case[key] for key in ("id", "product", "question")} | {
        "sources": [
            {key: source[key] for key in ("id", "title", "url")} for source in case["sources"]
        ]
    }


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0


def prepare_inputs(
    path, *, mode, case_ids=None, input_hash=None, registry_hash=None, manifest_hash=None
):
    if mode not in {"candidate-diagnostic", "human-reviewed"}:
        raise ValueError("explicit supported review mode is required")
    path = Path(path)
    frozen_bytes = path.read_bytes()
    actual_input = digest(frozen_bytes)
    if input_hash and actual_input != input_hash:
        raise ValueError("input hash drift")
    cases = [json.loads(line) for line in frozen_bytes.decode().splitlines() if line.strip()]
    if not 1 <= len(cases) <= 8 or len({row.get("id") for row in cases}) != len(cases):
        raise ValueError("one to eight distinct cases are required")
    for row in cases:
        if not all(_nonblank(row.get(key)) for key in ("id", "product", "question")):
            raise ValueError("case identity and question must be nonblank strings")
        if not isinstance(row.get("sources"), list) or not 1 <= len(row["sources"]) <= 8:
            raise ValueError("one to eight source identities are required per case")
        for source in row["sources"]:
            if not all(_nonblank(source.get(key)) for key in ("id", "title", "url")):
                raise ValueError("invalid source identity")
        if mode == "human-reviewed":
            try:
                reviewed = (
                    row.get("review_status") == "reviewed"
                    and _nonblank(row.get("reviewed_by"))
                    and _utc(row.get("reviewed_at", ""))
                )
            except (ValueError, TypeError, AttributeError):
                reviewed = False
            if not reviewed:
                raise ValueError("human review of every input case is required")
    by_id = {row["id"]: row for row in cases}
    selected_ids = list(case_ids) if case_ids is not None else list(by_id)
    if (
        not selected_ids
        or len(set(selected_ids)) != len(selected_ids)
        or any(case_id not in by_id for case_id in selected_ids)
    ):
        raise ValueError("invalid case selection")
    if len(selected_ids) > 4:
        raise ValueError("select at most four questions per run")
    selected = [by_id[case_id] for case_id in selected_ids]
    if len(runtime_questions(selected)) > 500:
        raise ValueError("combined decision question exceeds 500 characters; split the selection")
    current_registry = registry_snapshot()[1]
    if registry_hash and registry_hash != current_registry:
        raise ValueError("registry hash drift")
    payloads = [runtime_payload(row) for row in selected]
    for row in payloads:
        for source in row["sources"]:
            if registered_document(row["product"], source["url"]) is None:
                raise ValueError("source is not in exact-document official registry")
    if digest(path.read_bytes()) != actual_input:
        raise ValueError("input hash drift during validation")
    manifest = {
        "dataset": path.name,
        "input_sha256": actual_input,
        "registry_sha256": current_registry,
        "review_mode": mode,
        "input_cases": len(cases),
        "selected_cases": len(payloads),
        "case_ids": selected_ids,
        "not_selected": [key for key in by_id if key not in selected_ids],
        "source_urls": [s["url"] for row in payloads for s in row["sources"]],
        "runtime_payload_sha256": digest(
            json.dumps(payloads, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ),
        "semantic_quality": "pending_human",
        "input_mode": "live_official_documents",
        "blind_holdout": False,
        "human_reviewed": mode == "human-reviewed",
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "official_runner_sha256": digest(
            Path(__file__).with_name("eval_official_writer.py").read_bytes()
        ),
        "runtime_helpers_sha256": digest(
            b"".join(
                name.encode() + Path(__file__).with_name(name).read_bytes()
                for name in (
                    "eval_evidence_binding.py",
                    "eval_live_products.py",
                    "export_agent_eval.py",
                )
            )
        ),
        "production_code_sha256": digest(
            b"".join(
                str(p.relative_to(ROOT)).encode() + p.read_bytes()
                for p in sorted((ROOT / "backend/packages").rglob("*.py"))
            )
        ),
    }
    actual_manifest = digest(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    if manifest_hash and manifest_hash != actual_manifest:
        raise ValueError("manifest hash drift")
    manifest["manifest_sha256"] = actual_manifest
    return payloads, manifest


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "eval/product-answer-holdout-v1.jsonl")
    parser.add_argument("--mode", choices=["candidate-diagnostic", "human-reviewed"], required=True)
    parser.add_argument("--case-ids", nargs="+")
    parser.add_argument("--expected-input-sha256")
    parser.add_argument("--expected-registry-sha256")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--output", type=Path, default=Path("/tmp/answer-official-" + uuid4().hex))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--capture-only", action="store_true")
    args = parser.parse_args(argv)
    payloads, manifest = prepare_inputs(
        args.cases,
        mode=args.mode,
        case_ids=args.case_ids,
        input_hash=args.expected_input_sha256,
        registry_hash=args.expected_registry_sha256,
        manifest_hash=args.expected_manifest_sha256,
    )
    if not args.run:
        print(
            json.dumps(
                manifest | {"mode": "preview", "fetch_attempts": 0, "llm_transport_attempts": 0},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not all(
        (args.expected_input_sha256, args.expected_registry_sha256, args.expected_manifest_sha256)
    ):
        raise ValueError("run requires three frozen input, registry and manifest hashes")
    if not 0 < args.timeout <= 900:
        raise ValueError("run timeout must be positive and at most 900 seconds")
    print(
        json.dumps(
            await run_live(
                payloads,
                manifest,
                args.output,
                timeout=args.timeout,
                capture_only=args.capture_only,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
