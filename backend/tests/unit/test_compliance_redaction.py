from packages.compliance import CompliancePolicy, redact_text


FAKE_OPENROUTER_KEY = "sk-or-v1-" + "test" * 12


def test_redacts_common_provider_key_families() -> None:
    text = "\n".join(
        [
            f"BACKUP_LLM_API_KEY={FAKE_OPENROUTER_KEY}",
            "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890",
            "ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456",
            "PPLX_API_KEY=pplx-abcdefghijklmnopqrstuvwxyz123456",
            "GOOGLE_API_KEY=AIzaabcdefghijklmnopqrstuvwxyz123456",
            "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP",
            "HF_TOKEN=hf_abcdefghijklmnopqrstuvwxyz123456",
        ]
    )

    result = redact_text(text)

    assert result.counts["api_key"] == 7
    assert "sk-or-v1" not in result.text
    assert "sk-proj" not in result.text
    assert "AKIA" not in result.text
    assert result.text.count("[redacted:api_key]") == 7


def test_redaction_policy_can_disable_key_redaction_only() -> None:
    result = redact_text(
        f"key={FAKE_OPENROUTER_KEY} user=ops@example.com",
        policy=CompliancePolicy(redact_api_keys=False),
    )

    assert "sk-or-v1" in result.text
    assert "[redacted:email]" in result.text
    assert "api_key" not in result.counts
