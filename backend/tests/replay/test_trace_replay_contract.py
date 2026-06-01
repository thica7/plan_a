from packages.observability import TraceStore
from packages.schema.models import AgentMessage


def test_replay_store_preserves_agent_message_consumption_state() -> None:
    store = TraceStore.in_memory()
    message = AgentMessage(
        id="msg-1",
        run_id="run-1",
        from_agent="qa",
        to_agent="collector",
        message_type="redo_request",
        payload_schema="RedoRequestPayload",
        payload={"target_subagent": "pricing"},
        status="consumed",
        consumed_by="redo_router",
    )

    store.append_agent_message(message)

    [loaded] = store.list_agent_messages("run-1")
    assert loaded.status == "consumed"
    assert loaded.consumed_by == "redo_router"
