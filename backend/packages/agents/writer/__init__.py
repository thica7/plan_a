ROLE = "writer"
OUTPUT_SCHEMA = "MarkdownReport"

from packages.agents.writer.runner import run

__all__ = ["OUTPUT_SCHEMA", "ROLE", "run"]
