ROLE = "comparator"
OUTPUT_SCHEMA = "ComparisonMatrix"

from packages.agents.comparator.runner import run

__all__ = ["OUTPUT_SCHEMA", "ROLE", "run"]
