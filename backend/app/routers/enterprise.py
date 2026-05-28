from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_enterprise_store
from packages.enterprise import EnterpriseMemoryStore
from packages.schema.enterprise import (
    AuditLogRecord,
    ClaimRecord,
    EnterpriseRunProjection,
    EvidenceRecord,
    ProjectRecord,
    ReportVersionRecord,
    WorkspaceRecord,
)

router = APIRouter()
EnterpriseStoreDep = Annotated[EnterpriseMemoryStore, Depends(get_enterprise_store)]


@router.get("/enterprise/workspaces", response_model=list[WorkspaceRecord])
def list_workspaces(
    store: EnterpriseStoreDep,
) -> list[WorkspaceRecord]:
    return store.list_workspaces()


@router.get("/enterprise/projects", response_model=list[ProjectRecord])
def list_projects(
    store: EnterpriseStoreDep,
    workspace_id: str | None = None,
) -> list[ProjectRecord]:
    return store.list_projects(workspace_id=workspace_id)


@router.get("/enterprise/projects/{project_id}/evidence", response_model=list[EvidenceRecord])
def list_project_evidence(
    project_id: str,
    store: EnterpriseStoreDep,
) -> list[EvidenceRecord]:
    return store.list_evidence(project_id=project_id)


@router.get("/enterprise/projects/{project_id}/claims", response_model=list[ClaimRecord])
def list_project_claims(
    project_id: str,
    store: EnterpriseStoreDep,
) -> list[ClaimRecord]:
    return store.list_claims(project_id=project_id)


@router.get(
    "/enterprise/projects/{project_id}/report-versions",
    response_model=list[ReportVersionRecord],
)
def list_project_report_versions(
    project_id: str,
    store: EnterpriseStoreDep,
) -> list[ReportVersionRecord]:
    return store.list_report_versions(project_id=project_id)


@router.get("/enterprise/runs/{run_id}/projection", response_model=EnterpriseRunProjection)
def get_run_projection(
    run_id: str,
    store: EnterpriseStoreDep,
) -> EnterpriseRunProjection:
    projection = store.get_run_projection(run_id)
    if projection is None:
        raise HTTPException(status_code=404, detail="Enterprise projection not found")
    return projection


@router.get("/enterprise/audit-logs", response_model=list[AuditLogRecord])
def list_audit_logs(
    store: EnterpriseStoreDep,
    workspace_id: str | None = None,
) -> list[AuditLogRecord]:
    return store.list_audit_logs(workspace_id=workspace_id)
