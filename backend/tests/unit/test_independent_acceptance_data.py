import hashlib
import json
from collections import Counter
from pathlib import Path

from packages.knowledge.product_eval_data import load_dataset
from scripts.eval_live_products import acceptance_request

ROOT = Path(__file__).resolve().parents[3]
PREFIX = ROOT / "eval/product-research-independent-v1"


def test_independent_reviewed_dataset_keeps_provenance_and_six_answer_denominator():
    dataset = load_dataset(*(f"{PREFIX}-{kind}.jsonl" for kind in ("corpus", "queries", "labels")))
    manifest = json.loads(Path(f"{PREFIX}-manifest.json").read_text())
    assert len(dataset.sources) == 22
    assert len(dataset.queries) == 8
    assert Counter(row["expected_outcome"] for row in dataset.labels.values()) == {
        "answer": 6,
        "insufficient": 1,
        "clarify": 1,
    }
    assert (
        manifest["review_record"]["review_source"]
        == "request_user_input_async_call_10e1726901774af98094b651290c4101"
    )
    assert manifest["blind_holdout"] is False
    assert manifest["new_sources"] == 6 and manifest["distractor_sources"] == 16
    assert (
        sum(row["market"] == "全球" and row["role"] == "source" for row in dataset.sources.values())
        == 13
    )
    for name, digest in manifest["files_sha256"].items():
        assert hashlib.sha256((ROOT / "eval" / name).read_bytes()).hexdigest() == digest
    assert all(
        source["text_kind"] == "summary_with_short_official_quotes"
        for key, source in dataset.sources.items()
        if key.startswith("ind-")
    )
    assert {row["reviewed_by"] for row in dataset.labels.values()} == {"project_user"}


def test_hardware_case_requests_two_dimensions_and_preserves_battery_scope():
    cases = [
        json.loads(row)
        for row in (ROOT / "eval/hardware-comparison-v1.jsonl").read_text().splitlines()
    ]
    assert len(cases) == 1
    request = acceptance_request(cases[0])
    assert request.research_depth == "standard"
    assert request.dimensions == ["feature", "persona"]
    assert request.target_product.name == "Steam Deck OLED"
    assert request.competitors == ["Steam Deck LCD"]
    assert "所有游戏" in request.topic and "大陆" in request.topic
