from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol

from packages.identity import compute_competitor_set_hash, compute_topic_normalized
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import (
    AuditLogRecord,
    ClaimRecord,
    CompetitorRecord,
    EnterpriseRunProjection,
    EvidenceRecord,
    ProjectCompetitorLink,
    ProjectRecord,
    ReportVersionRecord,
    UserRecord,
    WorkspaceRecord,
)

DEFAULT_WORKSPACE_ID = "default-workspace"
DEFAULT_USER_ID = "system-user"


@dataclass(frozen=True)
class EnterpriseRunContext:
    workspace_id: str
    project_id: str
    user_id: str
    competitor_ids: list[str]
    competitor_id_map: dict[str, str]


class EnterpriseStore(Protocol):
    def start_run(
        self,
        detail: RunDetail,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        actor_id: str | None = None,
    ) -> EnterpriseRunContext: ...

    def save_projection(self, projection: EnterpriseRunProjection) -> None: ...

    def project_id_for_run(self, run_id: str) -> str | None: ...

    def get_run_projection(self, run_id: str) -> EnterpriseRunProjection | None: ...


class EnterpriseMemoryStore:
    """Phase 1 enterprise repository boundary, with Postgres-compatible semantics."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.workspaces: dict[str, WorkspaceRecord] = {}
        self.users: dict[str, UserRecord] = {}
        self.projects: dict[str, ProjectRecord] = {}
        self.competitors: dict[str, CompetitorRecord] = {}
        self.project_competitors: dict[tuple[str, str], ProjectCompetitorLink] = {}
        self.evidence_records: dict[str, EvidenceRecord] = {}
        self.claim_records: dict[str, ClaimRecord] = {}
        self.report_versions: dict[str, ReportVersionRecord] = {}
        self.audit_logs: list[AuditLogRecord] = []
        self._run_contexts: dict[str, EnterpriseRunContext] = {}
        self.bootstrap_defaults()

    def bootstrap_defaults(self) -> None:
        with self._lock:
            self.workspaces.setdefault(
                DEFAULT_WORKSPACE_ID,
                WorkspaceRecord(
                    id=DEFAULT_WORKSPACE_ID,
                    name="Default Workspace",
                    description="Phase 1 default workspace.",
                ),
            )
            self.users.setdefault(
                DEFAULT_USER_ID,
                UserRecord(
                    id=DEFAULT_USER_ID,
                    email="system@local",
                    display_name="System",
                    role="owner",
                ),
            )

    def start_run(
        self,
        detail: RunDetail,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        actor_id: str | None = None,
    ) -> EnterpriseRunContext:
        workspace_id = workspace_id or detail.workspace_id or DEFAULT_WORKSPACE_ID
        actor_id = actor_id or DEFAULT_USER_ID
        competitor_ids = [
            self._competitor_id(workspace_id, name) for name in detail.plan.competitors
        ]
        project_id = project_id or detail.project_id or self._project_id(
            workspace_id,
            detail.topic,
            competitor_ids,
        )
        now = datetime.utcnow()
        context = EnterpriseRunContext(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=actor_id,
            competitor_ids=competitor_ids,
            competitor_id_map={
                name: competitor_id
                for name, competitor_id in zip(
                    detail.plan.competitors,
                    competitor_ids,
                    strict=False,
                )
            },
        )

        with self._lock:
            is_new_run = detail.id not in self._run_contexts
            self._ensure_workspace(workspace_id)
            project = self.projects.get(project_id)
            if project is None:
                project = ProjectRecord(
                    id=project_id,
                    workspace_id=workspace_id,
                    name=detail.topic,
                    topic=detail.topic,
                    topic_normalized=compute_topic_normalized(detail.topic),
                    competitor_set_hash=compute_competitor_set_hash(competitor_ids),
                    created_by=actor_id,
                    created_at=detail.created_at,
                    updated_at=now,
                )
                self.projects[project_id] = project
            else:
                project.topic = detail.topic
                project.topic_normalized = compute_topic_normalized(detail.topic)
                project.competitor_set_hash = compute_competitor_set_hash(competitor_ids)
                project.updated_at = now
            for name, competitor_id in zip(detail.plan.competitors, competitor_ids, strict=False):
                self.competitors.setdefault(
                    competitor_id,
                    CompetitorRecord(
                        id=competitor_id,
                        workspace_id=workspace_id,
                        name=name,
                        normalized_name=_normalize_key(name),
                        homepage_url=detail.plan.homepage_hints.get(name),
                        created_at=detail.created_at,
                        updated_at=now,
                    ),
                )
                self.project_competitors.setdefault(
                    (project_id, competitor_id),
                    ProjectCompetitorLink(project_id=project_id, competitor_id=competitor_id),
                )
            self._run_contexts[detail.id] = context
            if is_new_run:
                self._append_audit(
                    workspace_id=workspace_id,
                    actor_id=actor_id,
                    action="run.created",
                    resource_type="run",
                    resource_id=detail.id,
                    after={
                        "project_id": project_id,
                        "topic": detail.topic,
                        "competitors": detail.plan.competitors,
                    },
                )
        return context

    def save_projection(self, projection: EnterpriseRunProjection) -> None:
        with self._lock:
            for evidence in projection.evidence_records:
                self.evidence_records[evidence.id] = evidence
            for claim in projection.claim_records:
                self.claim_records[claim.id] = claim
            self.report_versions[projection.report_version.id] = projection.report_version
            self._append_audit(
                workspace_id=projection.workspace_id,
                actor_id=DEFAULT_USER_ID,
                action="run.projected",
                resource_type="run",
                resource_id=projection.run_id,
                after={
                    "project_id": projection.project_id,
                    "evidence_count": len(projection.evidence_records),
                    "claim_count": len(projection.claim_records),
                    "report_version_id": projection.report_version.id,
                },
            )

    def project_id_for_run(self, run_id: str) -> str | None:
        with self._lock:
            context = self._run_contexts.get(run_id)
            return context.project_id if context else None

    def context_for_run(self, run_id: str) -> EnterpriseRunContext | None:
        with self._lock:
            return self._run_contexts.get(run_id)

    def list_workspaces(self) -> list[WorkspaceRecord]:
        with self._lock:
            return sorted(self.workspaces.values(), key=lambda item: item.created_at)

    def list_projects(self, workspace_id: str | None = None) -> list[ProjectRecord]:
        with self._lock:
            projects = list(self.projects.values())
            if workspace_id:
                projects = [item for item in projects if item.workspace_id == workspace_id]
            return sorted(projects, key=lambda item: item.updated_at, reverse=True)

    def list_evidence(self, project_id: str | None = None) -> list[EvidenceRecord]:
        with self._lock:
            records = list(self.evidence_records.values())
            if project_id:
                records = [item for item in records if item.project_id == project_id]
            return sorted(records, key=lambda item: item.captured_at, reverse=True)

    def list_claims(self, project_id: str | None = None) -> list[ClaimRecord]:
        with self._lock:
            records = list(self.claim_records.values())
            if project_id:
                records = [item for item in records if item.project_id == project_id]
            return sorted(records, key=lambda item: item.created_at, reverse=True)

    def list_report_versions(self, project_id: str | None = None) -> list[ReportVersionRecord]:
        with self._lock:
            records = list(self.report_versions.values())
            if project_id:
                records = [item for item in records if item.project_id == project_id]
            return sorted(
                records,
                key=lambda item: (item.created_at, item.version_number),
                reverse=True,
            )

    def list_audit_logs(self, workspace_id: str | None = None) -> list[AuditLogRecord]:
        with self._lock:
            records = list(self.audit_logs)
            if workspace_id:
                records = [item for item in records if item.workspace_id == workspace_id]
            return sorted(records, key=lambda item: item.created_at, reverse=True)

    def get_run_projection(self, run_id: str) -> EnterpriseRunProjection | None:
        with self._lock:
            versions = [item for item in self.report_versions.values() if item.run_id == run_id]
            if not versions:
                return None
            report_version = max(versions, key=lambda item: (item.version_number, item.created_at))
            evidence_ids = set(report_version.evidence_ids)
            claim_ids = set(report_version.claim_ids)
            return EnterpriseRunProjection(
                workspace_id=report_version.workspace_id,
                project_id=report_version.project_id,
                run_id=run_id,
                evidence_records=[
                    self.evidence_records[item]
                    for item in report_version.evidence_ids
                    if item in evidence_ids and item in self.evidence_records
                ],
                claim_records=[
                    self.claim_records[item]
                    for item in report_version.claim_ids
                    if item in claim_ids and item in self.claim_records
                ],
                report_version=report_version,
            )

    def _ensure_workspace(self, workspace_id: str) -> None:
        self.workspaces.setdefault(
            workspace_id,
            WorkspaceRecord(id=workspace_id, name=_title_from_id(workspace_id)),
        )

    def _append_audit(
        self,
        *,
        workspace_id: str,
        actor_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str,
        after: dict,
    ) -> None:
        self.audit_logs.append(
            AuditLogRecord(
                id=f"audit-{len(self.audit_logs) + 1:06d}",
                workspace_id=workspace_id,
                actor_type="system",
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                after=after,
            )
        )

    def _competitor_id(self, workspace_id: str, name: str) -> str:
        raw = f"{workspace_id}|{_normalize_key(name)}"
        return f"competitor-{_short_hash(raw)}"

    def _project_id(self, workspace_id: str, topic: str, competitor_ids: list[str]) -> str:
        raw = "|".join(
            [
                workspace_id,
                compute_topic_normalized(topic),
                compute_competitor_set_hash(competitor_ids),
            ]
        )
        return f"project-{_short_hash(raw)}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _normalize_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower().strip()).strip("-")
    return normalized or _short_hash(value)


def _title_from_id(value: str) -> str:
    return value.replace("-", " ").strip().title() or value
