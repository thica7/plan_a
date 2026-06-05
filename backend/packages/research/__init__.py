from packages.research.models import (
    CandidateOrigin,
    CapturedPage,
    EvidenceItem,
    EvidenceQuote,
    ExtractionResult,
    QualityGap,
    RepairTask,
    ResearchBrief,
    ResearchResult,
    SourceCandidate,
)


def __getattr__(name: str):
    if name == "run_research_pipeline":
        from packages.research.pipeline import run_research_pipeline

        return run_research_pipeline
    raise AttributeError(name)

__all__ = [
    "CandidateOrigin",
    "CapturedPage",
    "EvidenceItem",
    "EvidenceQuote",
    "ExtractionResult",
    "QualityGap",
    "RepairTask",
    "ResearchBrief",
    "ResearchResult",
    "SourceCandidate",
    "run_research_pipeline",
]
