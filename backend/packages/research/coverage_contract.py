from __future__ import annotations

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
    if "pricing" not in brief.dimension.casefold():
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
