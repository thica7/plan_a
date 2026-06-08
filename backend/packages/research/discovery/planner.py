from __future__ import annotations

from packages.research.models import RepairTask, ResearchBrief


def build_search_queries(
    brief: ResearchBrief,
    *,
    repair_tasks: list[RepairTask] | None = None,
) -> list[str]:
    queries: list[str] = []
    task_queries = [
        query
        for task in repair_tasks or []
        if _same_branch(brief, task)
        for query in task.query_hints
    ]
    queries.extend(task_queries)
    queries.extend(_dimension_queries(brief))
    return _dedupe_queries(queries)[: brief.max_search_queries]


def _dimension_queries(brief: ResearchBrief) -> list[str]:
    topic_suffix = f"{brief.topic} official source".strip()
    competitor = brief.competitor
    key = brief.dimension.casefold()
    if "pricing" in key:
        intents = [
            "pricing plans billing usage limits",
            "API pricing token cost official docs",
            "enterprise pricing cost management",
        ]
    elif "persona" in key or "user" in key:
        intents = [
            "customers use cases case studies enterprise",
            "ideal customer profile buyer persona public evidence",
            "solutions teams developers official",
        ]
    elif "security" in key or "trust" in key:
        intents = [
            "security trust compliance official docs",
            "privacy SOC ISO SSO SCIM enterprise",
        ]
    else:
        intents = [
            "official product capabilities unique features",
            "model documentation supported workflow coverage",
            "developer docs features API",
        ]
    return [f"{competitor} {intent} {topic_suffix}" for intent in intents]


def _same_branch(brief: ResearchBrief, task: RepairTask) -> bool:
    if task.dimension != brief.dimension:
        return False
    return task.competitor in {None, brief.competitor}


def _dedupe_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for query in queries:
        normalized = " ".join(query.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped
