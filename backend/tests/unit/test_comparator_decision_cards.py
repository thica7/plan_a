from packages.agents.comparator.decision_cards import build_decision_card_bundle
from packages.schema.messages import AGENT_MESSAGE_PAYLOAD_SCHEMAS
from packages.schema.models import ComparisonCell, ComparisonMatrix
from packages.schema.report_artifact import ClaimCard, ClaimCardBundle


def _claim(
    card_id: str,
    competitor: str,
    dimension: str,
    strength: str = "strong",
    confidence: float | None = None,
) -> ClaimCard:
    resolved_confidence = (
        confidence if confidence is not None else 0.86 if strength == "strong" else 0.62
    )
    return ClaimCard(
        id=card_id,
        run_id="run-1",
        competitor=competitor,
        dimension=dimension,
        claim_type="dimension_claim",
        claim=f"{competitor} has strong {dimension} support.",
        source_ids=[f"raw-source-{card_id}"],
        confidence=resolved_confidence,
        evidence_strength=strength,
        support_level="official" if strength == "strong" else "single_source",
        scope=dimension,
        caveats=[],
        conflicts=[],
        applicability=dimension,
        produced_by="analyst",
        producer_stage=f"analyst:{dimension}:{competitor}",
        derived_from=[f"raw-source-{card_id}"],
        metadata={},
    )


def _gap_claim(card_id: str, competitor: str, dimension: str) -> ClaimCard:
    return ClaimCard(
        id=card_id,
        run_id="run-1",
        competitor=competitor,
        dimension=dimension,
        claim_type="evidence_gap",
        claim=f"No supported {dimension} claim was produced for {competitor}.",
        source_ids=[],
        confidence=0.0,
        evidence_strength="insufficient",
        support_level="gap",
        scope=dimension,
        caveats=["Missing evidence."],
        conflicts=[],
        applicability=dimension,
        produced_by="analyst",
        producer_stage=f"analyst:{dimension}:{competitor}",
        derived_from=[],
        metadata={},
    )


def _bundle(
    competitor: str,
    dimension: str,
    cards: list[ClaimCard],
) -> ClaimCardBundle:
    return ClaimCardBundle(
        run_id="run-1",
        competitor=competitor,
        dimension=dimension,
        cards=cards,
        source_ids=[source_id for card in cards for source_id in card.source_ids],
        coverage={},
        gap_count=sum(1 for card in cards if card.support_level == "gap"),
        generated_at="2026-06-21T00:00:00Z",
        producer_context={},
    )


def test_build_decision_cards_from_matrix_and_claims() -> None:
    claim = _claim("1", "Cursor", "pricing")
    matrix = ComparisonMatrix(
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Best price fit",
                source_ids=claim.source_ids,
                confidence=0.86,
            ),
            ComparisonCell(
                competitor="GitHub Copilot",
                dimension="pricing",
                value="Enterprise bundle",
                source_ids=["raw-source-2"],
                confidence=0.7,
            ),
        ],
        winner_by_dimension={"pricing": "Cursor"},
        summary=["Cursor wins pricing for prototype-heavy users."],
    )
    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[_bundle("Cursor", "pricing", [claim])],
        matrix=matrix,
        fallback_used=False,
    )
    assert bundle.recommendation_card_id is not None
    assert any(card.decision_type == "dimension_winner" for card in bundle.cards)
    assert any(card.decision_type == "overall_recommendation" for card in bundle.cards)
    assert bundle.cards[0].produced_by == "comparator"


def test_fallback_decision_cards_are_not_strong() -> None:
    claim = _claim("1", "Cursor", "pricing", strength="strong")
    matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="High-confidence fallback evidence",
                source_ids=claim.source_ids,
                confidence=0.95,
            )
        ],
        winner_by_dimension={"pricing": "Cursor"},
        summary=[],
    )
    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[_bundle("Cursor", "pricing", [claim])],
        matrix=matrix,
        fallback_used=True,
    )
    assert all(card.posture != "strong" for card in bundle.cards)
    assert all(card.confidence <= 0.74 for card in bundle.cards)


def test_decision_cards_do_not_use_gap_claim_cards_as_support() -> None:
    gap_claim = _gap_claim("gap-1", "Cursor", "pricing")
    matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="No supported evidence",
                source_ids=[],
                confidence=0.0,
            )
        ],
        winner_by_dimension={"pricing": "Cursor"},
        summary=["Cursor appears to win, but evidence is missing."],
    )

    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[_bundle("Cursor", "pricing", [gap_claim])],
        matrix=matrix,
        fallback_used=False,
    )

    assert bundle.cards == []
    assert bundle.recommendation_card_id is None


def test_decision_cards_do_not_copy_raw_matrix_text_as_evidence() -> None:
    claim = _claim("1", "Cursor", "pricing")
    matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="RAW MATRIX ONLY TEXT SHOULD NOT APPEAR",
                source_ids=["matrix-only-source"],
                confidence=0.86,
            )
        ],
        winner_by_dimension={"pricing": "Cursor"},
        summary=[],
    )

    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[_bundle("Cursor", "pricing", [claim])],
        matrix=matrix,
        fallback_used=False,
    )

    text = "\n".join(
        f"{card.recommendation}\n{card.rationale}" for card in bundle.cards
    )
    assert "RAW MATRIX ONLY TEXT SHOULD NOT APPEAR" not in text
    assert all(card.source_ids == claim.source_ids for card in bundle.cards)


def test_overall_recommendation_requires_supporting_claim_cards() -> None:
    claim = _claim("1", "Cursor", "pricing")
    matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["pricing", "security"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Supported pricing evidence",
                source_ids=claim.source_ids,
                confidence=0.86,
            )
        ],
        winner_by_dimension={"pricing": "Cursor", "security": "Cursor"},
        summary=["Cursor wins security in the matrix summary."],
    )

    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[_bundle("Cursor", "pricing", [claim])],
        matrix=matrix,
        fallback_used=False,
    )

    assert any(card.decision_type == "overall_recommendation" for card in bundle.cards)
    assert all(card.claim_card_ids for card in bundle.cards)
    assert not any(
        card.subject == "security" and card.decision_type == "dimension_winner"
        for card in bundle.cards
    )


def test_overall_recommendation_is_not_strong_for_mixed_dimension_strength() -> None:
    pricing_claim = _claim("1", "Cursor", "pricing", strength="strong")
    security_claim = _claim(
        "2",
        "Cursor",
        "security",
        strength="moderate",
        confidence=0.86,
    )
    matrix = ComparisonMatrix(
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing", "security"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Strong pricing evidence",
                source_ids=pricing_claim.source_ids,
                confidence=0.86,
            ),
            ComparisonCell(
                competitor="Cursor",
                dimension="security",
                value="Moderate security evidence",
                source_ids=security_claim.source_ids,
                confidence=0.86,
            ),
        ],
        winner_by_dimension={"pricing": "Cursor", "security": "Cursor"},
        summary=[],
    )

    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[
            _bundle("Cursor", "pricing", [pricing_claim]),
            _bundle("Cursor", "security", [security_claim]),
        ],
        matrix=matrix,
        fallback_used=False,
    )

    overall = next(
        card for card in bundle.cards if card.decision_type == "overall_recommendation"
    )
    assert overall.evidence_strength != "strong"
    assert overall.posture != "strong"


def test_no_overall_recommendation_for_cross_dimension_tie() -> None:
    cursor_claim = _claim("1", "Cursor", "pricing")
    copilot_claim = _claim("2", "GitHub Copilot", "security")
    matrix = ComparisonMatrix(
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing", "security"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Cursor pricing evidence",
                source_ids=cursor_claim.source_ids,
                confidence=0.86,
            ),
            ComparisonCell(
                competitor="GitHub Copilot",
                dimension="security",
                value="Copilot security evidence",
                source_ids=copilot_claim.source_ids,
                confidence=0.86,
            ),
        ],
        winner_by_dimension={
            "pricing": "Cursor",
            "security": "GitHub Copilot",
        },
        summary=[],
    )

    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[
            _bundle("Cursor", "pricing", [cursor_claim]),
            _bundle("GitHub Copilot", "security", [copilot_claim]),
        ],
        matrix=matrix,
        fallback_used=False,
    )

    assert bundle.recommendation_card_id is None
    assert not any(
        card.decision_type == "overall_recommendation" for card in bundle.cards
    )
    assert bundle.producer_context["overall_winner_tie"] is True


def test_no_overall_recommendation_for_non_tied_split_support() -> None:
    cursor_pricing_claim = _claim("1", "Cursor", "pricing")
    cursor_feature_claim = _claim("2", "Cursor", "feature")
    copilot_security_claim = _claim("3", "GitHub Copilot", "security")
    matrix = ComparisonMatrix(
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing", "feature", "security"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Cursor pricing evidence",
                source_ids=cursor_pricing_claim.source_ids,
                confidence=0.86,
            ),
            ComparisonCell(
                competitor="Cursor",
                dimension="feature",
                value="Cursor feature evidence",
                source_ids=cursor_feature_claim.source_ids,
                confidence=0.86,
            ),
            ComparisonCell(
                competitor="GitHub Copilot",
                dimension="security",
                value="Copilot security evidence",
                source_ids=copilot_security_claim.source_ids,
                confidence=0.86,
            ),
        ],
        winner_by_dimension={
            "pricing": "Cursor",
            "feature": "Cursor",
            "security": "GitHub Copilot",
        },
        summary=[],
    )

    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[
            _bundle("Cursor", "pricing", [cursor_pricing_claim]),
            _bundle("Cursor", "feature", [cursor_feature_claim]),
            _bundle("GitHub Copilot", "security", [copilot_security_claim]),
        ],
        matrix=matrix,
        fallback_used=False,
    )

    assert bundle.recommendation_card_id is None
    assert not any(
        card.decision_type == "overall_recommendation" for card in bundle.cards
    )
    assert bundle.producer_context["overall_winner_split"] is True
    assert bundle.producer_context["overall_winner_counts"] == {
        "Cursor": 2,
        "GitHub Copilot": 1,
    }


def test_decision_card_bundle_message_payload_has_schema_name() -> None:
    claim = _claim("1", "Cursor", "pricing")
    matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Supported pricing evidence",
                source_ids=claim.source_ids,
                confidence=0.86,
            )
        ],
        winner_by_dimension={"pricing": "Cursor"},
        summary=[],
    )
    bundle = build_decision_card_bundle(
        run_id="run-1",
        claim_bundles=[_bundle("Cursor", "pricing", [claim])],
        matrix=matrix,
        fallback_used=False,
    )

    payload_model = AGENT_MESSAGE_PAYLOAD_SCHEMAS["DecisionCardBundle"]
    payload = payload_model.model_validate(
        {"bundle": bundle.model_dump(mode="json")}
    )

    assert payload.schema_name == "DecisionCardBundle"
