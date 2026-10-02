from __future__ import annotations

from packages.identity import normalize_url
from packages.research.models import (
    CandidateIntent,
    CandidateLedgerEntry,
    CapturedPage,
    CoverageContractResult,
    EvidenceItem,
    ResearchBrief,
    SourceCandidate,
)
from packages.research.source_fitness import classify_source_fitness


def evaluate_coverage_contract(
    brief: ResearchBrief,
    *,
    candidates: list[SourceCandidate],
    pages: list[CapturedPage],
    evidence_items: list[EvidenceItem],
    ledger: list[CandidateLedgerEntry],
) -> CoverageContractResult:
    if (brief.product_name or brief.product_category) and "pricing" in brief.dimension.casefold():
        page_by_id = {page.id: page for page in pages}
        supported = any(
            item.status == "accepted" and item.field in {"price_rows", "price_points"}
            and item.competitor == brief.competitor and item.dimension == brief.dimension
            and (page := page_by_id.get(item.captured_page_id)) is not None
            and page.status == "ok"
            and brief.competitor.casefold() in f"{page.title} {page.text}".casefold()
            for item in evidence_items
        )
        return CoverageContractResult(
            dimension=brief.dimension, competitor=brief.competitor,
            required_intents=["current_plan_price_support"],
            satisfied_intents=["current_plan_price_support"] if supported else [],
            missing_intents=[] if supported else ["current_plan_price_support"],
            blocking_reasons=[] if supported else ["No source-backed product price was found."],
            passed=supported,
            metadata={"contract": "product_pricing_v1", "authority": "source_requires_review"},
        )
    if "pricing" not in brief.dimension.casefold():
        if brief.product_name or brief.product_category:
            return _product_fact_coverage(brief, pages, evidence_items)
        blocking_reasons = [
            gap
            for gap in _ledger_blocking_reasons(brief, ledger)
            if gap
        ]
        return CoverageContractResult(
            dimension=brief.dimension,
            competitor=brief.competitor,
            required_intents=[],
            satisfied_intents=[],
            missing_intents=[],
            blocking_reasons=blocking_reasons,
            passed=not blocking_reasons,
        )

    satisfied = _pricing_satisfied_intents(brief, candidates, pages, evidence_items)
    required: list[CandidateIntent] = [
        "official_pricing_page",
        "official_billing_or_usage_docs",
        "current_plan_price_support",
    ]
    missing: list[CandidateIntent] = []
    has_official_pricing_or_billing = bool(
        {"official_pricing_page", "official_billing_or_usage_docs"} & set(satisfied)
    )
    if not has_official_pricing_or_billing:
        missing.append("official_pricing_page")
    if "current_plan_price_support" not in satisfied:
        missing.append("current_plan_price_support")

    blocking_reasons = _ledger_blocking_reasons(brief, ledger)
    if missing:
        blocking_reasons.append(
            "Pricing coverage is missing required official pricing/billing or current plan support."
        )
    repair_hints = _repair_hints(brief, missing, blocking_reasons)
    return CoverageContractResult(
        dimension=brief.dimension,
        competitor=brief.competitor,
        required_intents=required,
        satisfied_intents=sorted(satisfied),
        missing_intents=missing,
        blocking_reasons=blocking_reasons,
        repair_hints=repair_hints,
        passed=not missing and not blocking_reasons,
        metadata={
            "contract": "pricing_v1",
            "accepted_ledger_count": sum(1 for entry in ledger if entry.status == "accepted"),
        },
    )


def _product_fact_coverage(
    brief: ResearchBrief,
    pages: list[CapturedPage],
    evidence_items: list[EvidenceItem],
) -> CoverageContractResult:
    page_by_id = {page.id: page for page in pages}
    accepted = [
        item for item in evidence_items
        if item.status == "accepted"
        and item.competitor == brief.competitor
        and item.dimension == brief.dimension
    ]
    source_groups: list[set[tuple[str, str]]] = []
    for item in accepted:
        page = page_by_id.get(item.captured_page_id)
        if (
            page is None or page.status != "ok"
            or item.source_candidate_id != page.candidate_id
        ):
            continue
        url = normalize_url(page.final_url)
        content_hash = page.content_hash.strip()
        identity = {("page", page.id)}
        if url:
            identity.add(("url", url))
        if content_hash:
            identity.add(("hash", content_hash))
        independent_groups = []
        for group in source_groups:
            if group.isdisjoint(identity):
                independent_groups.append(group)
            else:
                identity.update(group)
        source_groups = [*independent_groups, identity]

    usable_source_count = len(source_groups)
    missing_source_count = max(0, brief.target_source_count - usable_source_count)
    supported = missing_source_count == 0
    return CoverageContractResult(
        dimension=brief.dimension,
        competitor=brief.competitor,
        required_intents=["product_fact_support"],
        satisfied_intents=["product_fact_support"] if supported else [],
        missing_intents=[] if supported else ["product_fact_support"],
        blocking_reasons=[] if supported else [
            f"Product fact coverage for {brief.competitor} / {brief.dimension} has "
            f"{usable_source_count} independent usable sources; "
            f"{brief.target_source_count} required."
        ],
        repair_hints=[] if supported else [
            f"Find {missing_source_count} additional independent {brief.dimension} sources "
            f"with reviewable product facts for {brief.competitor} "
            f"({brief.product_category or brief.product_name})."
        ],
        passed=supported,
        metadata={
            "contract": "product_facts_v1",
            "required_source_count": brief.target_source_count,
            "accepted_evidence_count": len(accepted),
            "usable_source_count": usable_source_count,
            "missing_source_count": missing_source_count,
        },
    )


def _pricing_satisfied_intents(
    brief: ResearchBrief,
    candidates: list[SourceCandidate],
    pages: list[CapturedPage],
    evidence_items: list[EvidenceItem],
) -> set[CandidateIntent]:
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    accepted_page_ids = {
        item.captured_page_id
        for item in evidence_items
        if item.status == "accepted"
        and item.competitor == brief.competitor
        and item.dimension == brief.dimension
    }
    satisfied: set[CandidateIntent] = set()
    for page in pages:
        if page.status != "ok":
            continue
        candidate = candidate_by_id.get(page.candidate_id)
        if candidate is None:
            continue
        fitness = classify_source_fitness(brief, candidate, page)
        for intent in fitness.coverage_intents:
            if intent == "current_plan_price_support" and page.id not in accepted_page_ids:
                continue
            satisfied.add(intent)
    return satisfied


def _ledger_blocking_reasons(
    brief: ResearchBrief,
    ledger: list[CandidateLedgerEntry],
) -> list[str]:
    if "pricing" not in brief.dimension.casefold():
        return []
    blocked_fitness = {"changelog", "product_docs", "irrelevant_or_stale"}
    reasons: list[str] = []
    for entry in ledger:
        if entry.status != "accepted" or entry.source_fitness not in blocked_fitness:
            continue
        reasons.append(
            f"{entry.url} has source fitness {entry.source_fitness}, which cannot support current pricing."
        )
    return reasons


def _repair_hints(
    brief: ResearchBrief,
    missing: list[CandidateIntent],
    blocking_reasons: list[str],
) -> list[str]:
    hints: list[str] = []
    if "official_pricing_page" in missing:
        hints.append(
            f"Find the current official pricing, plans, or billing page for {brief.competitor}."
        )
    if "current_plan_price_support" in missing:
        hints.append(
            f"Find current plan/tier price evidence for {brief.competitor}, preferably on the official site."
        )
    if blocking_reasons:
        hints.append("Avoid changelog, plugin overview, and product docs as primary pricing sources.")
    return hints
