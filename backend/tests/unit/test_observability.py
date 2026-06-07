import pytest

from packages.knowledge.repository import KnowledgeRepository
from packages.observability import RetrievalObservability, build_run_event, sanitize_for_trace


def test_trace_payload_sanitizes_nested_secrets() -> None:
    payload = {
        "ARK_API_KEY": "ark-secret",
        "headers": {"Authorization": "Bearer token"},
        "nested": [{"pplx_token": "pplx-secret", "visible": "safe"}],
    }

    sanitized = sanitize_for_trace(payload)

    assert sanitized["ARK_API_KEY"] == "[redacted]"
    assert sanitized["headers"]["Authorization"] == "[redacted]"
    assert sanitized["nested"][0]["pplx_token"] == "[redacted]"
    assert sanitized["nested"][0]["visible"] == "safe"


def test_build_run_event_applies_trace_sanitizer() -> None:
    event = build_run_event(
        event_id=1,
        run_id="run-1",
        event_type="node_started",
        agent="collector",
        subagent="pricing",
        message="started",
        payload={"api_key": "secret", "query": "pricing"},
    )

    assert event.swimlane == "pricing"
    assert event.payload == {"api_key": "[redacted]", "query": "pricing"}


def test_retrieval_observability_record_defaults_trace_fields() -> None:
    record = RetrievalObservability(
        query="pricing",
        preset_used="pricing",
        dense_hits=2,
        sparse_hits=3,
        reranked_hits=1,
        latency_ms=12.5,
        cache_hit=False,
        competitor="Acme",
        dimension="pricing",
        source_type="webpage_verified",
        retrieval_preset="pricing",
    )

    assert record.query == "pricing"
    assert record.retrieval_preset == "pricing"
    assert record.dense_hits == 2


@pytest.mark.asyncio
async def test_repository_persists_retrieval_observability_record(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        trace_id = await repo.record_retrieval_trace(
            RetrievalObservability(
                query="compare pricing",
                preset_used="comparison",
                dense_hits=4,
                sparse_hits=5,
                reranked_hits=3,
                latency_ms=25.0,
                cache_hit=True,
            )
        )
        async with repo._connection.execute(
            "SELECT * FROM retrieval_traces WHERE id = ?",
            (trace_id,),
        ) as cur:
            row = await cur.fetchone()

        assert row["query"] == "compare pricing"
        assert row["preset_used"] == "comparison"
        assert row["cache_hit"] == 1
    finally:
        await repo.close()
