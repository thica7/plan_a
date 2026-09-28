from __future__ import annotations

from packages.research.extraction.feature import extract_feature_slots, extract_generic_capabilities
from packages.research.extraction.persona import extract_persona_schema
from packages.research.extraction.pricing import extract_generic_pricing, extract_pricing_model
from packages.research.models import CapturedPage, ExtractionResult, ResearchBrief


def extract_page(brief: ResearchBrief, page: CapturedPage) -> ExtractionResult:
    key = brief.dimension.casefold()
    if "pricing" in key:
        if brief.product_name or brief.product_category:
            return extract_generic_pricing(brief, page)
        return extract_pricing_model(brief, page)
    if "persona" in key or "user" in key or "buyer" in key:
        return extract_persona_schema(brief, page)
    if brief.product_name or brief.product_category:
        return extract_generic_capabilities(brief, page)
    return extract_feature_slots(brief, page)
