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
    EvidenceQualityLabel,
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

    def next_report_version_number(
        self,
        *,
        project_id: str,
        topic_normalized: str,
        competitor_layer: str,
        competitor_set_hash: str,
    ) -> int: ...

    def project_id_for_run(self, run_id: str) -> str | None: ...

    def get_run_projection(self, run_id: str) -> EnterpriseRunProjection | None: ...

    def list_workspaces(self) -> list[WorkspaceRecord]: ...

    def list_projects(self, workspace_id: str | None = None) -> list[ProjectRecord]: ...

    def get_project(self, project_id: str) -> ProjectRecord | None: ...

    def upsert_project(self, project: ProjectRecord) -> ProjectRecord: ...

    def list_competitors(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> list[CompetitorRecord]: ...

    def list_evidence(self, project_id: str | None = None) -> list[EvidenceRecord]: ...

    def upsert_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord: ...

    def update_evidence_quality(
        self,
        evidence_id: str,
        quality_label: EvidenceQualityLabel,
        *,
        actor_id: str | None = None,
        note: str = "",
    ) -> EvidenceRecord | None: ...

    def list_claims(self, project_id: str | None = None) -> list[ClaimRecord]: ...

    def list_report_versions(self, project_id: str | None = None) -> list[ReportVersionRecord]: ...

    def upsert_report_version(self, version: ReportVersionRecord) -> ReportVersionRecord: ...

    def get_report_version(self, version_id: str) -> ReportVersionRecord | None: ...

    def get_previous_report_version(
        self,
        version: ReportVersionRecord,
    ) -> ReportVersionRecord | None: ...

    def list_audit_logs(self, workspace_id: str | None = None) -> list[AuditLogRecord]: ...


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
        project_id = (
            project_id
            or detail.project_id
            or self._project_id(
                workspace_id,
                detail.topic,
                competitor_ids,
            )
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
                    competitor_layer=detail.plan.competitor_layer,
                    competitor_set_hash=compute_competitor_set_hash(competitor_ids),
                    scenario_id=detail.plan.scenario_id,
                    created_by=actor_id,
                    created_at=detail.created_at,
                    updated_at=now,
                )
                self.projects[project_id] = project
            else:
                project.topic = detail.topic
                project.topic_normalized = compute_topic_normalized(detail.topic)
                project.competitor_layer = detail.plan.competitor_layer
                project.competitor_set_hash = compute_competitor_set_hash(competitor_ids)
                project.scenario_id = detail.plan.scenario_id
                project.updated_at = now
            self._append_audit_once(
                workspace_id=workspace_id,
                actor_id=actor_id,
                action="project.upserted",
                resource_type="project",
                resource_id=project_id,
                after={
                    "topic": detail.topic,
                    "competitor_layer": detail.plan.competitor_layer,
                    "scenario_id": detail.plan.scenario_id,
                },
            )
            for name, competitor_id in zip(detail.plan.competitors, competitor_ids, strict=False):
                competitor = self.competitors.get(competitor_id)
                if competitor is None:
                    self.competitors[competitor_id] = CompetitorRecord(
                        id=competitor_id,
                        workspace_id=workspace_id,
                        name=name,
                        normalized_name=_normalize_key(name),
                        layer=detail.plan.competitor_layer,
                        homepage_url=detail.plan.homepage_hints.get(name),
                        metadata={
                            "scenario_id": detail.plan.scenario_id,
                            "qa_rule_ids": detail.plan.qa_rule_ids,
                        },
                        created_at=detail.created_at,
                        updated_at=now,
                    )
                else:
                    competitor.name = name
                    competitor.layer = detail.plan.competitor_layer
                    competitor.homepage_url = detail.plan.homepage_hints.get(name)
                    competitor.metadata["scenario_id"] = detail.plan.scenario_id
                    competitor.metadata["qa_rule_ids"] = detail.plan.qa_rule_ids
                    competitor.updated_at = now
                self._append_audit_once(
                    workspace_id=workspace_id,
                    actor_id=actor_id,
                    action="competitor.upserted",
                    resource_type="competitor",
                    resource_id=competitor_id,
                    after={"name": name, "layer": detail.plan.competitor_layer},
                )
                link_key = (project_id, competitor_id)
                self.project_competitors.setdefault(
                    link_key,
                    ProjectCompetitorLink(project_id=project_id, competitor_id=competitor_id),
                )
                self._append_audit_once(
                    workspace_id=workspace_id,
                    actor_id=actor_id,
                    action="project_competitor.linked",
                    resource_type="project_competitor",
                    resource_id=f"{project_id}:{competitor_id}",
                    after={"project_id": project_id, "competitor_id": competitor_id},
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
            if projection.evidence_records:
                self._append_audit_once(
                    workspace_id=projection.workspace_id,
                    actor_id=DEFAULT_USER_ID,
                    action="evidence.upserted",
                    resource_type="run",
                    resource_id=projection.run_id,
                    after={
                        "project_id": projection.project_id,
                        "evidence_ids": [item.id for item in projection.evidence_records],
                    },
                )
            if projection.claim_records:
                self._append_audit_once(
                    workspace_id=projection.workspace_id,
                    actor_id=DEFAULT_USER_ID,
                    action="claim.upserted",
                    resource_type="run",
                    resource_id=projection.run_id,
                    after={
                        "project_id": projection.project_id,
                        "claim_ids": [item.id for item in projection.claim_records],
                    },
                )
            self._append_audit_once(
                workspace_id=projection.workspace_id,
                actor_id=DEFAULT_USER_ID,
                action="report_version.upserted",
                resource_type="report_version",
                resource_id=projection.report_version.id,
                after={
                    "project_id": projection.project_id,
                    "run_id": projection.run_id,
                    "version_number": projection.report_version.version_number,
                },
            )
            self._append_audit_once(
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

    def next_report_version_number(
        self,
        *,
        project_id: str,
        topic_normalized: str,
        competitor_layer: str,
        competitor_set_hash: str,
    ) -> int:
        with self._lock:
            versions = [
                version.version_number
                for version in self.report_versions.values()
                if version.project_id == project_id
                and version.topic_normalized == topic_normalized
                and version.competitor_layer == competitor_layer
                and version.competitor_set_hash == competitor_set_hash
            ]
            return (max(versions) + 1) if versions else 1

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

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self._lock:
            return self.projects.get(project_id)

    def upsert_project(self, project: ProjectRecord) -> ProjectRecord:
        with self._lock:
            self._ensure_workspace(project.workspace_id)
            existing = self.projects.get(project.id)
            before = existing.model_dump(mode="json") if existing is not None else None
            self.projects[project.id] = project
            self._append_audit(
                workspace_id=project.workspace_id,
                actor_id=project.created_by or DEFAULT_USER_ID,
                action="project.upserted",
                resource_type="project",
                resource_id=project.id,
                before=before,
                after=project.model_dump(mode="json"),
            )
            return project

    def list_competitors(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> list[CompetitorRecord]:
        with self._lock:
            records = list(self.competitors.values())
            if workspace_id:
                records = [item for item in records if item.workspace_id == workspace_id]
            if project_id:
                linked_ids = {
                    competitor_id
                    for link_project_id, competitor_id in self.project_competitors
                    if link_project_id == project_id
                }
                records = [item for item in records if item.id in linked_ids]
            return sorted(records, key=lambda item: item.name.casefold())

    def list_evidence(self, project_id: str | None = None) -> list[EvidenceRecord]:
        with self._lock:
            records = list(self.evidence_records.values())
            if project_id:
                records = [item for item in records if item.project_id == project_id]
            return sorted(records, key=lambda item: item.captured_at, reverse=True)

    def upsert_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        with self._lock:
            before_record = self.evidence_records.get(evidence.id)
            self.evidence_records[evidence.id] = evidence
            self._append_audit(
                workspace_id=evidence.workspace_id,
                actor_id=DEFAULT_USER_ID,
                action="evidence.upserted",
                resource_type="evidence",
                resource_id=evidence.id,
                before=before_record.model_dump(mode="json") if before_record else None,
                after=evidence.model_dump(mode="json"),
            )
            return evidence

    def update_evidence_quality(
        self,
        evidence_id: str,
        quality_label: EvidenceQualityLabel,
        *,
        actor_id: str | None = None,
        note: str = "",
    ) -> EvidenceRecord | None:
        with self._lock:
            evidence = self.evidence_records.get(evidence_id)
            if evidence is None:
                return None
            before = evidence.model_dump(mode="json")
            evidence.quality_label = quality_label
            evidence.metadata["quality_note"] = note
            evidence.metadata["quality_reviewed_at"] = datetime.utcnow().isoformat()
            after = evidence.model_dump(mode="json")
            self._append_audit(
                workspace_id=evidence.workspace_id,
                actor_id=actor_id or DEFAULT_USER_ID,
                action="evidence.quality_updated",
                resource_type="evidence",
                resource_id=evidence.id,
                before=before,
                after=after,
            )
            return evidence

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

    def get_report_version(self, version_id: str) -> ReportVersionRecord | None:
        with self._lock:
            return self.report_versions.get(version_id)

    def upsert_report_version(self, version: ReportVersionRecord) -> ReportVersionRecord:
        with self._lock:
            before_record = self.report_versions.get(version.id)
            self.report_versions[version.id] = version
            self._append_audit(
                workspace_id=version.workspace_id,
                actor_id=DEFAULT_USER_ID,
                action="report_version.upserted",
                resource_type="report_version",
                resource_id=version.id,
                before=before_record.model_dump(mode="json") if before_record else None,
                after=version.model_dump(mode="json"),
            )
            return version

    def get_previous_report_version(
        self,
        version: ReportVersionRecord,
    ) -> ReportVersionRecord | None:
        with self._lock:
            candidates = [
                item
                for item in self.report_versions.values()
                if item.project_id == version.project_id
                and item.topic_normalized == version.topic_normalized
                and item.competitor_layer == version.competitor_layer
                and item.competitor_set_hash == version.competitor_set_hash
                and item.version_number < version.version_number
            ]
            if not candidates:
                return None
            return max(candidates, key=lambda item: (item.version_number, item.created_at))

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
        before: dict | None = None,
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
                before=before,
                after=after,
            )
        )

    def _append_audit_once(
        self,
        *,
        workspace_id: str,
        actor_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str,
        after: dict,
        before: dict | None = None,
    ) -> None:
        if self._audit_exists(action, resource_id, resource_type=resource_type):
            return
        self._append_audit(
            workspace_id=workspace_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
        )

    def _audit_exists(
        self,
        action: str,
        resource_id: str,
        *,
        resource_type: str | None = None,
    ) -> bool:
        return any(
            log.action == action
            and log.resource_id == resource_id
            and (resource_type is None or log.resource_type == resource_type)
            for log in self.audit_logs
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
