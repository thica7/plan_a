from packages.observability import TraceStore
from packages.schema.models import AgentMessage, ToolCallMessage, TraceSpan


def test_trace_store_round_trips_spans_and_messages() -> None:
    store = TraceStore.in_memory()
    span = TraceSpan(
        id="span-1",
        kind="llm",
        agent="planner",
        subagent=None,
        name="planner_scope",
        status="ok",
        duration_ms=12,
        input_chars=10,
        output_chars=20,
        input_tokens_estimate=3,
        output_tokens_estimate=5,
        cost_estimate_usd=0.000004,
    )
    agent_message = AgentMessage(
        id="msg-1",
        run_id="run-1",
        from_agent="planner",
        to_agent="collector_dispatch",
        message_type="analysis_plan_ready",
        payload_schema="AnalysisPlan",
        trace_span_ids=["span-1"],
    )
    tool_message = ToolCallMessage(
        id="tool-1",
        run_id="run-1",
        agent="collector",
        subagent="pricing::A",
        tool_name="web_search",
        status="ok",
        trace_span_id="span-2",
    )

    store.append_span("run-1", span)
    store.append_agent_message(agent_message)
    store.append_tool_call_message(tool_message)

    assert store.list_spans("run-1")[0].name == "planner_scope"
    assert store.list_agent_messages("run-1")[0].message_type == "analysis_plan_ready"
    assert store.list_tool_call_messages("run-1")[0].tool_name == "web_search"
    assert store.stats() == {"trace_spans": 1, "agent_messages": 1, "tool_call_messages": 1}
