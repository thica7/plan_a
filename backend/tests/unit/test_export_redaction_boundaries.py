"""Synthetic export regressions for credential syntax and JSON boundaries."""

import json
from urllib.parse import quote

import pytest

from scripts.eval_live_products import redacted_json
from scripts.export_agent_eval import _redact


@pytest.mark.parametrize(
    "heading",
    ["1Password", "7Password", "2026Secret", "3Authorization", "2ApiKey"],
)
@pytest.mark.parametrize("prefix", ["", "# ", "产品比较： "])
def test_unquoted_numeric_product_heading_preserves_report(heading, prefix):
    report = f"{prefix}{heading}: 产品功能分析\n\n正文包含方案和适用条件。"

    assert _redact(report) == report


@pytest.mark.parametrize(
    "text",
    [
        "Monkey: public product documentation.",
        "Tokenization: public product documentation.",
        "Passwordless: public authentication feature.",
        "The password manager compares plans.\nNext paragraph.",
    ],
)
def test_ordinary_credential_word_context_preserves_text(text):
    assert _redact(text) == text


@pytest.mark.parametrize(
    "assignment",
    [
        "db_password: synthetic-private-marker",
        "service-password=synthetic-private-marker",
        "dbPassword: synthetic-private-marker",
        "databaseSecret: synthetic-private-marker",
        "apiKey: synthetic-private-marker",
        "DB_PASSWORD: synthetic-private-marker",
        "dbpassword=synthetic-private-marker",
        "1Password=synthetic-private-marker",
        '"1Password": "synthetic-private-marker"',
        '{"7Password": "synthetic-private-marker"}',
        "https://example.test?1Password=synthetic-private-marker&public=ok",
        'api_key": "synthetic-private-marker"',
        "password'=synthetic-private-marker",
    ],
)
def test_explicit_or_identifier_credential_assignments_remain_redacted(assignment):
    safe = _redact(assignment)

    assert "synthetic-private-marker" not in safe
    assert "[redacted:" in safe
    if "&public=ok" in assignment:
        assert "&public=ok" in safe


def _sensitive_examples():
    examples = [
        ("password=private-marker", ["private-marker"]),
        ("password: private-marker", ["private-marker"]),
        ("db_password=private-marker", ["private-marker"]),
        ("dbPassword=private-marker", ["private-marker"]),
        ("dbpassword=private-marker", ["private-marker"]),
        ("1Password=private-marker", ["private-marker"]),
        (json.dumps({"password": 'abc\\"private-marker'}), ["private-marker"]),
        ('password="abc private-marker"', ["private-marker"]),
        (json.dumps({"password": 'abc\\\"private-marker'}), ["private-marker"]),
        ("Authorization: Bearer private-marker", ["private-marker"]),
        ("Authorization=Basic private-marker", ["private-marker"]),
        ("Bearer private-marker", ["private-marker"]),
        (
            "https://synthetic-user:private-marker@example.test/path",
            ["synthetic-user", "private-marker"],
        ),
        ("密钥sk-synthetic000000000000000000用于测试", ["sk-synthetic000000000000000000"]),
        ("联系ops@example.test获得帮助", ["ops@example.test"]),
        ("联系电话13800138000获得帮助", ["13800138000"]),
    ]
    for separator in (";", "?", "%26"):
        examples.append(
            (
                f"https://example.test?password=abc{separator}private-marker&public=ok",
                ["private-marker"],
            )
        )
    for assignment in ("%70assword=abc%26private-marker", "password%3Dabc%26private-marker"):
        for extra_rounds in range(3):
            encoded = assignment
            for _ in range(extra_rounds):
                encoded = quote(encoded, safe="")
            examples.append((f"https://example.test?{encoded}&public=ok", ["private-marker"]))
    examples.append(
        (
            "https://example.test%3F%70assword=abc%26private-marker&public=ok",
            ["private-marker"],
        )
    )
    for whitespace in (" ", "\t", "\n"):
        for name in ("pass%77ord", "password%3D"):
            separator = whitespace + "=" + whitespace if name == "pass%77ord" else whitespace
            examples.append(
                (name + separator + "abc%26private-marker&public=ok", ["private-marker"])
            )
    return examples


@pytest.mark.parametrize("text,private", _sensitive_examples())
def test_secret_and_pii_safety_matrix(text, private):
    safe = _redact(text)

    assert all(marker not in safe for marker in private)
    if "&public=ok" in text:
        assert "&public=ok" in safe


def test_url_credentials_do_not_cross_json_quotes_to_another_field():
    payload = {"url": "https://example.test", "contact": "ops@example.test", "count": 3}
    compact = json.dumps(payload, separators=(",", ":"))

    safe = json.loads(_redact(compact))

    assert safe["url"] == payload["url"]
    assert safe["contact"] == "[redacted:email]"
    assert safe["count"] == 3


@pytest.mark.parametrize(
    "userinfo",
    [
        "synthetic-user:private-marker",
        "synthetic-user:abc'private-marker",
        "synthetic-user:abc%22private-marker",
        "synthetic-user:abc%2526private-marker",
    ],
)
def test_actual_url_userinfo_stays_redacted_inside_compact_json(userinfo):
    compact = json.dumps(
        {"url": f"https://{userinfo}@example.test/path", "status": "ok"},
        separators=(",", ":"),
    )

    safe_text = _redact(compact)
    safe = json.loads(safe_text)

    assert "synthetic-user" not in safe_text
    assert "private-marker" not in safe_text
    assert safe["status"] == "ok"
    assert safe["url"].endswith("@example.test/path")


def test_recursive_json_preserves_numeric_title_and_serialized_pipeline():
    report = "# 1Password: 产品功能分析\n\n正文包含方案和适用条件。"
    pipeline = json.dumps({"report_md": report, "status": "completed"}, ensure_ascii=False)
    payload = {
        "report_md": report,
        "pipeline_json": pipeline,
        "nested": [report],
        "status": "completed",
        "count": 3,
    }

    safe = json.loads(redacted_json(payload))

    assert safe == payload
    assert json.loads(safe["pipeline_json"]) == json.loads(pipeline)


def test_serialized_pipeline_with_public_url_and_email_remains_parseable():
    pipeline = json.dumps(
        {"url": "https://example.test", "contact": "ops@example.test", "status": "ok"},
        separators=(",", ":"),
    )

    safe_outer = json.loads(redacted_json({"pipeline_json": pipeline, "count": 3}))
    safe_pipeline = json.loads(safe_outer["pipeline_json"])

    assert safe_pipeline["url"] == "https://example.test"
    assert safe_pipeline["contact"] == "[redacted:email]"
    assert safe_pipeline["status"] == "ok"
    assert safe_outer["count"] == 3


@pytest.mark.parametrize(
    "credential_key",
    [
        "password",
        "api_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "dbPassword",
        "1Password",
        "authorization",
        "token",
        "key",
        "pass%77ord",
        "api%255Fkey",
    ],
)
def test_recursive_json_redacts_short_sensitive_key_values(credential_key):
    payload = {
        "nested": [{credential_key: "synthetic-private-marker", "label": "public"}],
        "status": "ok",
        "count": 3,
    }

    safe_text = redacted_json(payload)
    safe = json.loads(safe_text)

    assert "synthetic-private-marker" not in safe_text
    assert safe["nested"][0]["label"] == "public"
    assert credential_key in safe["nested"][0]
    assert safe["status"] == "ok"
    assert safe["count"] == 3
