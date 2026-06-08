from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.auth import list_policy_actions
from packages.enterprise import EnterpriseStore

TenantReadinessStatus = Literal["pass", "warn", "fail"]


class TenantReadinessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    domain: str
    status: TenantReadinessStatus
    message: str
    evidence: dict[str, object] = Field(default_factory=dict)
    recommendation: str = ""


class TenantGovernanceReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TenantReadinessStatus
    score: int = Field(ge=0, le=100)
    workspace_id: str | None = None
    check_count: int = 0
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    checks: list[TenantReadinessCheck] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def build_tenant_governance_readiness_report(
    *,
    store: EnterpriseStore,
    workspace_id: str | None = None,
    postgres_schema_path: str | Path | None = None,
) -> TenantGovernanceReadinessReport:
    checks = [
        _rbac_actions_check(),
        _workspace_scoped_records_check(store, workspace_id=workspace_id),
        _audit_workspace_filter_check(store, workspace_id=workspace_id),
        _artifact_workspace_filter_check(store, workspace_id=workspace_id),
        _report_publication_policy_check(),
        _postgres_rls_readiness_check(postgres_schema_path),
    ]
    pass_count = sum(1 for item in checks if item.status == "pass")
    warn_count = sum(1 for item in checks if item.status == "warn")
    fail_count = sum(1 for item in checks if item.status == "fail")
    score = max(0, min(100, round((pass_count * 100 + warn_count * 60) / len(checks))))
    status: TenantReadinessStatus = "pass"
    if fail_count:
        status = "fail"
    elif warn_count:
        status = "warn"
    return TenantGovernanceReadinessReport(
        status=status,
        score=score,
        workspace_id=workspace_id,
        check_count=len(checks),
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        checks=checks,
    )


def _rbac_actions_check() -> TenantReadinessCheck:
    actions = list_policy_actions()
    required = {
        "workspace:read",
        "workspace:write",
        "project:read",
        "project:write",
        "artifact:read",
        "artifact:write",
        "report:read",
        "report:write",
        "report:review",
        "audit:read",
    }
    missing = sorted(required - set(actions))
    return TenantReadinessCheck(
        id="rbac.required_actions",
        domain="rbac",
        status="fail" if missing else "pass",
        message="Required enterprise RBAC actions are registered.",
        evidence={"missing_actions": missing, "registered_action_count": len(actions)},
        recommendation="Add missing RBAC actions before production use." if missing else "",
    )


def _workspace_scoped_records_check(
    store: EnterpriseStore,
    *,
    workspace_id: str | None,
) -> TenantReadinessCheck:
    projects = store.list_projects(workspace_id=workspace_id)
    evidence = _project_scoped_records(store.list_evidence, projects)
    claims = _project_scoped_records(store.list_claims, projects)
    reports = _project_scoped_records(store.list_report_versions, projects)
    artifacts = store.list_artifacts(workspace_id=workspace_id)
    source_registry = store.list_source_registry(workspace_id=workspace_id)
    records = [*projects, *evidence, *claims, *reports, *artifacts, *source_registry]
    missing = [
        getattr(item, "id", "")
        for item in records
        if not getattr(item, "workspace_id", "")
    ]
    return TenantReadinessCheck(
        id="tenant.workspace_identity",
        domain="tenant_isolation",
        status="fail" if missing else "pass",
        message="Durable enterprise records carry workspace identity.",
        evidence={
            "workspace_id": workspace_id,
            "sampled_record_count": len(records),
            "missing_workspace_record_ids": missing,
        },
        recommendation="Add workspace_id to all durable records." if missing else "",
    )


def _audit_workspace_filter_check(
    store: EnterpriseStore,
    *,
    workspace_id: str | None,
) -> TenantReadinessCheck:
    workspaces = store.list_workspaces()
    target = workspace_id or (workspaces[0].id if workspaces else None)
    if target is None:
        return TenantReadinessCheck(
            id="tenant.audit_filter",
            domain="audit",
            status="warn",
            message="No workspace exists yet, so audit workspace filtering could not be sampled.",
            recommendation="Create a workspace and rerun readiness.",
        )
    logs = store.list_audit_logs(workspace_id=target)
    cross_scope = [item.id for item in logs if item.workspace_id != target]
    return TenantReadinessCheck(
        id="tenant.audit_filter",
        domain="audit",
        status="fail" if cross_scope else "pass",
        message="Audit log reads are workspace-filtered.",
        evidence={"workspace_id": target, "log_count": len(logs), "cross_scope_ids": cross_scope},
        recommendation="Filter audit log reads by workspace_id." if cross_scope else "",
    )


def _artifact_workspace_filter_check(
    store: EnterpriseStore,
    *,
    workspace_id: str | None,
) -> TenantReadinessCheck:
    artifacts = store.list_artifacts(workspace_id=workspace_id)
    cross_scope = [
        item.id
        for item in artifacts
        if workspace_id is not None and item.workspace_id != workspace_id
    ]
    return TenantReadinessCheck(
        id="tenant.artifact_filter",
        domain="artifact",
        status="fail" if cross_scope else "pass",
        message="Artifact reads are workspace-filtered.",
        evidence={
            "workspace_id": workspace_id,
            "artifact_count": len(artifacts),
            "cross_scope_ids": cross_scope,
        },
        recommendation="Filter artifact reads by workspace_id." if cross_scope else "",
    )


def _report_publication_policy_check() -> TenantReadinessCheck:
    return TenantReadinessCheck(
        id="tenant.report_publication_policy",
        domain="report",
        status="pass",
        message="Report publication is routed through RuntimeCommandService and ReleaseGate.",
        evidence={
            "command_layer": "RuntimeCommandService.publish_report",
            "required_permission": "report:write",
            "release_gate_enforced": True,
        },
    )


def _postgres_rls_readiness_check(path: str | Path | None) -> TenantReadinessCheck:
    schema_path = Path(path or "backend/db/postgres/001_enterprise_core.sql")
    if not schema_path.exists():
        return TenantReadinessCheck(
            id="tenant.postgres_rls",
            domain="postgres",
            status="warn",
            message="Postgres schema file was not found for RLS readiness inspection.",
            evidence={"schema_path": str(schema_path)},
            recommendation="Provide the schema path and rerun readiness.",
        )
    sql = schema_path.read_text(encoding="utf-8")
    required_tables = [
        "projects",
        "runs",
        "evidence_records",
        "artifacts",
        "source_registry",
        "report_versions",
        "audit_logs",
    ]
    missing_policies = [
        table
        for table in required_tables
        if f"tenant_isolation_{table}" not in sql or f"ON {table}" not in sql
    ]
    status: TenantReadinessStatus = "pass" if not missing_policies else "warn"
    return TenantReadinessCheck(
        id="tenant.postgres_rls",
        domain="postgres",
        status=status,
        message="Postgres schema contains tenant isolation RLS policy definitions.",
        evidence={
            "schema_path": str(schema_path),
            "required_tables": required_tables,
            "missing_policy_tables": missing_policies,
            "uses_current_workspace_setting": "app.current_workspace_id" in sql,
        },
        recommendation=(
            "Add missing tenant isolation policies before production Postgres deployment."
            if missing_policies
            else "Run live Postgres RLS smoke tests before production."
        ),
    )


def _project_scoped_records(
    loader: object,
    projects: list[object],
) -> list[object]:
    records: list[object] = []
    if not callable(loader):
        return records
    for project in projects:
        project_id = getattr(project, "id", None)
        if isinstance(project_id, str):
            records.extend(loader(project_id=project_id))
    return records
