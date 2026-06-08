from __future__ import annotations

from packages.schema.enterprise import CompetitorLayerAssessment

LAYER_KEYWORDS: dict[str, set[str]] = {
    "L1": {
        "battlecard",
        "direct",
        "pricing",
        "feature",
        "replacement",
        "vs",
    },
    "L2": {
        "adjacent",
        "alternative",
        "workflow",
        "integration",
        "ecosystem",
        "partner",
    },
    "L3": {
        "landscape",
        "market",
        "category",
        "trend",
        "industry",
        "benchmark",
    },
}


def assess_competitor_layer(
    *,
    topic: str,
    competitors: list[str],
    dimensions: list[str],
    requested_layer: str | None = None,
) -> CompetitorLayerAssessment:
    """Classify the project into the L1/L2/L3 competitive-intel model."""

    if requested_layer in {"L1", "L2", "L3"}:
        return CompetitorLayerAssessment(
            layer=requested_layer,
            confidence=1.0,
            rationale=f"Layer was supplied by the caller: {requested_layer}.",
            signals=["requested_layer"],
        )

    text = " ".join([topic, *dimensions]).casefold()
    scores = {
        layer: sum(1 for keyword in keywords if keyword in text)
        for layer, keywords in LAYER_KEYWORDS.items()
    }
    signals: list[str] = []

    competitor_count = len([item for item in competitors if item.strip()])
    if competitor_count >= 5:
        scores["L3"] += 2
        signals.append("many_competitors")
    elif competitor_count >= 3:
        scores["L2"] += 1
        signals.append("multi_competitor_set")
    elif competitor_count >= 1:
        scores["L1"] += 1
        signals.append("focused_competitor_set")

    if any("pricing" in item.casefold() for item in dimensions):
        scores["L1"] += 1
        signals.append("pricing_dimension")
    if any("market" in item.casefold() or "trend" in item.casefold() for item in dimensions):
        scores["L3"] += 1
        signals.append("market_dimension")
    if any(
        "integration" in item.casefold() or "ecosystem" in item.casefold()
        for item in dimensions
    ):
        scores["L2"] += 1
        signals.append("ecosystem_dimension")

    layer = max(scores, key=lambda item: (scores[item], _layer_priority(item)))
    total = max(sum(scores.values()), 1)
    confidence = min(0.95, max(0.55, scores[layer] / total + 0.35))
    matched_keywords = [
        f"{layer}:{keyword}"
        for layer_name, keywords in LAYER_KEYWORDS.items()
        for keyword in keywords
        if layer_name == layer and keyword in text
    ]
    signals.extend(matched_keywords)
    return CompetitorLayerAssessment(
        layer=layer,
        confidence=round(confidence, 2),
        rationale=_rationale(layer, competitor_count),
        signals=signals or ["default_direct_competition"],
    )


def _layer_priority(layer: str) -> int:
    return {"L1": 3, "L2": 2, "L3": 1}.get(layer, 0)


def _rationale(layer: str, competitor_count: int) -> str:
    if layer == "L1":
        return f"Focused on direct product comparison across {competitor_count} competitor(s)."
    if layer == "L2":
        return "Signals point to adjacent workflow, ecosystem, or alternative-category analysis."
    return "Signals point to category, market landscape, or benchmark-level analysis."
