import pytest

from packages.schema.messages import validate_agent_message_payload
from packages.schema.models import RedoScope


def test_redo_request_payload_accepts_requested_issue_ids() -> None:
    validate_agent_message_payload(
        "RedoRequestPayload",
        {
            "redo_scope": RedoScope(
                kind="writer_only",
                rationale="Repair selected release gate issue.",
            ).model_dump(mode="json"),
            "issues": [],
            "issue_ids": ["qc-release-gate-1"],
            "requested_issue_ids": ["release-gate-1"],
        },
    )


def test_redo_request_payload_still_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="RedoRequestPayload.unexpected"):
        validate_agent_message_payload(
            "RedoRequestPayload",
            {
                "redo_scope": RedoScope(
                    kind="writer_only",
                    rationale="Repair selected release gate issue.",
                ).model_dump(mode="json"),
                "unexpected": True,
            },
        )
