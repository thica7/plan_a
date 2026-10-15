import pytest
from test_execution_limits import _service, _text_call

from packages.agents.prompt_contract import prompt_trace_metadata


def test_comparator_context_reference_contract_has_new_version():
    assert (
        prompt_trace_metadata("comparator", "comparison_matrix", "system", "user", None)[
            "prompt_version"
        ]
        == "3"
    )


@pytest.mark.asyncio
async def test_native_call_trace_has_prompt_identity_and_content_fingerprints():
    service, record = await _service()

    async def complete(**kwargs):
        return "Fixed offline output"

    service._llm.complete_text = complete
    await _text_call(service, record)
    metadata = record.detail.trace_spans[-1].metadata
    assert metadata.get("prompt_id") == "writer.first_draft"
    assert metadata.get("prompt_version") == "2"
    assert len(metadata.get("prompt_template_hash", "")) == 64
    assert len(metadata.get("prompt_input_hash", "")) == 64
    await service._trace_llm_text(
        record,
        agent="writer",
        subagent=None,
        name="report_writer",
        system="test",
        user="Different fixed evidence",
    )
    changed = record.detail.trace_spans[-1].metadata
    assert changed["prompt_template_hash"] == metadata["prompt_template_hash"]
    assert changed["prompt_input_hash"] != metadata["prompt_input_hash"]
