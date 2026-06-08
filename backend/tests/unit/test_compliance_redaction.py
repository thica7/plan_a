from packages.compliance import CompliancePolicy, redact_text

OPENROUTER_PREFIX = "sk" + "-or-v1-"
OPENAI_PROJECT_PREFIX = "sk" + "-proj-"
ANTHROPIC_PREFIX = "sk" + "-ant-api03-"
PERPLEXITY_PREFIX = "pplx" + "-"
GOOGLE_PREFIX = "AI" + "za"
AWS_PREFIX = "AK" + "IA"
HF_PREFIX = "hf" + "_"

FAKE_OPENROUTER_KEY = OPENROUTER_PREFIX + "test" * 12


def test_redacts_common_provider_key_families() -> None:
    text = "\n".join(
        [
            f"BACKUP_LLM_API_KEY={FAKE_OPENROUTER_KEY}",
            f"OPENAI_API_KEY={OPENAI_PROJECT_PREFIX}abcdefghijklmnopqrstuvwxyz1234567890",
            f"ANTHROPIC_API_KEY={ANTHROPIC_PREFIX}abcdefghijklmnopqrstuvwxyz123456",
            f"PPLX_API_KEY={PERPLEXITY_PREFIX}abcdefghijklmnopqrstuvwxyz123456",
            f"GOOGLE_API_KEY={GOOGLE_PREFIX}abcdefghijklmnopqrstuvwxyz123456",
            f"AWS_ACCESS_KEY_ID={AWS_PREFIX}ABCDEFGHIJKLMNOP",
            f"HF_TOKEN={HF_PREFIX}abcdefghijklmnopqrstuvwxyz123456",
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
