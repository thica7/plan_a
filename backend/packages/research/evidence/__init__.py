"""Public evidence helpers, loaded lazily so DTOs can import immutable records."""

from importlib import import_module

_EXPORT_MODULES = {
    "admission": (
        "admit_evidence_items",
        "raw_source_from_capture",
        "raw_sources_from_research_result",
        "source_quality_problem",
    ),
    "citations": ("citation_refs_from_evidence_items", "snippet_from_evidence_items"),
    "items": ("evidence_items_from_extractions",),
    "normalization": (
        "normalized_fields_as_dicts",
        "normalized_fields_from_evidence_items",
        "normalized_fields_from_source",
        "normalized_summary_from_source",
    ),
    "store": (
        "accepted_evidence_by_page",
        "accepted_evidence_items",
        "dedupe_by_id",
        "rejected_evidence_items",
    ),
    "text": (
        "deterministic_claim_text_from_source",
        "publishable_text_noise_problem",
        "source_business_snippet",
    ),
}

__all__ = [
    "accepted_evidence_by_page",
    "accepted_evidence_items",
    "admit_evidence_items",
    "citation_refs_from_evidence_items",
    "dedupe_by_id",
    "deterministic_claim_text_from_source",
    "evidence_items_from_extractions",
    "normalized_fields_as_dicts",
    "normalized_fields_from_evidence_items",
    "normalized_fields_from_source",
    "normalized_summary_from_source",
    "publishable_text_noise_problem",
    "rejected_evidence_items",
    "raw_source_from_capture",
    "raw_sources_from_research_result",
    "snippet_from_evidence_items",
    "source_business_snippet",
    "source_quality_problem",
]


def __getattr__(name: str):
    for module, names in _EXPORT_MODULES.items():
        if name in names:
            value = getattr(import_module(f"{__name__}.{module}"), name)
            globals()[name] = value
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
