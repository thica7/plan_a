from packages.orchestrator.scoping import assign_redo_scope
from packages.orchestrator.state import GraphState

__all__ = ["GraphState", "RunService", "assign_redo_scope"]


def __getattr__(name: str):
    if name == "RunService":
        from packages.orchestrator.service import RunService

        return RunService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
