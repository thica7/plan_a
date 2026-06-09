from packages.agents.collectors.runner import dispatch, join, run_branch

ROLE = "collector"
INPUT_SCHEMA = "CollectTaskPayload"
OUTPUT_SCHEMA = "RawSource[]"

__all__ = ["INPUT_SCHEMA", "OUTPUT_SCHEMA", "ROLE", "dispatch", "join", "run_branch"]
