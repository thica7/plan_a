from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from packages.agents import (
    analysts as analyst_agent,
)
from packages.agents import (
    collectors as collector_agent,
)
from packages.agents import (
    comparator as comparator_agent,
)
from packages.agents import (
    planner as planner_agent,
)
from packages.agents import (
    qa as qa_agent,
)
from packages.agents import (
    reflector as reflector_agent,
)
from packages.agents import (
    survey as survey_agent,
)
from packages.agents import (
    writer as writer_agent,
)
from packages.orchestrator.state import GraphState


def build_real_analysis_graph(service: Any, checkpointer: Any | None = None):
    graph = StateGraph(GraphState)
    _add_real_nodes(graph, service)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "planner_hitl")
    graph.add_edge("planner_hitl", "collector_dispatch")
    graph.add_conditional_edges("collector_dispatch", _send_collectors, ["collector"])
    graph.add_edge("collector", "collect_join")
    graph.add_edge("collect_join", "survey_interview")
    graph.add_edge("survey_interview", "collect_qa")
    graph.add_conditional_edges(
        "collect_qa",
        lambda state: service._route_phase_qa(state, "collect"),
        {"retry": "collector_dispatch", "pass": "analyst_dispatch", "fail": END},
    )
    graph.add_conditional_edges("analyst_dispatch", _send_analysts, ["analyst"])
    graph.add_edge("analyst", "analyst_join")
    graph.add_edge("analyst_join", "analyst_qa")
    graph.add_conditional_edges(
        "analyst_qa",
        lambda state: service._route_phase_qa(state, "analyst"),
        {"retry": "analyst_dispatch", "pass": "comparator", "fail": END},
    )
    graph.add_edge("comparator", "reflector")
    graph.add_edge("reflector", "writer")
    graph.add_edge("writer", "qa")
    graph.add_edge("qa", "qa_hitl")
    graph.add_conditional_edges(
        "qa_hitl",
        _route_final_qa,
        {
            "end": END,
            "writer_only": "writer",
            "comparator": "comparator",
            "analyst": "analyst_dispatch",
            "collector": "collector_dispatch",
            "full": "planner",
        },
    )

    return graph.compile(checkpointer=checkpointer, name="competiscope_real_analysis")


def build_scoped_redo_graph(service: Any, checkpointer: Any | None = None):
    graph = StateGraph(GraphState)
    _add_real_nodes(graph, service)

    async def redo_router(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        for target in ("collector", "analyst", "comparator", "writer_only", "orchestrator"):
            service._consume_queued_agent_messages(
                record,
                to_agent=target,
                consumer_agent="redo_router",
                message_types={"redo_request"},
            )
        return {"current_node": "redo_router", "redo_kind": state.get("redo_kind") or "full"}

    def route_redo(state: GraphState) -> str:
        kind = state.get("redo_kind")
        if kind == "writer_only":
            return "writer"
        if kind == "comparator":
            return "comparator"
        if kind == "analyst":
            return "analyst_dispatch"
        if kind == "collector":
            return "collector_dispatch"
        return "planner"

    graph.add_node("redo_router", redo_router)
    graph.add_edge(START, "redo_router")
    graph.add_conditional_edges(
        "redo_router",
        route_redo,
        {
            "writer": "writer",
            "comparator": "comparator",
            "analyst_dispatch": "analyst_dispatch",
            "collector_dispatch": "collector_dispatch",
            "planner": "planner",
        },
    )
    graph.add_edge("planner", "planner_hitl")
    graph.add_edge("planner_hitl", "collector_dispatch")
    graph.add_conditional_edges("collector_dispatch", _send_collectors, ["collector"])
    graph.add_edge("collector", "collect_join")
    graph.add_edge("collect_join", "survey_interview")
    graph.add_edge("survey_interview", "collect_qa")
    graph.add_conditional_edges(
        "collect_qa",
        lambda state: service._route_phase_qa(state, "collect"),
        {"retry": "collector_dispatch", "pass": "analyst_dispatch", "fail": END},
    )
    graph.add_conditional_edges("analyst_dispatch", _send_analysts, ["analyst"])
    graph.add_edge("analyst", "analyst_join")
    graph.add_edge("analyst_join", "analyst_qa")
    graph.add_conditional_edges(
        "analyst_qa",
        lambda state: service._route_phase_qa(state, "analyst"),
        {"retry": "analyst_dispatch", "pass": "comparator", "fail": END},
    )
    graph.add_edge("comparator", "reflector")
    graph.add_edge("reflector", "writer")
    graph.add_edge("writer", "qa")
    graph.add_edge("qa", "qa_hitl")
    graph.add_conditional_edges(
        "qa_hitl",
        _route_final_qa,
        {
            "end": END,
            "writer_only": "writer",
            "comparator": "comparator",
            "analyst": "analyst_dispatch",
            "collector": "collector_dispatch",
            "full": "planner",
        },
    )

    return graph.compile(checkpointer=checkpointer, name="competiscope_scoped_redo")


def build_demo_analysis_graph(service: Any, checkpointer: Any | None = None):
    graph = StateGraph(GraphState)
    _add_demo_nodes(graph, service)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "planner_hitl")
    graph.add_edge("planner_hitl", "collector_dispatch")
    graph.add_conditional_edges("collector_dispatch", _send_collectors, ["collector"])
    graph.add_edge("collector", "collect_join")
    graph.add_edge("collect_join", "survey_interview")
    graph.add_edge("survey_interview", "collect_qa")
    graph.add_conditional_edges(
        "collect_qa",
        lambda state: service._route_phase_qa(state, "collect"),
        {"retry": "collector_dispatch", "pass": "analyst_dispatch", "fail": END},
    )
    graph.add_conditional_edges("analyst_dispatch", _send_analysts, ["analyst"])
    graph.add_edge("analyst", "analyst_join")
    graph.add_edge("analyst_join", "analyst_qa")
    graph.add_conditional_edges(
        "analyst_qa",
        lambda state: service._route_phase_qa(state, "analyst"),
        {"retry": "analyst_dispatch", "pass": "comparator", "fail": END},
    )
    graph.add_edge("comparator", "reflector")
    graph.add_edge("reflector", "writer")
    graph.add_edge("writer", "qa")
    graph.add_edge("qa", "qa_hitl")
    graph.add_conditional_edges(
        "qa_hitl",
        _route_final_qa,
        {
            "end": END,
            "writer_only": "writer",
            "comparator": "comparator",
            "analyst": "analyst_dispatch",
            "collector": "collector_dispatch",
            "full": "planner",
        },
    )

    return graph.compile(checkpointer=checkpointer, name="competiscope_demo_analysis")


def _add_real_nodes(graph: StateGraph, service: Any) -> None:
    async def planner(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await planner_agent.run(service, record)
        return {"current_node": "planner", "dimensions": list(record.detail.plan.dimensions)}

    async def planner_hitl(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_planner_hitl_step(record)
        return {"current_node": "planner_hitl", "dimensions": list(record.detail.plan.dimensions)}

    async def collector_dispatch(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = state.get("dimensions") or record.detail.plan.dimensions
        competitors = state.get("target_competitors") or record.detail.plan.competitors
        await collector_agent.dispatch(service, record, list(dimensions), list(competitors))
        return {
            "current_node": "collector_dispatch",
            "dimensions": list(dimensions),
            "target_competitors": list(competitors),
        }

    async def collector(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        branch_dimensions = state.get("branch_dimensions") or []
        branch_competitors = state.get("branch_competitors") or []
        if not branch_dimensions or not branch_competitors:
            raise RuntimeError(
                "collector node must be entered through Send(competitor x dimension)."
            )
        dimension = branch_dimensions[-1]
        competitor = branch_competitors[-1]
        await collector_agent.run_branch(service, record, dimension, competitor)
        return {"completed_collector_branches": [service._analyst_branch_id(dimension, competitor)]}

    async def collect_join(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = _ordered_unique(
            state.get("dimensions")
            or state.get("branch_dimensions")
            or record.detail.plan.dimensions
        )
        await collector_agent.join(service, record, list(dimensions))
        return {"current_node": "collect_join", "dimensions": list(dimensions)}

    async def survey_interview(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = _ordered_unique(state.get("dimensions") or record.detail.plan.dimensions)
        competitors = _ordered_unique(
            state.get("target_competitors") or record.detail.plan.competitors
        )
        await survey_agent.run_enrichment(service, record, list(dimensions), list(competitors))
        return {
            "current_node": "survey_interview",
            "dimensions": list(dimensions),
            "target_competitors": list(competitors),
        }

    async def analyst_dispatch(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = state.get("dimensions") or record.detail.plan.dimensions
        competitors = state.get("target_competitors") or record.detail.plan.competitors
        await analyst_agent.dispatch(service, record, list(dimensions), list(competitors))
        return {
            "current_node": "analyst_dispatch",
            "dimensions": list(dimensions),
            "target_competitors": list(competitors),
        }

    async def analyst(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        branch_dimensions = state.get("branch_dimensions") or []
        branch_competitors = state.get("branch_competitors") or []
        if not branch_dimensions or not branch_competitors:
            raise RuntimeError("analyst node must be entered through Send(competitor x slice).")
        dimension = branch_dimensions[-1]
        competitor = branch_competitors[-1]
        await analyst_agent.run_branch(service, record, dimension, competitor)
        return {"completed_analyst_branches": [service._analyst_branch_id(dimension, competitor)]}

    async def analyst_join(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = _ordered_unique(
            state.get("dimensions")
            or state.get("branch_dimensions")
            or record.detail.plan.dimensions
        )
        competitors = _ordered_unique(
            state.get("target_competitors")
            or state.get("branch_competitors")
            or record.detail.plan.competitors
        )
        await analyst_agent.join(service, record, list(dimensions), list(competitors))
        return {
            "current_node": "analyst_join",
            "dimensions": list(dimensions),
            "target_competitors": list(competitors),
        }

    async def collect_qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await qa_agent.run_phase(service, record, "collect")
        attempts = state.get("collect_qa_attempts", 0)
        blockers = service._blocking_phase_issues(record.detail, "collect")
        if blockers:
            attempts += 1
        next_dimensions = (
            sorted(service._issue_dimensions(record.detail, blockers))
            if blockers
            else list(state.get("dimensions") or record.detail.plan.dimensions)
        )
        next_competitors = (
            sorted(service._issue_target_competitors(record.detail, blockers))
            if blockers
            else list(state.get("target_competitors") or [])
        )
        return {
            "current_node": "collect_qa",
            "collect_qa_attempts": attempts,
            "dimensions": next_dimensions,
            "target_competitors": next_competitors,
        }

    async def analyst_qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await qa_agent.run_phase(service, record, "analyst")
        attempts = state.get("analyst_qa_attempts", 0)
        blockers = service._blocking_phase_issues(record.detail, "analyst")
        if blockers:
            attempts += 1
        next_dimensions = (
            sorted(service._issue_dimensions(record.detail, blockers))
            if blockers
            else list(state.get("dimensions") or record.detail.plan.dimensions)
        )
        next_competitors = (
            sorted(service._issue_target_competitors(record.detail, blockers))
            if blockers
            else list(state.get("target_competitors") or [])
        )
        return {
            "current_node": "analyst_qa",
            "analyst_qa_attempts": attempts,
            "dimensions": next_dimensions,
            "target_competitors": next_competitors,
        }

    async def comparator(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await comparator_agent.run(service, record)
        return {"current_node": "comparator"}

    async def reflector(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await reflector_agent.run(service, record)
        return {"current_node": "reflector"}

    async def writer(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await writer_agent.run(service, record)
        return {"current_node": "writer"}

    async def qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await qa_agent.run_final(service, record)
        return {"current_node": "qa"}

    async def qa_hitl(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        route_state = await service._real_qa_hitl_step(record)
        return {"current_node": "qa_hitl", **route_state}

    graph.add_node("planner", planner)
    graph.add_node("planner_hitl", planner_hitl)
    graph.add_node("collector_dispatch", collector_dispatch)
    graph.add_node("collector", collector)
    graph.add_node("collect_join", collect_join)
    graph.add_node("survey_interview", survey_interview)
    graph.add_node("collect_qa", collect_qa)
    graph.add_node("analyst_dispatch", analyst_dispatch)
    graph.add_node("analyst", analyst)
    graph.add_node("analyst_join", analyst_join)
    graph.add_node("analyst_qa", analyst_qa)
    graph.add_node("comparator", comparator)
    graph.add_node("reflector", reflector)
    graph.add_node("writer", writer)
    graph.add_node("qa", qa)
    graph.add_node("qa_hitl", qa_hitl)


def _add_demo_nodes(graph: StateGraph, service: Any) -> None:
    async def planner(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._demo_planner_step(record)
        return {"current_node": "planner", "dimensions": list(record.detail.plan.dimensions)}

    async def planner_hitl(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._real_planner_hitl_step(record)
        return {"current_node": "planner_hitl", "dimensions": list(record.detail.plan.dimensions)}

    async def collector_dispatch(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = state.get("dimensions") or record.detail.plan.dimensions
        competitors = state.get("target_competitors") or record.detail.plan.competitors
        await collector_agent.dispatch(service, record, list(dimensions), list(competitors))
        return {
            "current_node": "collector_dispatch",
            "dimensions": list(dimensions),
            "target_competitors": list(competitors),
        }

    async def collector(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        branch_dimensions = state.get("branch_dimensions") or []
        branch_competitors = state.get("branch_competitors") or []
        if not branch_dimensions or not branch_competitors:
            raise RuntimeError(
                "collector node must be entered through Send(competitor x dimension)."
            )
        dimension = branch_dimensions[-1]
        competitor = branch_competitors[-1]
        await service._demo_collector_branch_step(record, dimension, competitor)
        return {"completed_collector_branches": [service._analyst_branch_id(dimension, competitor)]}

    async def collect_join(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = _ordered_unique(
            state.get("dimensions")
            or state.get("branch_dimensions")
            or record.detail.plan.dimensions
        )
        await service._demo_collect_join_step(record, list(dimensions))
        return {"current_node": "collect_join", "dimensions": list(dimensions)}

    async def survey_interview(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = _ordered_unique(state.get("dimensions") or record.detail.plan.dimensions)
        competitors = _ordered_unique(
            state.get("target_competitors") or record.detail.plan.competitors
        )
        await survey_agent.run_enrichment(service, record, list(dimensions), list(competitors))
        return {
            "current_node": "survey_interview",
            "dimensions": list(dimensions),
            "target_competitors": list(competitors),
        }

    async def collect_qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._demo_phase_qa_step(record, "collect")
        return {
            "current_node": "collect_qa",
            "collect_qa_attempts": state.get("collect_qa_attempts", 0),
            "dimensions": list(state.get("dimensions") or record.detail.plan.dimensions),
            "target_competitors": list(
                state.get("target_competitors") or record.detail.plan.competitors
            ),
        }

    async def analyst_dispatch(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = state.get("dimensions") or record.detail.plan.dimensions
        competitors = state.get("target_competitors") or record.detail.plan.competitors
        await analyst_agent.dispatch(service, record, list(dimensions), list(competitors))
        return {
            "current_node": "analyst_dispatch",
            "dimensions": list(dimensions),
            "target_competitors": list(competitors),
        }

    async def analyst(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        branch_dimensions = state.get("branch_dimensions") or []
        branch_competitors = state.get("branch_competitors") or []
        if not branch_dimensions or not branch_competitors:
            raise RuntimeError("analyst node must be entered through Send(competitor x slice).")
        dimension = branch_dimensions[-1]
        competitor = branch_competitors[-1]
        await service._demo_analyst_branch_step(record, dimension, competitor)
        return {"completed_analyst_branches": [service._analyst_branch_id(dimension, competitor)]}

    async def analyst_join(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        dimensions = _ordered_unique(
            state.get("dimensions")
            or state.get("branch_dimensions")
            or record.detail.plan.dimensions
        )
        competitors = _ordered_unique(
            state.get("target_competitors")
            or state.get("branch_competitors")
            or record.detail.plan.competitors
        )
        await analyst_agent.join(service, record, list(dimensions), list(competitors))
        return {
            "current_node": "analyst_join",
            "dimensions": list(dimensions),
            "target_competitors": list(competitors),
        }

    async def analyst_qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._demo_phase_qa_step(record, "analyst")
        return {
            "current_node": "analyst_qa",
            "analyst_qa_attempts": state.get("analyst_qa_attempts", 0),
            "dimensions": list(state.get("dimensions") or record.detail.plan.dimensions),
            "target_competitors": list(
                state.get("target_competitors") or record.detail.plan.competitors
            ),
        }

    async def comparator(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._demo_comparator_step(record)
        return {"current_node": "comparator"}

    async def reflector(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._demo_reflector_step(record)
        return {"current_node": "reflector"}

    async def writer(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._demo_writer_step(record)
        return {"current_node": "writer"}

    async def qa(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        await service._demo_qa_step(record)
        return {"current_node": "qa"}

    async def qa_hitl(state: GraphState) -> GraphState:
        record = service._runs[state["run_id"]]
        route_state = await service._real_qa_hitl_step(record)
        return {"current_node": "qa_hitl", **route_state}

    graph.add_node("planner", planner)
    graph.add_node("planner_hitl", planner_hitl)
    graph.add_node("collector_dispatch", collector_dispatch)
    graph.add_node("collector", collector)
    graph.add_node("collect_join", collect_join)
    graph.add_node("survey_interview", survey_interview)
    graph.add_node("collect_qa", collect_qa)
    graph.add_node("analyst_dispatch", analyst_dispatch)
    graph.add_node("analyst", analyst)
    graph.add_node("analyst_join", analyst_join)
    graph.add_node("analyst_qa", analyst_qa)
    graph.add_node("comparator", comparator)
    graph.add_node("reflector", reflector)
    graph.add_node("writer", writer)
    graph.add_node("qa", qa)
    graph.add_node("qa_hitl", qa_hitl)


def _send_collectors(state: GraphState) -> list[Send]:
    dimensions = state.get("dimensions") or []
    competitors = state.get("target_competitors") or []
    return [
        Send(
            "collector",
            {
                "run_id": state["run_id"],
                "branch_dimensions": [dimension],
                "branch_competitors": [competitor],
            },
        )
        for dimension in dimensions
        for competitor in competitors
    ]


def _send_analysts(state: GraphState) -> list[Send]:
    dimensions = state.get("dimensions") or []
    competitors = state.get("target_competitors") or []
    return [
        Send(
            "analyst",
            {
                "run_id": state["run_id"],
                "branch_dimensions": [dimension],
                "branch_competitors": [competitor],
            },
        )
        for dimension in dimensions
        for competitor in competitors
    ]


def _route_final_qa(state: GraphState) -> str:
    route = state.get("redo_kind") or "end"
    if route in {"writer_only", "comparator", "analyst", "collector", "full"}:
        return route
    return "end"


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
