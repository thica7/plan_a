from packages.auth import (
    EnterpriseUserContext,
    can_access_workspace,
    can_perform,
    evaluate_access_policy,
    list_policy_actions,
    normalize_role,
)
from packages.config import Settings
from packages.governance import build_model_policy_report


def test_rbac_role_permissions_are_ordered() -> None:
    assert can_perform("owner", "audit:read")
    assert can_perform("analyst", "project:write")
    assert can_perform("reviewer", "evidence:review")
    assert not can_perform("viewer", "project:write")
    assert not can_perform("reviewer", "evidence:write")


def test_rbac_workspace_scope_blocks_cross_workspace_access() -> None:
    user = EnterpriseUserContext(user_id="viewer-1", role="viewer", workspace_id="workspace-a")

    assert can_access_workspace(user, "workspace-a", "project:read")
    assert not can_access_workspace(user, "workspace-b", "project:read")
    assert normalize_role("unknown") == "viewer"


def test_policy_decision_explains_denies_and_allows() -> None:
    viewer = EnterpriseUserContext(
        user_id="viewer-1",
        role="viewer",
        workspace_id="workspace-a",
    )
    analyst = EnterpriseUserContext(
        user_id="analyst-1",
        role="analyst",
        workspace_id="workspace-a",
    )

    role_deny = evaluate_access_policy(viewer, "workspace-a", "project:write")
    scope_deny = evaluate_access_policy(analyst, "workspace-b", "project:write")
    allow = evaluate_access_policy(analyst, "workspace-a", "project:write")

    assert role_deny.allowed is False
    assert role_deny.matched_rules[0].rule_id == "deny_role_below_minimum"
    assert scope_deny.allowed is False
    assert scope_deny.matched_rules[0].rule_id == "deny_cross_workspace_scope"
    assert allow.allowed is True
    assert allow.engine == "internal-opa-compatible"
    assert list_policy_actions()["audit:read"] == "admin"


def test_model_policy_report_blocks_disabled_redaction() -> None:
    settings = Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=180,
        llm_temperature=0.2,
        compliance_redaction_enabled=False,
    )

    report = build_model_policy_report(settings)

    assert report.status == "fail"
    assert report.real_execution_allowed is False
    assert report.blocker_count == 1
    assert report.blocking_finding_ids == [
        "provider.no_real_provider",
        "compliance.redaction_disabled",
    ]
    assert {finding.id for finding in report.findings} >= {
        "compliance.redaction_disabled",
        "provider.no_real_provider",
        "cost.timeout_high",
    }
