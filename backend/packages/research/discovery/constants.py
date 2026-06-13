from __future__ import annotations

SOURCE_ORIGIN_PRIORITY: dict[str, int] = {
    "trusted_registry": 400,
    "perplexity": 300,
    "web_search": 280,
    "community_search": 260,
    "homepage_derived": 120,
    "llm_fallback": 40,
}
