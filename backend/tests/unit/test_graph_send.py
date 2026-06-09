from types import SimpleNamespace

import pytest

from packages.orchestrator.graph import build_real_analysis_graph


@pytest.mark.asyncio
async def test_real_graph_uses_send_fanout_for_collector_and_analyst() -> None:
    calls: list[tuple[str, str | None, str | None]] = []

    detail = SimpleNamespace(
        plan=SimpleNamespace(
            dimensions=["pricing", "feature"],
            competitors=["A", "B"],
        ),
        status="running",
    )
    record = SimpleNamespace(detail=detail)

    class Service:
        _runs = {"run-1": record}

        def _analyst_branch_id(self, dimension: str, competitor: str) -> str:
            return f"{dimension}::{competitor}"

        async def _real_planner_step(self, _record) -> None:
            calls.append(("planner", None, None))

        async def _real_planner_hitl_step(self, _record) -> None:
            calls.append(("planner_hitl", None, None))

        async def _real_collector_dispatch_step(self, _record, dimensions, competitors) -> None:
            calls.append(("collector_dispatch", ",".join(dimensions), ",".join(competitors)))

        async def _real_collector_branch_step(
            self, _record, dimension: str, competitor: str
        ) -> None:
            calls.append(("collector", dimension, competitor))

        async def _real_collect_join_step(self, _record, dimensions) -> None:
            calls.append(("collect_join", ",".join(dimensions), None))

        async def _run_survey_interview_enrichment(
            self, _record, dimensions, competitors
        ) -> None:
            calls.append(("survey_interview", ",".join(dimensions), ",".join(competitors)))

        async def _real_phase_qa_step(self, _record, phase: str) -> None:
            calls.append((f"{phase}_qa", None, None))

        def _route_phase_qa(self, _state, _phase: str) -> str:
            return "pass"

        def _blocking_phase_issues(self, _detail, _phase: str) -> list:
            return []

        def _issue_dimensions(self, _detail, _issues) -> set[str]:
            return set()

        def _issue_target_competitors(self, _detail, _issues) -> set[str]:
            return set()

        async def _real_analyst_dispatch_step(self, _record, dimensions, competitors) -> None:
            calls.append(("analyst_dispatch", ",".join(dimensions), ",".join(competitors)))

        async def _real_analyst_branch_step(self, _record, dimension: str, competitor: str) -> None:
            calls.append(("analyst", dimension, competitor))

        async def _real_analyst_join_step(self, _record, dimensions, competitors) -> None:
            calls.append(("analyst_join", ",".join(dimensions), ",".join(competitors)))

        async def _real_comparator_step(self, _record) -> None:
            calls.append(("comparator", None, None))

        async def _real_reflector_step(self, _record) -> None:
            calls.append(("reflector", None, None))

        async def _real_writer_step(self, _record) -> None:
            calls.append(("writer", None, None))

        async def _real_qa_step(self, _record) -> None:
            calls.append(("qa", None, None))

        async def _real_qa_hitl_step(self, _record) -> None:
            calls.append(("qa_hitl", None, None))
            return {"redo_kind": "end"}

    graph = build_real_analysis_graph(Service())

    await graph.ainvoke(
        {
            "run_id": "run-1",
            "dimensions": ["pricing", "feature"],
            "target_competitors": ["A", "B"],
            "collect_qa_attempts": 0,
            "analyst_qa_attempts": 0,
        }
    )

    collector_calls = [call for call in calls if call[0] == "collector"]
    analyst_calls = [call for call in calls if call[0] == "analyst"]

    assert sorted((dimension, competitor) for _, dimension, competitor in collector_calls) == [
        ("feature", "A"),
        ("feature", "B"),
        ("pricing", "A"),
        ("pricing", "B"),
    ]
    assert sorted((dimension, competitor) for _, dimension, competitor in analyst_calls) == [
        ("feature", "A"),
        ("feature", "B"),
        ("pricing", "A"),
        ("pricing", "B"),
    ]
    assert ("collect_join", "pricing,feature", None) in calls
    assert ("survey_interview", "pricing,feature", "A,B") in calls
    assert ("analyst_join", "pricing,feature", "A,B") in calls


@pytest.mark.asyncio
async def test_final_qa_redo_limit_ends_graph_after_allowed_retry() -> None:
    calls: list[str] = []
    events: list[tuple[str, dict]] = []

    detail = SimpleNamespace(
        id="run-final-qa-limit",
        plan=SimpleNamespace(dimensions=["pricing"], competitors=["A"]),
        status="running",
        max_iterations=1,
    )
    record = SimpleNamespace(detail=detail)

    class Service:
        _runs = {"run-final-qa-limit": record}

        def _analyst_branch_id(self, dimension: str, competitor: str) -> str:
            return f"{dimension}::{competitor}"

        async def _real_planner_step(self, _record) -> None:
            calls.append("planner")

        async def _real_planner_hitl_step(self, _record) -> None:
            calls.append("planner_hitl")

        async def _real_collector_dispatch_step(self, _record, _dimensions, _competitors) -> None:
            calls.append("collector_dispatch")

        async def _real_collector_branch_step(self, _record, _dimension, _competitor) -> None:
            calls.append("collector")

        async def _real_collect_join_step(self, _record, _dimensions) -> None:
            calls.append("collect_join")

        async def _run_survey_interview_enrichment(
            self, _record, _dimensions, _competitors
        ) -> None:
            calls.append("survey_interview")

        async def _real_phase_qa_step(self, _record, phase: str) -> None:
            calls.append(f"{phase}_qa")

        def _route_phase_qa(self, _state, _phase: str) -> str:
            return "pass"

        def _blocking_phase_issues(self, _detail, _phase: str) -> list:
            return []

        def _issue_dimensions(self, _detail, _issues) -> set[str]:
            return set()

        def _issue_target_competitors(self, _detail, _issues) -> set[str]:
            return set()

        async def _real_analyst_dispatch_step(self, _record, _dimensions, _competitors) -> None:
            calls.append("analyst_dispatch")

        async def _real_analyst_branch_step(self, _record, _dimension, _competitor) -> None:
            calls.append("analyst")

        async def _real_analyst_join_step(self, _record, _dimensions, _competitors) -> None:
            calls.append("analyst_join")

        async def _real_comparator_step(self, _record) -> None:
            calls.append("comparator")

        async def _real_reflector_step(self, _record) -> None:
            calls.append("reflector")

        async def _real_writer_step(self, _record) -> None:
            calls.append("writer")

        async def _real_qa_step(self, _record) -> None:
            calls.append("qa")

        async def _real_qa_hitl_step(self, _record) -> dict[str, object]:
            calls.append("qa_hitl")
            return {"redo_kind": "writer_only"}

        async def emit(
            self,
            _run_id: str,
            event_type: str,
            _agent: str | None,
            _subagent: str | None,
            _message: str,
            payload: dict | None = None,
        ) -> None:
            events.append((event_type, payload or {}))

    graph = build_real_analysis_graph(Service())

    await graph.ainvoke(
        {
            "run_id": "run-final-qa-limit",
            "dimensions": ["pricing"],
            "target_competitors": ["A"],
            "collect_qa_attempts": 0,
            "analyst_qa_attempts": 0,
            "final_qa_attempts": 0,
        }
    )

    assert calls.count("writer") == 2
    assert calls.count("qa_hitl") == 2
    assert events == [
        (
            "qa.blocked",
            {
                "max_iterations": 1,
                "final_qa_attempts": 1,
                "blocked_redo_kind": "writer_only",
                "reason": "final_qa_attempt_limit",
            },
        )
    ]
