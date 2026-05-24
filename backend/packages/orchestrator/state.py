import operator
from typing import Annotated, Literal, TypedDict


class GraphState(TypedDict, total=False):
    run_id: str
    dimensions: list[str]
    target_competitors: list[str]
    branch_dimensions: Annotated[list[str], operator.add]
    branch_competitors: Annotated[list[str], operator.add]
    completed_collector_branches: Annotated[list[str], operator.add]
    completed_analyst_branches: Annotated[list[str], operator.add]
    current_node: str
    redo_kind: Literal["writer_only", "comparator", "analyst", "collector", "full"] | None
    collect_qa_attempts: int
    analyst_qa_attempts: int
