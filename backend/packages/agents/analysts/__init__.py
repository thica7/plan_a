ROLE = "analyst"
INPUT_SCHEMA = "AnalysisTaskPayload"
OUTPUT_SCHEMA = "CompetitorKnowledge"

from packages.agents.analysts.runner import dispatch, join, run_branch

__all__ = ["INPUT_SCHEMA", "OUTPUT_SCHEMA", "ROLE", "dispatch", "join", "run_branch"]
