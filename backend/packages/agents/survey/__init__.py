from packages.agents.survey.runner import run_enrichment

INPUT_SCHEMA = "SurveyInterviewTask"
OUTPUT_SCHEMA = "SurveyEvidenceBundle[]"

__all__ = ["INPUT_SCHEMA", "OUTPUT_SCHEMA", "run_enrichment"]
