from __future__ import annotations

import asyncio
from typing import Any

from langgraph.graph import END, START, StateGraph

from packages.orchestrator.state import GraphState


def build_real_analysis_graph(service: Any, checkpointer: Any | None = None):
    graph = StateGraph(GraphState)
    _add_real_nodes(graph, service)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "collector")
    graph.add_edge("collector", "collect_qa")
    graph.add_conditional_edges(
        "collect_qa",
        lambda state: service._route_phase_qa(state, "collect"),
        {"retry": "collector", "pass": "analyst", "fail": END},
    )
    graph.add_edge("analyst", "analyst_qa")
    graph.add_conditional_edges(
        "analyst_qa",
        lambda state: service._route_phase_qa(state, "analyst"),
        {"retry": "analyst", "pass": "comparator", "fail": END},
    )
    graph.add_edge("comparator", "reflector")
    graph.add_edge("reflector", "writer")
    graph.add_edge("writer", "qa")
    graph.add_edge("qa", END)

    return graph.compile(checkpointer=checkpointer, name="competiscope_real_analysis")


def build_scoped_redo_graph(service: Any, checkpointer: Any | None = None):
    graph = StateGraph(GraphState)
    _add_real_nodes(graph, service)

    async def redo_router(state: GraphState) -> GraphState:
        return {"current_node": "redo_router", "redo_kind": state.get("redo_kind") or "full"}

    def route_redo(state: GraphState) -> str:
        kind = state.get("redo_kind")
        if kind == "writer_only":
            return "writer"
        if kind == "comparator":
            return "comparator"
        if kind == "analyst":
            return "analyst"
        if kind == "collector":
            return "collector"
        return "planner"

    graph.add_node("redo_router", redo_router)
    graph.add_edge(START, "redo_router")
    graph.add_conditional_edges(
        "redo_router",
        route_redo,
        {
            "writer": "writer",
            "comparator": "comparator",
            "analyst": "analyst",
            "collector": "collector",
            "planner": "planner",
        },
    )
    graph.add_edge("planner", "collector")
    graph.add_edge("collector", "collect_qa")
    graph.add_conditional_edges(
        "collect_qa",
        lambda state: service._route_phase_qa(state, "collect"),
        {"retry": "collector", "pass": "analyst", "fail": END},
    )
    graph.add_edge("analyst", "analyst_qa")
    graph.add_conditional_edges(
        "analyst_qa",
        lambda state: service._route_phase_qa(state, "analyst"),
        {"retry": "analyst", "pass": "comparator", "fail": END},
    )
    graph.add_edge("comparator", "reflector")
    graph.add_edge("reflector", "writer")
    graph.add_edge("writer", "qa")
    graph.add_edge("qa", END)

    return graph.compile(checkpointer=checkpointer, name="competiscope_scoped_redo")


def _add_real_nodes(graph: StateGraph, service: Any) -> None:
    async def planner(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_planner_step(record)
        return {"current_node": "planner", "dimensions": list(record.detail.plan.dimensions)}

    async def collector(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = state.get("dimensions") or record.detail.plan.dimensions
        await asyncio.gather(
            *(service._real_collector_step(record, dimension) for dimension in dimensions)
        )
        await service._real_collect_join_step(record, list(dimensions))
        return {"current_node": "collector"}

    async def analyst(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = state.get("dimensions") or record.detail.plan.dimensions
        await asyncio.gather(
            *(service._real_analyst_step(record, dimension) for dimension in dimensions)
        )
        return {"current_node": "analyst"}

    async def collect_qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_phase_qa_step(record, "collect")
        attempts = state.get("collect_qa_attempts", 0)
        if service._phase_has_blockers(record, "collect"):
            attempts += 1
        return {"current_node": "collect_qa", "collect_qa_attempts": attempts}

    async def analyst_qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_phase_qa_step(record, "analyst")
        attempts = state.get("analyst_qa_attempts", 0)
        if service._phase_has_blockers(record, "analyst"):
            attempts += 1
        return {"current_node": "analyst_qa", "analyst_qa_attempts": attempts}

    async def comparator(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_comparator_step(record)
        return {"current_node": "comparator"}

    async def reflector(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_reflector_step(record)
        return {"current_node": "reflector"}

    async def writer(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_writer_step(record)
        return {"current_node": "writer"}

    async def qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_qa_step(record)
        return {"current_node": "qa"}

    graph.add_node("planner", planner)
    graph.add_node("collector", collector)
    graph.add_node("collect_qa", collect_qa)
    graph.add_node("analyst", analyst)
    graph.add_node("analyst_qa", analyst_qa)
    graph.add_node("comparator", comparator)
    graph.add_node("reflector", reflector)
    graph.add_node("writer", writer)
    graph.add_node("qa", qa)
