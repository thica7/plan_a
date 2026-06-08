import json
from pathlib import Path


def test_phase2_evidence_seed_has_50_records() -> None:
    rows = _jsonl("data/evidence_seed.jsonl")

    assert len(rows) == 50
    assert {row["dimension"] for row in rows} >= {
        "pricing",
        "feature",
        "persona",
        "security",
        "integrations",
    }
    assert all(row["reliability"] >= 0.7 for row in rows)


def test_phase2_golden_set_has_at_least_50_labeled_cases() -> None:
    rows = _jsonl("data/golden_set.jsonl")

    assert len(rows) >= 50
    assert {row["cohort"] for row in rows} >= {
        "core_l1",
        "core_l2",
        "core_l3",
        "boundary",
        "adversarial_phantom",
        "enterprise_l1",
        "enterprise_l2",
        "enterprise_l3",
        "adversarial_compliance",
        "observability",
        "pydantic_ai",
        "temporal_cutover",
    }
    assert {row["expected_layer"] for row in rows} == {"L1", "L2", "L3"}


def _jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
