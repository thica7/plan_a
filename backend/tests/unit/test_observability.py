from packages.compliance import CompliancePolicy, redact_text
from packages.observability import build_run_event, sanitize_for_trace, trace_id_for_run


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
    assert event.trace_id == trace_id_for_run("run-1")
    assert event.payload == {"api_key": "[redacted]", "query": "pricing"}


def test_trace_payload_sanitizes_sensitive_text_values() -> None:
    sanitized = sanitize_for_trace(
        {
            "note": (
                "Contact alice@example.com with "
                "OPENROUTER_TEST_KEY_REDACTED."
            )
        }
    )

    assert sanitized["note"] == (
        "Contact [redacted:email] with [redacted:api_key]."
    )


def test_compliance_redactor_reports_counts_by_kind() -> None:
    result = redact_text(
        "Bearer abcdef1234567890 belongs to bob@example.com and +1 415 555 2671."
    )

    assert result.total_count == 3
    assert result.counts == {"bearer_token": 1, "email": 1, "phone": 1}
    assert "[redacted:bearer_token]" in result.text


def test_compliance_redactor_obeys_policy() -> None:
    result = redact_text(
        "Contact alice@example.com with OPENROUTER_TEST_KEY_REDACTED.",
        policy=CompliancePolicy(redact_emails=False, redact_api_keys=True),
    )

    assert "alice@example.com" in result.text
    assert "[redacted:api_key]" in result.text
    assert result.counts == {"api_key": 1}
