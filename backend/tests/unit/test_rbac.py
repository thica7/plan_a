from packages.auth import EnterpriseUserContext, can_access_workspace, can_perform, normalize_role


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
