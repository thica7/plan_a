from __future__ import annotations

from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_enterprise_store
from app.main import create_app
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.governance import build_runtime_policy_decision
from packages.schema.enterprise import WorkspaceQuotaUpdateRequest

DEFAULT_WORKSPACE_ID = "default-workspace"


def test_runtime_policy_allows_configured_real_run_tools() -> None:
    store = EnterpriseMemoryStore()
    decision = build_runtime_policy_decision(
        _settings(
            ark_api_key="primary-key",
            ark_model="primary-model",
            pplx_api_key="pplx-key",
        ),
        store=store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        execution_mode="real",
        requested_tools=["web_search", "fetch_page", "claim_validator"],
        estimated_input_tokens=1000,
        estimated_output_tokens=500,
    )

    assert decision.status == "allow"
    assert decision.selected_provider_kind == "primary"
    assert decision.selected_model == "primary-model"
    assert decision.denied_tool_count == 0
    assert decision.allowed_tool_count == 3
    assert decision.quota_allowed is True
    assert decision.quota_status == "ok"
    assert decision.estimated_cost_usd > 0
    assert decision.audit_reason == "Runtime policy allows execution."


def test_runtime_policy_makes_backup_fallback_traceable() -> None:
    store = EnterpriseMemoryStore()
    decision = build_runtime_policy_decision(
        _settings(
            backup_llm_api_key="backup-key",
            backup_llm_model="deepseek/deepseek-v4-pro",
            pplx_api_key="pplx-key",
        ),
        store=store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        execution_mode="real",
        requested_tools=["web_search", "fetch_page"],
    )

    assert decision.status == "warn"
    assert decision.model_route_status == "fallback"
    assert decision.selected_provider_kind == "backup"
    assert decision.selected_model == "deepseek/deepseek-v4-pro"
    assert "fallback provider" in decision.audit_reason


def test_runtime_policy_denies_real_mode_when_requested_tool_is_not_allowed() -> None:
    store = EnterpriseMemoryStore()
    decision = build_runtime_policy_decision(
        _settings(
            ark_api_key="primary-key",
            ark_model="primary-model",
            pplx_api_key=None,
        ),
        store=store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        execution_mode="real",
        requested_tools=["online_gap_fill"],
    )

    assert decision.status == "deny"
    assert decision.denied_tool_count == 1
    tool = decision.tool_decisions[0]
    assert tool.tool_name == "online_gap_fill"
    assert tool.status == "denied"
    assert "search credentials" in tool.reason.lower()
    assert "requested tool" in decision.audit_reason


def test_runtime_policy_denies_quota_block_and_reports_pressure() -> None:
    store = EnterpriseMemoryStore()
    store.update_workspace_quota(
        DEFAULT_WORKSPACE_ID,
        WorkspaceQuotaUpdateRequest(monthly_run_quota=0, quota_enforcement="block"),
    )

    decision = build_runtime_policy_decision(
        _settings(
            ark_api_key="primary-key",
            ark_model="primary-model",
            pplx_api_key="pplx-key",
        ),
        store=store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        execution_mode="real",
        requested_tools=["web_search"],
    )

    assert decision.status == "deny"
    assert decision.quota_allowed is False
    assert decision.quota_status == "exceeded"
    assert decision.quota_enforcement == "block"
    assert decision.quota_pressure == "runs:100%"
    assert "quota blocks" in decision.audit_reason


def test_enterprise_runtime_policy_route_explains_policy_before_run() -> None:
    store = EnterpriseMemoryStore()
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: _settings(
        backup_llm_api_key="backup-key",
        backup_llm_model="deepseek/deepseek-v4-pro",
        pplx_api_key="pplx-key",
    )
    client = TestClient(app)

    response = client.get(
        "/api/enterprise/governance/runtime-policy",
        params=[
            ("workspace_id", DEFAULT_WORKSPACE_ID),
            ("execution_mode", "real"),
            ("requested_tools", "web_search"),
            ("requested_tools", "fetch_page"),
            ("estimated_input_tokens", "500"),
            ("estimated_output_tokens", "200"),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["policy_version"] == "c5.6-runtime-policy"
    assert body["status"] == "warn"
    assert body["model_route_status"] == "fallback"
    assert body["selected_provider_kind"] == "backup"
    assert body["quota_allowed"] is True
    assert [item["tool_name"] for item in body["tool_decisions"]] == [
        "web_search",
        "fetch_page",
    ]


def _settings(**overrides: object) -> Settings:
    values = {
        "demo_mode": True,
        "ark_api_key": None,
        "ark_model": None,
        "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "llm_timeout_seconds": 10,
        "llm_temperature": 0.2,
        "enterprise_store_backend": "memory",
        "enterprise_database_url": None,
        "compliance_redaction_enabled": True,
        "compliance_require_trace_context": True,
    }
    values.update(overrides)
    return Settings(**values)
