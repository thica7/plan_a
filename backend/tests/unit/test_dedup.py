from __future__ import annotations

from packages.knowledge.dedup import batch_dedup, dedup_document, hamming_distance, simhash


def test_simhash_is_stable_64_bit_value() -> None:
    first = simhash("Pricing starts at 10 dollars per seat.")
    second = simhash("Pricing starts at 10 dollars per seat.")

    assert first == second
    assert 0 <= first < 2**64


def test_dedup_document_detects_near_duplicate_text() -> None:
    existing = [simhash("Starter pricing is 10 dollars per user each month.")]

    assert dedup_document(
        "Starter pricing is 10 dollars per user each month.",
        existing,
        threshold=5,
    )
    assert not dedup_document("Enterprise security controls and SSO.", existing, threshold=5)


def test_batch_dedup_preserves_first_unique_texts() -> None:
    texts = [
        "Feature matrix includes SSO and audit logs.",
        "Feature matrix includes SSO and audit logs.",
        "Reviews mention responsive support.",
    ]

    assert batch_dedup(texts, threshold=5) == [texts[0], texts[2]]
    assert hamming_distance(simhash(texts[0]), simhash(texts[0])) == 0
