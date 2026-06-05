def __getattr__(name: str):
    if name == "build_search_queries":
        from packages.research.discovery.planner import build_search_queries

        return build_search_queries
    if name in {
        "homepage_candidates",
        "search_result_candidates",
        "trusted_registry_candidates",
    }:
        from packages.research.discovery import providers

        return getattr(providers, name)
    if name == "rank_and_dedupe_candidates":
        from packages.research.discovery.ranking import rank_and_dedupe_candidates

        return rank_and_dedupe_candidates
    raise AttributeError(name)

__all__ = [
    "build_search_queries",
    "homepage_candidates",
    "rank_and_dedupe_candidates",
    "search_result_candidates",
    "trusted_registry_candidates",
]
