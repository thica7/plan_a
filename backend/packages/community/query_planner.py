from __future__ import annotations


def build_community_queries(
    *,
    competitor: str,
    dimension: str,
    topic: str,
    limit: int = 3,
) -> list[str]:
    normalized_dimension = dimension.casefold().replace("-", "_")
    if "pricing" in normalized_dimension or "billing" in normalized_dimension:
        intents = [
            "pricing usage limit reddit",
            "pricing usage limit forum",
            "billing quota GitHub discussion",
            "hidden limit cost overage",
        ]
    elif "review" in normalized_dimension or "feedback" in normalized_dimension:
        intents = [
            "G2 reviews pros cons",
            "Capterra reviews",
            "TrustRadius reviews",
            "customer complaints alternatives",
        ]
    elif any(
        token in normalized_dimension
        for token in ("persona", "user", "customer", "buyer", "adoption", "switching")
    ):
        intents = [
            "user reviews pros cons reddit",
            f"switched from {competitor} to alternative",
            "adoption blockers enterprise developers",
            "onboarding workflow fit complaint",
        ]
    elif "feature" in normalized_dimension or "capability" in normalized_dimension:
        intents = [
            "context window issue discussion",
            "agent mode complaints reddit",
            "feature limitation forum",
            "bug issue developer workflow",
        ]
    else:
        intents = [
            "reddit user complaints",
            "forum limitations",
            "GitHub issue discussion",
            "developer review pros cons",
        ]
    return _dedupe(
        f"{competitor} {intent} {topic}".strip()
        for intent in intents
    )[: max(0, limit)]


def _dedupe(queries: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in queries:
        query = " ".join(str(item).split()).strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        result.append(query)
    return result
