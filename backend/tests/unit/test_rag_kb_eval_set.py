from __future__ import annotations

import json
from pathlib import Path

REQUIRED_FIELDS = {
    "competitor",
    "dimension",
    "evidence",
    "expected_collector_action",
    "expected_gate",
    "expected_refresh_required",
    "id",
    "query",
    "scenario",
}
REQUIRED_EVIDENCE_FIELDS = {
    "candidate_origin",
    "snippet",
    "source_id",
    "source_type",
    "title",
}
REQUIRED_SCENARIOS = {
    "competitor_ambiguity",
    "feature_deprecated",
    "free_plan_conflict",
    "official_third_party_conflict",
    "pricing_change",
    "privacy_training_conflict",
    "retention_conflict",
    "security_conflict",
    "stale_kb_vs_live",
}
SUPPORTED_EXPECTED_GATES = {
    "collector_disambiguation",
    "consistency_blocker",
    "freshness_blocker",
}
LIVE_SOURCE_ORIGINS = {"browser_fetch", "crawl_page", "official_api", "web_fetch"}
LIVE_REQUIRED_SCENARIOS = REQUIRED_SCENARIOS - {"competitor_ambiguity"}
OFFICIAL_SOURCE_TYPES = {
    "official_changelog",
    "official_docs",
    "official_pricing",
    "trust_center",
    "webpage_verified",
}


def _load_entries() -> list[dict]:
    eval_path = (
        Path(__file__).resolve().parents[3] / "eval" / "rag-kb-quality-gate-eval.jsonl"
    )
    return [
        json.loads(line)
        for line in eval_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_rag_kb_quality_gate_eval_set_has_required_risk_scenarios() -> None:
    entries = _load_entries()
    entry_ids = [entry["id"] for entry in entries]
    scenarios = {entry["scenario"] for entry in entries}
    expected_gates = {
        gate
        for entry in entries
        for gate in entry["expected_gate"]
    }

    assert len(entries) >= len(REQUIRED_SCENARIOS)
    assert len(entry_ids) == len(set(entry_ids))
    assert REQUIRED_SCENARIOS <= scenarios
    assert {"consistency_blocker", "freshness_blocker"} <= expected_gates


def test_rag_kb_quality_gate_eval_cases_are_traceable_and_gateable() -> None:
    for entry in _load_entries():
        missing = REQUIRED_FIELDS - set(entry)
        assert not missing, f"{entry.get('id', '<missing id>')} missing {missing}"
        assert isinstance(entry["expected_gate"], list)
        assert entry["expected_gate"]
        assert set(entry["expected_gate"]) <= SUPPORTED_EXPECTED_GATES

        evidence = entry["evidence"]
        assert isinstance(evidence, list)
        assert len(evidence) >= 2
        origins = {item["candidate_origin"] for item in evidence}
        assert "rag_kb" in origins
        if entry["scenario"] in LIVE_REQUIRED_SCENARIOS:
            assert origins & LIVE_SOURCE_ORIGINS

        for item in evidence:
            item_missing = REQUIRED_EVIDENCE_FIELDS - set(item)
            assert not item_missing, f"{entry['id']} evidence missing {item_missing}"
            assert item["snippet"].strip()
            if item["candidate_origin"] == "rag_kb":
                assert item.get("fetched_at") or item.get("observed_at")
            if item["candidate_origin"] in LIVE_SOURCE_ORIGINS:
                assert item.get("url", "").startswith("https://")


def test_rag_kb_quality_gate_eval_set_covers_authority_conflicts() -> None:
    entries_by_scenario = {entry["scenario"]: entry for entry in _load_entries()}
    authority_case = entries_by_scenario["official_third_party_conflict"]
    source_types = {item["source_type"] for item in authority_case["evidence"]}

    assert "third_party_review" in source_types
    assert source_types & OFFICIAL_SOURCE_TYPES
    assert "consistency_blocker" in authority_case["expected_gate"]
