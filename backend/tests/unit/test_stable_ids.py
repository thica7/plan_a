from packages.identity.stable_ids import (
    compute_claim_id,
    compute_competitor_set_hash,
    compute_content_hash,
    compute_evidence_id,
    compute_topic_normalized,
    normalize_dimension_key,
    normalize_text,
    normalize_url,
)


def test_normalize_url_strips_tracking_query_fragment_and_trailing_slash() -> None:
    assert (
        normalize_url("https://Cursor.sh/pricing/?utm_source=ad#plans")
        == "https://cursor.sh/pricing"
    )


def test_normalize_url_preserves_path_case() -> None:
    assert normalize_url("https://Cursor.SH/Pricing") == "https://cursor.sh/Pricing"


def test_normalize_text_collapses_whitespace_and_case() -> None:
    assert normalize_text("  Cursor   PRO\nPlan  ") == "cursor pro plan"


def test_normalize_dimension_key_is_case_and_space_insensitive() -> None:
    assert normalize_dimension_key("Enterprise Readiness") == "enterprise_readiness"


def test_content_hash_accepts_text_and_bytes() -> None:
    assert compute_content_hash("same") == compute_content_hash(b"same")


def test_evidence_id_is_stable_across_url_noise_and_dimension_case() -> None:
    first = compute_evidence_id(
        "https://Cursor.sh/pricing/?utm_source=ad",
        "content-hash",
        "comp-1",
        "Pricing",
    )
    second = compute_evidence_id(
        "https://cursor.sh/pricing",
        "content-hash",
        "comp-1",
        "pricing",
    )

    assert first == second


def test_evidence_id_changes_for_different_competitors() -> None:
    first = compute_evidence_id("https://x.com/a", "hash", "comp-1", "pricing")
    second = compute_evidence_id("https://x.com/a", "hash", "comp-2", "pricing")

    assert first != second


def test_claim_id_is_stable_for_equivalent_text_and_type() -> None:
    first = compute_claim_id("evidence-1", " Cursor Pro costs $20/month. ", "Pricing Tier")
    second = compute_claim_id("evidence-1", "cursor pro costs $20/month.", "pricing_tier")

    assert first == second


def test_competitor_set_hash_is_order_independent_and_deduped() -> None:
    assert compute_competitor_set_hash(["A", "B", "A"]) == compute_competitor_set_hash(["B", "A"])


def test_topic_normalized_handles_mixed_punctuation() -> None:
    assert compute_topic_normalized("AI编程助手， 定价！功能") == "ai编程助手 定价 功能"
