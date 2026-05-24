from typing import Literal, TypedDict


class GraphState(TypedDict, total=False):
    run_id: str
    dimensions: list[str]
    current_node: str
    redo_kind: Literal["writer_only", "comparator", "analyst", "collector", "full"] | None
    collect_qa_attempts: int
    analyst_qa_attempts: int
