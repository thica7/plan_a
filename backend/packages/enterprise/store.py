from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol
from urllib.parse import urlparse

from packages.business_intel.source_reconciliation import merge_evidence_source_metadata
from packages.enterprise.embedding_index import (
    build_evidence_embedding_record,
    cosine_similarity,
    deterministic_embedding,
)
from packages.enterprise.report_lifecycle import report_transition_audit_after
from packages.enterprise.usage import (
    build_quota_decision,
    build_workspace_usage_summary,
    current_month_window,
)
from packages.identity import (
    compute_competitor_id,
    compute_competitor_set_hash,
    compute_project_id,
    compute_source_registry_id,
    compute_topic_normalized,
    normalize_key,
    normalize_url,
    stable_prefixed_id,
)
from packages.refs import audit_relationship_resource_id, sort_report_versions
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import (
    ArtifactRecord,
    AuditLogRecord,
    ClaimRecord,
    CompetitorRecord,
    EnterpriseRunProjection,
    EvidenceEmbeddingRecord,
    EvidenceQualityLabel,
    EvidenceRecord,
    EvidenceReindexResult,
    EvidenceSearchHit,
    MemoryCandidate,
    MonitorJobRecord,
    MonitorJobUpdateRequest,
    NotificationRecord,
    ProjectCompetitorLink,
    ProjectRecord,
    ReportVersionRecord,
    SchemaEvolutionReviewRecord,
    SourceRegistryRecord,
    UserFeedbackRecord,
    UserRecord,
    WorkspaceMemberRecord,
    WorkspaceQuotaDecision,
    WorkspaceQuotaUpdateRequest,
    WorkspaceRecord,
    WorkspaceUsageSummary,
)
from packages.sources import normalize_report_version_sources

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

    def list_workspace_members(
        self,
        workspace_id: str | None = None,
    ) -> list[WorkspaceMemberRecord]: ...

    def upsert_workspace_member(
        self,
        member: WorkspaceMemberRecord,
    ) -> WorkspaceMemberRecord: ...

    def get_workspace_member(
        self,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceMemberRecord | None: ...

    def update_workspace_quota(
        self,
        workspace_id: str,
        update: WorkspaceQuotaUpdateRequest,
        *,
        actor_id: str | None = None,
    ) -> WorkspaceRecord | None: ...

    def get_workspace_usage(
        self,
        workspace_id: str,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> WorkspaceUsageSummary: ...

    def check_workspace_quota(
        self,
        workspace_id: str,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> WorkspaceQuotaDecision: ...

    def list_notifications(
        self,
        workspace_id: str | None = None,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[NotificationRecord]: ...

    def upsert_notification(
        self,
        notification: NotificationRecord,
    ) -> NotificationRecord: ...

    def list_monitor_jobs(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[MonitorJobRecord]: ...

    def get_monitor_job(self, monitor_id: str) -> MonitorJobRecord | None: ...

    def upsert_monitor_job(
        self,
        job: MonitorJobRecord,
        *,
        actor_id: str | None = None,
    ) -> MonitorJobRecord: ...

    def update_monitor_job(
        self,
        monitor_id: str,
        update: MonitorJobUpdateRequest,
        *,
        actor_id: str | None = None,
    ) -> MonitorJobRecord | None: ...

    def record_monitor_job_run(
        self,
        monitor_id: str,
        *,
        status: str,
        workflow_id: str | None = None,
        run_id: str | None = None,
        report_version_id: str | None = None,
        error: str = "",
        actor_id: str | None = None,
    ) -> MonitorJobRecord | None: ...

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

    def upsert_evidence_batch(self, evidence: list[EvidenceRecord]) -> list[EvidenceRecord]: ...

    def list_evidence_embeddings(
        self,
        workspace_id: str | None = None,
    ) -> list[EvidenceEmbeddingRecord]: ...

    def reindex_evidence_embeddings(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> EvidenceReindexResult: ...

    def search_evidence(
        self,
        *,
        workspace_id: str,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[EvidenceSearchHit]: ...

    def list_artifacts(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        evidence_id: str | None = None,
        report_version_id: str | None = None,
    ) -> list[ArtifactRecord]: ...

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None: ...

    def upsert_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord: ...

    def list_source_registry(
        self,
        workspace_id: str | None = None,
    ) -> list[SourceRegistryRecord]: ...

    def upsert_source_registry(
        self,
        record: SourceRegistryRecord,
        *,
        actor_id: str | None = None,
    ) -> SourceRegistryRecord: ...

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

    def audit_report_version_transition(
        self,
        version: ReportVersionRecord,
        *,
        action: str,
        actor_id: str | None = None,
        before_status: str | None = None,
        note: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None: ...

    def record_memory_feedback_audit(
        self,
        feedback: UserFeedbackRecord,
        candidates: list[MemoryCandidate],
        *,
        actor_id: str | None = None,
    ) -> None: ...

    def audit_schema_evolution_review(
        self,
        project: ProjectRecord,
        review: SchemaEvolutionReviewRecord,
        *,
        actor_id: str | None = None,
    ) -> None: ...


class EnterpriseMemoryStore:
    """Phase 1 enterprise repository boundary, with Postgres-compatible semantics."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.workspaces: dict[str, WorkspaceRecord] = {}
        self.users: dict[str, UserRecord] = {}
        self.workspace_members: dict[tuple[str, str], WorkspaceMemberRecord] = {}
        self.notifications: dict[str, NotificationRecord] = {}
        self.monitor_jobs: dict[str, MonitorJobRecord] = {}
        self.run_details: dict[str, RunDetail] = {}
        self.projects: dict[str, ProjectRecord] = {}
        self.competitors: dict[str, CompetitorRecord] = {}
        self.project_competitors: dict[tuple[str, str], ProjectCompetitorLink] = {}
        self.evidence_records: dict[str, EvidenceRecord] = {}
        self.evidence_embeddings: dict[str, EvidenceEmbeddingRecord] = {}
        self.artifacts: dict[str, ArtifactRecord] = {}
        self.source_registry: dict[str, SourceRegistryRecord] = {}
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
            self.workspace_members.setdefault(
                (DEFAULT_WORKSPACE_ID, DEFAULT_USER_ID),
                WorkspaceMemberRecord(
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    user_id=DEFAULT_USER_ID,
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
            current_competitor_ids = set(competitor_ids)
            self.project_competitors = {
                key: link
                for key, link in self.project_competitors.items()
                if key[0] != project_id or key[1] in current_competitor_ids
            }
            for name, competitor_id in zip(detail.plan.competitors, competitor_ids, strict=False):
                competitor = self.competitors.get(competitor_id)
                if competitor is None:
                    self.competitors[competitor_id] = CompetitorRecord(
                        id=competitor_id,
                        workspace_id=workspace_id,
                        name=name,
                        normalized_name=normalize_key(name),
                        layer=detail.plan.competitor_layer,
                        homepage_url=detail.plan.homepage_hints.get(name),
                        metadata={
                            "scenario_id": detail.plan.scenario_id,
                            "qa_rule_ids": detail.plan.qa_rule_ids,
                            "homepage_verified": detail.plan.homepage_verified.get(name, False),
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
                    competitor.metadata["homepage_verified"] = detail.plan.homepage_verified.get(
                        name,
                        False,
                    )
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
                    resource_id=audit_relationship_resource_id(
                        "project-competitor",
                        project_id,
                        competitor_id,
                    ),
                    after={"project_id": project_id, "competitor_id": competitor_id},
                )
            self._run_contexts[detail.id] = context
            self.run_details[detail.id] = detail.model_copy(
                deep=True,
                update={
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                },
            )
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
                existing = self.evidence_records.get(evidence.id)
                merged_evidence = _merge_evidence_lifecycle(
                    existing,
                    evidence,
                )
                self.evidence_records[evidence.id] = merged_evidence
                self._upsert_evidence_embedding_locked(merged_evidence)
                self._upsert_source_registry_locked(
                    source_registry_from_evidence(merged_evidence),
                    actor_id=DEFAULT_USER_ID,
                    audit_once=True,
                )
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

    def list_workspace_members(
        self,
        workspace_id: str | None = None,
    ) -> list[WorkspaceMemberRecord]:
        with self._lock:
            records = list(self.workspace_members.values())
            if workspace_id:
                records = [item for item in records if item.workspace_id == workspace_id]
            return sorted(records, key=lambda item: (item.workspace_id, item.user_id))

    def upsert_workspace_member(
        self,
        member: WorkspaceMemberRecord,
    ) -> WorkspaceMemberRecord:
        with self._lock:
            self._ensure_workspace(member.workspace_id)
            self.workspace_members[(member.workspace_id, member.user_id)] = member
            self._append_audit(
                workspace_id=member.workspace_id,
                actor_id=DEFAULT_USER_ID,
                action="workspace_member.upserted",
                resource_type="workspace_member",
                resource_id=audit_relationship_resource_id(
                    "workspace-member",
                    member.workspace_id,
                    member.user_id,
                ),
                after=member.model_dump(mode="json"),
            )
            return member

    def get_workspace_member(
        self,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceMemberRecord | None:
        with self._lock:
            return self.workspace_members.get((workspace_id, user_id))

    def update_workspace_quota(
        self,
        workspace_id: str,
        update: WorkspaceQuotaUpdateRequest,
        *,
        actor_id: str | None = None,
    ) -> WorkspaceRecord | None:
        with self._lock:
            workspace = self.workspaces.get(workspace_id)
            if workspace is None:
                return None
            before = workspace.model_dump(mode="json")
            update_values = {
                key: value
                for key, value in update.model_dump(exclude_none=True).items()
                if value is not None
            }
            if update_values:
                workspace = workspace.model_copy(
                    update={**update_values, "updated_at": datetime.utcnow()}
                )
                self.workspaces[workspace_id] = workspace
                self._append_audit(
                    workspace_id=workspace_id,
                    actor_id=actor_id or DEFAULT_USER_ID,
                    action="workspace.quota_updated",
                    resource_type="workspace",
                    resource_id=workspace_id,
                    before=before,
                    after=workspace.model_dump(mode="json"),
                )
            return workspace

    def get_workspace_usage(
        self,
        workspace_id: str,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> WorkspaceUsageSummary:
        with self._lock:
            self._ensure_workspace(workspace_id)
            workspace = self.workspaces[workspace_id]
            period_start, period_end = _usage_period(period_start, period_end)
            runs = [
                detail
                for detail in self.run_details.values()
                if detail.workspace_id == workspace_id
                and period_start <= detail.created_at < period_end
            ]
            return build_workspace_usage_summary(
                workspace,
                period_start=period_start,
                period_end=period_end,
                run_count=len(runs),
                completed_run_count=sum(1 for item in runs if item.status == "completed"),
                failed_run_count=sum(1 for item in runs if item.status == "failed"),
                interrupted_run_count=sum(1 for item in runs if item.status == "interrupted"),
                input_tokens_estimate=sum(item.metrics.input_tokens_estimate for item in runs),
                output_tokens_estimate=sum(item.metrics.output_tokens_estimate for item in runs),
                cost_estimate_usd=sum(item.metrics.cost_estimate_usd for item in runs),
            )

    def check_workspace_quota(
        self,
        workspace_id: str,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> WorkspaceQuotaDecision:
        usage = self.get_workspace_usage(
            workspace_id,
            period_start=period_start,
            period_end=period_end,
        )
        workspace = self.workspaces[workspace_id]
        return build_quota_decision(usage, workspace.quota_enforcement)

    def list_notifications(
        self,
        workspace_id: str | None = None,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[NotificationRecord]:
        with self._lock:
            records = list(self.notifications.values())
            if workspace_id:
                records = [item for item in records if item.workspace_id == workspace_id]
            if status:
                records = [item for item in records if item.status == status]
            records = sorted(records, key=lambda item: item.created_at, reverse=True)
            return records[: max(1, limit)]

    def upsert_notification(
        self,
        notification: NotificationRecord,
    ) -> NotificationRecord:
        with self._lock:
            self._ensure_workspace(notification.workspace_id)
            before_record = self.notifications.get(notification.id)
            self.notifications[notification.id] = notification
            self._append_audit(
                workspace_id=notification.workspace_id,
                actor_id=notification.created_by or DEFAULT_USER_ID,
                action="notification.upserted",
                resource_type="notification",
                resource_id=notification.id,
                before=before_record.model_dump(mode="json") if before_record else None,
                after=notification.model_dump(mode="json"),
            )
            return notification

    def list_monitor_jobs(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[MonitorJobRecord]:
        with self._lock:
            records = list(self.monitor_jobs.values())
            if workspace_id:
                records = [item for item in records if item.workspace_id == workspace_id]
            if project_id:
                records = [item for item in records if item.project_id == project_id]
            if status:
                records = [item for item in records if item.status == status]
            return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def get_monitor_job(self, monitor_id: str) -> MonitorJobRecord | None:
        with self._lock:
            job = self.monitor_jobs.get(monitor_id)
            return job.model_copy(deep=True) if job is not None else None

    def upsert_monitor_job(
        self,
        job: MonitorJobRecord,
        *,
        actor_id: str | None = None,
    ) -> MonitorJobRecord:
        with self._lock:
            self._ensure_workspace(job.workspace_id)
            before = self.monitor_jobs.get(job.id)
            stored = job.model_copy(update={"updated_at": datetime.utcnow()})
            self.monitor_jobs[job.id] = stored
            self._append_audit(
                workspace_id=stored.workspace_id,
                actor_id=actor_id or DEFAULT_USER_ID,
                action="monitor_job.upserted",
                resource_type="monitor_job",
                resource_id=stored.id,
                before=before.model_dump(mode="json") if before else None,
                after=stored.model_dump(mode="json"),
            )
            return stored

    def update_monitor_job(
        self,
        monitor_id: str,
        update: MonitorJobUpdateRequest,
        *,
        actor_id: str | None = None,
    ) -> MonitorJobRecord | None:
        with self._lock:
            current = self.monitor_jobs.get(monitor_id)
            if current is None:
                return None
            update_values = update.model_dump(exclude_none=True)
            if "metadata" in update_values:
                update_values["metadata"] = {
                    **current.metadata,
                    **dict(update_values["metadata"]),
                }
            updated = current.model_copy(
                update={**update_values, "updated_at": datetime.utcnow()}
            )
            self.monitor_jobs[monitor_id] = updated
            self._append_audit(
                workspace_id=updated.workspace_id,
                actor_id=actor_id or DEFAULT_USER_ID,
                action="monitor_job.updated",
                resource_type="monitor_job",
                resource_id=updated.id,
                before=current.model_dump(mode="json"),
                after=updated.model_dump(mode="json"),
            )
            return updated

    def record_monitor_job_run(
        self,
        monitor_id: str,
        *,
        status: str,
        workflow_id: str | None = None,
        run_id: str | None = None,
        report_version_id: str | None = None,
        error: str = "",
        actor_id: str | None = None,
    ) -> MonitorJobRecord | None:
        with self._lock:
            current = self.monitor_jobs.get(monitor_id)
            if current is None:
                return None
            now = datetime.utcnow()
            completed_at = now if status in {"completed", "failed"} else current.last_completed_at
            updated = current.model_copy(
                update={
                    "last_status": status,
                    "last_workflow_id": workflow_id or current.last_workflow_id,
                    "last_run_id": run_id or current.last_run_id,
                    "last_report_version_id": report_version_id
                    or current.last_report_version_id,
                    "last_error": error,
                    "last_started_at": now if status == "running" else current.last_started_at,
                    "last_completed_at": completed_at,
                    "updated_at": now,
                }
            )
            self.monitor_jobs[monitor_id] = updated
            self._append_audit(
                workspace_id=updated.workspace_id,
                actor_id=actor_id or DEFAULT_USER_ID,
                action="monitor_job.run_recorded",
                resource_type="monitor_job",
                resource_id=updated.id,
                before=current.model_dump(mode="json"),
                after={
                    "status": status,
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "report_version_id": report_version_id,
                    "error": error,
                },
            )
            return updated

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

    def audit_schema_evolution_review(
        self,
        project: ProjectRecord,
        review: SchemaEvolutionReviewRecord,
        *,
        actor_id: str | None = None,
    ) -> None:
        with self._lock:
            self._append_audit(
                workspace_id=project.workspace_id,
                actor_id=actor_id or review.reviewed_by,
                action="schema_evolution.reviewed",
                resource_type="schema_evolution_suggestion",
                resource_id=audit_relationship_resource_id(
                    "schema-evolution-suggestion",
                    project.id,
                    review.suggestion_id,
                ),
                after={
                    "project_id": project.id,
                    "suggestion_id": review.suggestion_id,
                    "decision": review.decision,
                    "dimension": review.dimension,
                    "normalized_dimension": review.normalized_dimension,
                    "source_gap_ids": review.source_gap_ids,
                    "note": review.note,
                },
            )

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
                linked_ids = self._report_linked_evidence_ids_locked(project_id)
                records = [
                    item
                    for item in records
                    if item.project_id == project_id or item.id in linked_ids
                ]
            return sorted(records, key=lambda item: item.captured_at, reverse=True)

    def upsert_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        with self._lock:
            return self._upsert_evidence_locked(evidence)

    def upsert_evidence_batch(self, evidence: list[EvidenceRecord]) -> list[EvidenceRecord]:
        with self._lock:
            return [self._upsert_evidence_locked(item) for item in evidence]

    def list_evidence_embeddings(
        self,
        workspace_id: str | None = None,
    ) -> list[EvidenceEmbeddingRecord]:
        with self._lock:
            records = list(self.evidence_embeddings.values())
            if workspace_id:
                records = [item for item in records if item.workspace_id == workspace_id]
            return sorted(records, key=lambda item: (item.workspace_id, item.evidence_id))

    def reindex_evidence_embeddings(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> EvidenceReindexResult:
        with self._lock:
            evidence = list(self.evidence_records.values())
            if workspace_id:
                evidence = [item for item in evidence if item.workspace_id == workspace_id]
            if project_id:
                evidence = [item for item in evidence if item.project_id == project_id]
            target_ids = {item.id for item in evidence}
            self.evidence_embeddings = {
                key: value
                for key, value in self.evidence_embeddings.items()
                if value.evidence_id not in target_ids
            }
            indexed_count = 0
            duplicate_count = 0
            for item in evidence:
                item, duplicate_of = self._apply_embedding_dedupe_locked(item)
                self.evidence_records[item.id] = item
                if duplicate_of is None:
                    self._upsert_evidence_embedding_locked(item)
                    indexed_count += 1
                else:
                    duplicate_count += 1
            return EvidenceReindexResult(
                indexed_count=indexed_count,
                duplicate_count=duplicate_count,
            )

    def search_evidence(
        self,
        *,
        workspace_id: str,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[EvidenceSearchHit]:
        with self._lock:
            query_vector = deterministic_embedding(query)
            hits: list[EvidenceSearchHit] = []
            for embedding in self.evidence_embeddings.values():
                if embedding.workspace_id != workspace_id:
                    continue
                evidence = self.evidence_records.get(embedding.evidence_id)
                if evidence is None:
                    continue
                if project_id and evidence.project_id != project_id:
                    continue
                score = cosine_similarity(
                    query_vector,
                    deterministic_embedding(embedding.embedding_text),
                )
                hits.append(
                    EvidenceSearchHit(
                        evidence=evidence,
                        score=score,
                        embedding_model=embedding.embedding_model,
                    )
                )
            return sorted(hits, key=lambda item: item.score, reverse=True)[: max(1, limit)]

    def list_artifacts(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        evidence_id: str | None = None,
        report_version_id: str | None = None,
    ) -> list[ArtifactRecord]:
        with self._lock:
            records = list(self.artifacts.values())
            if workspace_id:
                records = [item for item in records if item.workspace_id == workspace_id]
            if project_id:
                records = [item for item in records if item.project_id == project_id]
            if evidence_id:
                records = [item for item in records if item.evidence_id == evidence_id]
            if report_version_id:
                records = [item for item in records if item.report_version_id == report_version_id]
            return sorted(records, key=lambda item: item.created_at, reverse=True)

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        with self._lock:
            return self.artifacts.get(artifact_id)

    def upsert_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._lock:
            self._ensure_workspace(artifact.workspace_id)
            before_record = self.artifacts.get(artifact.id)
            self.artifacts[artifact.id] = artifact
            self._append_audit(
                workspace_id=artifact.workspace_id,
                actor_id=artifact.created_by or DEFAULT_USER_ID,
                action="artifact.upserted",
                resource_type="artifact",
                resource_id=artifact.id,
                before=before_record.model_dump(mode="json") if before_record else None,
                after=artifact.model_dump(mode="json"),
            )
            return artifact

    def list_source_registry(
        self,
        workspace_id: str | None = None,
    ) -> list[SourceRegistryRecord]:
        with self._lock:
            records = list(self.source_registry.values())
            if workspace_id:
                records = [item for item in records if item.workspace_id == workspace_id]
            return sorted(records, key=lambda item: (item.domain, item.source_type))

    def upsert_source_registry(
        self,
        record: SourceRegistryRecord,
        *,
        actor_id: str | None = None,
    ) -> SourceRegistryRecord:
        with self._lock:
            self._ensure_workspace(record.workspace_id)
            return self._upsert_source_registry_locked(
                record,
                actor_id=actor_id or DEFAULT_USER_ID,
                audit_once=False,
            )

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
                linked_ids = self._report_linked_claim_ids_locked(project_id)
                records = [
                    item
                    for item in records
                    if item.project_id == project_id or item.id in linked_ids
                ]
            return sorted(records, key=lambda item: item.created_at, reverse=True)

    def list_report_versions(self, project_id: str | None = None) -> list[ReportVersionRecord]:
        with self._lock:
            records = list(self.report_versions.values())
            if project_id:
                records = [item for item in records if item.project_id == project_id]
            return sort_report_versions(records)

    def get_report_version(self, version_id: str) -> ReportVersionRecord | None:
        with self._lock:
            return self.report_versions.get(version_id)

    def upsert_report_version(self, version: ReportVersionRecord) -> ReportVersionRecord:
        with self._lock:
            version = normalize_report_version_sources(
                version,
                self._report_scope_evidence_locked(version),
            )
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
            if before_record is not None and before_record.status != version.status:
                self._append_audit(
                    workspace_id=version.workspace_id,
                    actor_id=DEFAULT_USER_ID,
                    action="report_version.status_changed",
                    resource_type="report_version",
                    resource_id=version.id,
                    before={"status": before_record.status},
                    after={
                        "status": version.status,
                        "project_id": version.project_id,
                        "version_number": version.version_number,
                    },
                )
            return version

    def audit_report_version_transition(
        self,
        version: ReportVersionRecord,
        *,
        action: str,
        actor_id: str | None = None,
        before_status: str | None = None,
        note: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            after = report_transition_audit_after(
                version,
                transition=action,
                actor_id=actor_id,
                note=note,
                gate=None,
            )
            if metadata:
                after.update(metadata)
            self._append_audit(
                workspace_id=version.workspace_id,
                actor_id=actor_id or DEFAULT_USER_ID,
                action=action,
                resource_type="report_version",
                resource_id=version.id,
                before={"status": before_status} if before_status else None,
                after=after,
            )

    def _report_linked_evidence_ids_locked(self, project_id: str) -> set[str]:
        return {
            evidence_id
            for version in self.report_versions.values()
            if version.project_id == project_id
            for evidence_id in version.evidence_ids
        }

    def _report_linked_claim_ids_locked(self, project_id: str) -> set[str]:
        return {
            claim_id
            for version in self.report_versions.values()
            if version.project_id == project_id
            for claim_id in version.claim_ids
        }

    def _report_scope_evidence_locked(
        self,
        version: ReportVersionRecord,
    ) -> list[EvidenceRecord]:
        scoped_ids = set(version.evidence_ids)
        return [
            item
            for item in self.evidence_records.values()
            if item.project_id == version.project_id or item.id in scoped_ids
        ]

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

    def record_memory_feedback_audit(
        self,
        feedback: UserFeedbackRecord,
        candidates: list[MemoryCandidate],
        *,
        actor_id: str | None = None,
    ) -> None:
        with self._lock:
            self._append_audit(
                workspace_id=feedback.workspace_id,
                actor_id=actor_id or feedback.user_id or DEFAULT_USER_ID,
                action="memory.feedback_captured",
                resource_type="memory_feedback",
                resource_id=feedback.id,
                after=_memory_feedback_audit_after(feedback, candidates),
            )

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
        self.workspace_members.setdefault(
            (workspace_id, DEFAULT_USER_ID),
            WorkspaceMemberRecord(
                workspace_id=workspace_id,
                user_id=DEFAULT_USER_ID,
                role="owner",
            ),
        )

    def _upsert_evidence_locked(self, evidence: EvidenceRecord) -> EvidenceRecord:
        before_record = self.evidence_records.get(evidence.id)
        evidence = _merge_evidence_lifecycle(before_record, evidence)
        evidence, duplicate_of = self._apply_embedding_dedupe_locked(evidence)
        self.evidence_records[evidence.id] = evidence
        if duplicate_of is None:
            self._upsert_evidence_embedding_locked(evidence)
        else:
            self._delete_evidence_embedding_locked(evidence.id)
        self._upsert_source_registry_locked(
            source_registry_from_evidence(evidence),
            actor_id=DEFAULT_USER_ID,
            audit_once=True,
        )
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

    def _upsert_evidence_embedding_locked(
        self,
        evidence: EvidenceRecord,
    ) -> EvidenceEmbeddingRecord:
        record = build_evidence_embedding_record(evidence)
        existing = self.evidence_embeddings.get(record.id)
        if existing is not None:
            record = record.model_copy(update={"created_at": existing.created_at})
        self.evidence_embeddings[record.id] = record
        return record

    def _delete_evidence_embedding_locked(self, evidence_id: str) -> None:
        self.evidence_embeddings = {
            key: value
            for key, value in self.evidence_embeddings.items()
            if value.evidence_id != evidence_id
        }

    def _apply_embedding_dedupe_locked(
        self,
        evidence: EvidenceRecord,
    ) -> tuple[EvidenceRecord, str | None]:
        duplicate = self._find_embedding_duplicate_locked(evidence)
        metadata = dict(evidence.metadata)
        if duplicate is None:
            metadata.pop("embedding_duplicate_of", None)
            metadata.pop("embedding_dedupe_key", None)
            metadata.pop("embedding_dedupe_strategy", None)
            metadata["embedding_indexed"] = True
            return evidence.model_copy(update={"metadata": metadata}), None
        canonical, dedupe_key = duplicate
        metadata["embedding_duplicate_of"] = canonical.id
        metadata["embedding_dedupe_key"] = dedupe_key
        metadata["embedding_dedupe_strategy"] = _embedding_dedupe_strategy(dedupe_key)
        metadata["embedding_indexed"] = False
        self._record_embedding_duplicate_locked(canonical.id, evidence.id)
        return evidence.model_copy(update={"metadata": metadata}), canonical.id

    def _find_embedding_duplicate_locked(
        self,
        evidence: EvidenceRecord,
    ) -> tuple[EvidenceRecord, str] | None:
        keys = _embedding_dedupe_keys(evidence)
        if not keys:
            return None
        candidates = [
            item
            for item in self.evidence_records.values()
            if set(_embedding_dedupe_keys(item)) & set(keys)
        ]
        if not candidates:
            return None
        canonical = sorted(
            [*candidates, evidence],
            key=lambda item: (item.captured_at, item.id),
        )[0]
        if canonical.id == evidence.id:
            return None
        matching_keys = sorted(set(_embedding_dedupe_keys(canonical)) & set(keys))
        if not matching_keys:
            return None
        return canonical, matching_keys[0]

    def _record_embedding_duplicate_locked(
        self,
        canonical_id: str,
        duplicate_id: str,
    ) -> None:
        if canonical_id == duplicate_id:
            return
        canonical = self.evidence_records.get(canonical_id)
        if canonical is None:
            return
        metadata = dict(canonical.metadata)
        existing = metadata.get("embedding_duplicate_ids", [])
        duplicate_ids = [
            item for item in existing if isinstance(item, str) and item != duplicate_id
        ]
        duplicate_ids.append(duplicate_id)
        metadata["embedding_duplicate_ids"] = sorted(duplicate_ids)
        metadata["embedding_duplicate_count"] = len(duplicate_ids)
        self.evidence_records[canonical_id] = canonical.model_copy(update={"metadata": metadata})

    def _upsert_source_registry_locked(
        self,
        record: SourceRegistryRecord,
        *,
        actor_id: str | None,
        audit_once: bool,
    ) -> SourceRegistryRecord:
        existing_id = self._source_registry_id_by_natural_key(record)
        before_record = self.source_registry.get(existing_id or record.id)
        merged = _merge_source_registry(before_record, record)
        self.source_registry[merged.id] = merged
        append_audit = self._append_audit_once if audit_once else self._append_audit
        append_audit(
            workspace_id=merged.workspace_id,
            actor_id=actor_id,
            action="source_registry.upserted",
            resource_type="source_registry",
            resource_id=merged.id,
            before=before_record.model_dump(mode="json") if before_record else None,
            after=merged.model_dump(mode="json"),
        )
        return merged

    def _source_registry_id_by_natural_key(
        self,
        record: SourceRegistryRecord,
    ) -> str | None:
        for item in self.source_registry.values():
            if (
                item.workspace_id == record.workspace_id
                and item.domain == record.domain
                and item.source_type == record.source_type
            ):
                return item.id
        return None

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
                id=stable_prefixed_id("audit", len(self.audit_logs) + 1, length=12),
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
        return compute_competitor_id(workspace_id, name)

    def _project_id(self, workspace_id: str, topic: str, competitor_ids: list[str]) -> str:
        return compute_project_id(workspace_id, topic, competitor_ids)


def _memory_feedback_audit_after(
    feedback: UserFeedbackRecord,
    candidates: list[MemoryCandidate],
) -> dict[str, object]:
    return {
        "feedback_id": feedback.id,
        "feedback_type": feedback.feedback_type,
        "project_id": feedback.project_id,
        "run_id": feedback.run_id,
        "report_version_id": feedback.report_version_id,
        "target_type": feedback.target_type,
        "target_id": feedback.target_id,
        "candidate_ids": [candidate.id for candidate in candidates],
        "candidate_count": len(candidates),
        "candidate_kinds": sorted({candidate.kind for candidate in candidates}),
        "candidate_statuses": sorted({candidate.status for candidate in candidates}),
        "tags": feedback.tags,
        "redaction_counts": feedback.redaction_counts,
        "message_excerpt": feedback.message[:240],
    }


def _title_from_id(value: str) -> str:
    return value.replace("-", " ").strip().title() or value


def _usage_period(
    period_start: datetime | None,
    period_end: datetime | None,
) -> tuple[datetime, datetime]:
    default_start, default_end = current_month_window()
    return period_start or default_start, period_end or default_end


def _merge_evidence_lifecycle(
    existing: EvidenceRecord | None,
    incoming: EvidenceRecord,
) -> EvidenceRecord:
    current_run_id = incoming.last_seen_run_id or incoming.run_id
    metadata = merge_evidence_source_metadata(existing, incoming)
    if existing is None:
        return incoming.model_copy(
            update={
                "first_seen_run_id": incoming.first_seen_run_id or incoming.run_id,
                "last_seen_run_id": current_run_id,
                "seen_count": max(1, incoming.seen_count),
                "metadata": metadata,
            }
        )

    increment = 1 if current_run_id and current_run_id != existing.last_seen_run_id else 0
    return incoming.model_copy(
        update={
            "run_id": existing.run_id or incoming.run_id,
            "first_seen_run_id": existing.first_seen_run_id
            or existing.run_id
            or incoming.first_seen_run_id
            or incoming.run_id,
            "last_seen_run_id": current_run_id or existing.last_seen_run_id,
            "seen_count": max(1, existing.seen_count + increment),
            "metadata": metadata,
        }
    )


def _embedding_dedupe_key(evidence: EvidenceRecord) -> str:
    if not evidence.content_hash:
        return ""
    parts = [
        evidence.workspace_id,
        evidence.project_id,
        evidence.competitor_id.casefold().strip(),
        evidence.dimension.casefold().strip(),
        evidence.content_hash.casefold().strip(),
    ]
    return "|".join(parts)


def _embedding_dedupe_keys(evidence: EvidenceRecord) -> list[str]:
    keys = []
    content_key = _embedding_dedupe_key(evidence)
    if content_key:
        keys.append(f"content_hash|{content_key}")
    url = _evidence_dedupe_url(evidence)
    if url:
        keys.append(
            "|".join(
                [
                    "canonical_url",
                    evidence.workspace_id,
                    evidence.project_id,
                    evidence.competitor_id.casefold().strip(),
                    evidence.dimension.casefold().strip(),
                    url,
                ]
            )
        )
    return keys


def _evidence_dedupe_url(evidence: EvidenceRecord) -> str:
    return normalize_url(evidence.canonical_url or str(evidence.url or ""))


def _embedding_dedupe_strategy(dedupe_key: str) -> str:
    if dedupe_key.startswith("canonical_url|"):
        return "canonical_url"
    return "content_hash"


def source_registry_id(workspace_id: str, domain: str, source_type: str) -> str:
    return compute_source_registry_id(workspace_id, domain, source_type)


def source_registry_from_evidence(evidence: EvidenceRecord) -> SourceRegistryRecord:
    domain, homepage_url = _source_location(evidence)
    source_type = evidence.source_type or "unknown"
    first_seen_run_id = evidence.first_seen_run_id or evidence.run_id
    last_seen_run_id = evidence.last_seen_run_id or evidence.run_id
    return SourceRegistryRecord(
        id=source_registry_id(evidence.workspace_id, domain, source_type),
        workspace_id=evidence.workspace_id,
        domain=domain,
        source_type=source_type,
        display_name=_title_from_id(domain),
        homepage_url=homepage_url,
        trust_level=_source_trust_level(evidence),
        robots_status=_source_robots_status(evidence),
        policy_review_status=_source_policy_review_status(evidence),
        policy_review_reason=_source_policy_review_reason(evidence),
        first_seen_run_id=first_seen_run_id,
        last_seen_run_id=last_seen_run_id,
        first_seen_at=evidence.captured_at,
        last_seen_at=evidence.captured_at,
        seen_count=max(1, evidence.seen_count),
        metadata={
            "last_evidence_id": evidence.id,
            "last_project_id": evidence.project_id,
            "last_dimension": evidence.dimension,
        },
    )


def _source_location(evidence: EvidenceRecord) -> tuple[str, str | None]:
    url_value = evidence.canonical_url or (str(evidence.url) if evidence.url else "")
    parsed = urlparse(url_value)
    host = parsed.hostname or ""
    if host:
        domain = host.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
        return domain, f"{scheme}://{domain}"
    return normalize_key(evidence.source_type or "unknown"), None


def _source_trust_level(evidence: EvidenceRecord) -> str:
    source_type = evidence.source_type.casefold()
    if source_type in {
        "official",
        "official_site",
        "official_docs",
        "official_pricing",
        "official_api",
        "trust_center",
    }:
        return "official"
    if source_type in {"webpage_verified", "verified_webpage", "verified_document"}:
        return "verified"
    if source_type in {
        "survey_response",
        "interview_record",
        "manual_transcript",
        "manual_note",
        "manual",
    } and bool(evidence.metadata.get("imported_user_research")):
        return "verified"
    if source_type in {
        "synthetic",
        "synthesized",
        "survey_simulated",
        "survey_response",
        "interview_record",
        "manual_transcript",
        "manual_note",
    }:
        return "synthetic"
    if evidence.url or evidence.canonical_url:
        return "community"
    return "unknown"


def _source_robots_status(evidence: EvidenceRecord) -> str:
    status = str(evidence.metadata.get("robots_status") or "unknown").casefold()
    if status in {"allowed", "blocked", "error"}:
        return status
    source_type = evidence.source_type.casefold()
    if "robots" in source_type and "blocked" in source_type:
        return "blocked"
    if status == "unknown":
        return "unknown"
    return "unknown"


def _source_policy_review_status(evidence: EvidenceRecord) -> str:
    status = str(
        evidence.metadata.get("policy_review_status")
        or evidence.metadata.get("source_policy_review_status")
        or ""
    ).casefold()
    if status in {"not_required", "pending", "approved", "rejected"}:
        return status
    robots_status = _source_robots_status(evidence)
    if robots_status in {"blocked", "error"}:
        return "pending"
    if bool(evidence.metadata.get("source_policy_review_required")):
        return "pending"
    return "not_required"


def _source_policy_review_reason(evidence: EvidenceRecord) -> str:
    reason = (
        evidence.metadata.get("policy_review_reason")
        or evidence.metadata.get("source_policy_review_reason")
        or ""
    )
    if reason:
        return str(reason)
    robots_status = _source_robots_status(evidence)
    if robots_status in {"blocked", "error"}:
        return f"Robots/source policy status is {robots_status}."
    if bool(evidence.metadata.get("source_policy_review_required")):
        return "Source policy requires human review."
    return ""


def _merge_source_registry(
    existing: SourceRegistryRecord | None,
    incoming: SourceRegistryRecord,
) -> SourceRegistryRecord:
    if existing is None:
        return incoming

    run_increment = (
        1
        if incoming.last_seen_run_id and incoming.last_seen_run_id != existing.last_seen_run_id
        else 0
    )
    return incoming.model_copy(
        update={
            "id": existing.id,
            "trust_level": _stronger_trust_level(existing.trust_level, incoming.trust_level),
            "robots_status": incoming.robots_status
            if incoming.robots_status != "unknown"
            else existing.robots_status,
            "policy_review_status": incoming.policy_review_status
            if incoming.policy_review_status != "not_required"
            else existing.policy_review_status,
            "policy_review_reason": incoming.policy_review_reason or existing.policy_review_reason,
            "is_active": existing.is_active,
            "first_seen_run_id": existing.first_seen_run_id or incoming.first_seen_run_id,
            "first_seen_at": min(existing.first_seen_at, incoming.first_seen_at),
            "last_seen_at": max(existing.last_seen_at, incoming.last_seen_at),
            "seen_count": max(existing.seen_count + run_increment, incoming.seen_count),
            "metadata": {**existing.metadata, **incoming.metadata},
        }
    )


def _stronger_trust_level(left: str, right: str) -> str:
    rank = {
        "unknown": 0,
        "synthetic": 1,
        "community": 2,
        "verified": 3,
        "official": 4,
    }
    return left if rank.get(left, 0) >= rank.get(right, 0) else right
