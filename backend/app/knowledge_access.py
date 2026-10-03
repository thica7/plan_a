"""Build knowledge boundaries from the authenticated enterprise subject."""

from fastapi import HTTPException

from app.deps import get_enterprise_store
from packages.auth import EnterpriseUserContext, can_access_workspace
from packages.enterprise.store import DEFAULT_WORKSPACE_ID, EnterpriseStore
from packages.knowledge.models import KnowledgeScope


def resolve_knowledge_scope(
    user: EnterpriseUserContext,
    action: str,
    *,
    store: EnterpriseStore | None = None,
    project_id: str | None = None,
    include_workspace_library: bool = False,
) -> KnowledgeScope:
    workspace_id = user.workspace_id or DEFAULT_WORKSPACE_ID
    if not can_access_workspace(user, workspace_id, action):
        raise HTTPException(status_code=403, detail="Insufficient workspace permission")
    if project_id is not None:
        project = (store or get_enterprise_store()).get_project(project_id)
        if not project_id.strip() or project is None or project.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Project not found")
    return KnowledgeScope(
        workspace_id=workspace_id,
        project_id=project_id,
        include_workspace_library=include_workspace_library,
    )


def select_project(query_project: str | None, body_project: str | None) -> str | None:
    if query_project is not None and body_project is not None and query_project != body_project:
        raise HTTPException(status_code=400, detail="Conflicting project selections")
    return query_project if query_project is not None else body_project


def stored_job_scope(row) -> KnowledgeScope:
    if row is None:
        raise ValueError("Knowledge job is missing")
    values = dict(row)
    workspace_id = values.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ValueError("Knowledge job has no trusted workspace")
    return KnowledgeScope(workspace_id=workspace_id, project_id=values.get("project_id"))
