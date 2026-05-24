ROLE = "reflector"
OUTPUT_SCHEMA = "ReflectionRecord"

from packages.agents.reflector.runner import run

__all__ = ["OUTPUT_SCHEMA", "ROLE", "run"]
