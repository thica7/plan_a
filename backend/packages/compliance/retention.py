from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

RetentionResourceType = Literal["project", "evidence", "artifact", "report_version", "audit_log"]


class RetentionStore(Protocol):
    def list_projects(self, workspace_id: str | None = None) -> list[object]: ...

    def list_evidence(self, project_id: str | None = None) -> list[object]: ...

    def list_artifacts(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[object]: ...

    def list_report_versions(self, project_id: str | None = None) -> list[object]: ...

    def list_audit_logs(self, workspace_id: str | None = None) -> list[object]: ...


class DataRetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_days: int = Field(default=1095, ge=1)
    evidence_days: int = Field(default=730, ge=1)
    artifact_days: int = Field(default=730, ge=1)
    report_version_days: int = Field(default=1095, ge=1)
    audit_log_days: int = Field(default=2555, ge=1)
    expiring_soon_days: int = Field(default=30, ge=1)
    physical_delete_enabled: bool = False


class RetentionBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: RetentionResourceType
    retention_days: int = Field(ge=1)
    total_count: int = Field(ge=0)
    expired_count: int = Field(ge=0)
    expiring_soon_count: int = Field(ge=0)
    oldest_created_at: datetime | None = None
    next_expiry_at: datetime | None = None


class DataRetentionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    status: Literal["pass", "warn", "fail"]
    policy: DataRetentionPolicy
    bucket_count: int = Field(ge=0)
    total_record_count: int = Field(ge=0)
    expired_count: int = Field(ge=0)
    expiring_soon_count: int = Field(ge=0)
    physical_delete_enabled: bool = False
    recommendations: list[str] = Field(default_factory=list)
    buckets: list[RetentionBucket]
    generated_at: datetime = Field(default_factory=datetime.utcnow)


def retention_policy_from_settings(settings: object) -> DataRetentionPolicy:
    return DataRetentionPolicy(
        project_days=_positive_int(settings, "retention_project_days", 1095),
        evidence_days=_positive_int(settings, "retention_evidence_days", 730),
        artifact_days=_positive_int(settings, "retention_artifact_days", 730),
        report_version_days=_positive_int(settings, "retention_report_version_days", 1095),
        audit_log_days=_positive_int(settings, "retention_audit_log_days", 2555),
        expiring_soon_days=_positive_int(settings, "retention_expiring_soon_days", 30),
        physical_delete_enabled=bool(getattr(settings, "retention_physical_delete_enabled", False)),
    )


def build_data_retention_report(
    *,
    store: RetentionStore,
    workspace_id: str,
    settings: object,
    as_of: datetime | None = None,
) -> DataRetentionReport:
    policy = retention_policy_from_settings(settings)
    now = as_of or datetime.utcnow()
    projects = store.list_projects(workspace_id=workspace_id)
    project_ids = [str(project.id) for project in projects]
    evidence = [
        item
        for project_id in project_ids
        for item in store.list_evidence(project_id=project_id)
    ]
    artifacts = store.list_artifacts(workspace_id=workspace_id)
    report_versions = [
        item
        for project_id in project_ids
        for item in store.list_report_versions(project_id=project_id)
    ]
    audit_logs = store.list_audit_logs(workspace_id=workspace_id)
    buckets = [
        _bucket("project", projects, "created_at", policy.project_days, policy, now),
        _bucket("evidence", evidence, "captured_at", policy.evidence_days, policy, now),
        _bucket("artifact", artifacts, "created_at", policy.artifact_days, policy, now),
        _bucket(
            "report_version",
            report_versions,
            "created_at",
            policy.report_version_days,
            policy,
            now,
        ),
        _bucket("audit_log", audit_logs, "created_at", policy.audit_log_days, policy, now),
    ]
    expired_count = sum(item.expired_count for item in buckets)
    expiring_soon_count = sum(item.expiring_soon_count for item in buckets)
    if expired_count:
        status = "fail"
    elif expiring_soon_count:
        status = "warn"
    else:
        status = "pass"
    return DataRetentionReport(
        workspace_id=workspace_id,
        status=status,
        policy=policy,
        bucket_count=len(buckets),
        total_record_count=sum(item.total_count for item in buckets),
        expired_count=expired_count,
        expiring_soon_count=expiring_soon_count,
        physical_delete_enabled=policy.physical_delete_enabled,
        recommendations=_recommendations(expired_count, expiring_soon_count, policy),
        buckets=buckets,
    )


def _bucket(
    resource_type: RetentionResourceType,
    records: list[object],
    field_name: str,
    retention_days: int,
    policy: DataRetentionPolicy,
    as_of: datetime,
) -> RetentionBucket:
    created_values = [
        value for item in records if (value := _datetime_field(item, field_name)) is not None
    ]
    expiry_values = [value + timedelta(days=retention_days) for value in created_values]
    soon_cutoff = as_of + timedelta(days=policy.expiring_soon_days)
    expired_count = sum(1 for expiry in expiry_values if expiry <= as_of)
    expiring_soon_count = sum(1 for expiry in expiry_values if as_of < expiry <= soon_cutoff)
    return RetentionBucket(
        resource_type=resource_type,
        retention_days=retention_days,
        total_count=len(records),
        expired_count=expired_count,
        expiring_soon_count=expiring_soon_count,
        oldest_created_at=min(created_values) if created_values else None,
        next_expiry_at=min((expiry for expiry in expiry_values if expiry > as_of), default=None),
    )


def _datetime_field(item: object, field_name: str) -> datetime | None:
    value = getattr(item, field_name, None)
    return value if isinstance(value, datetime) else None


def _positive_int(settings: object, name: str, default: int) -> int:
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
    return max(1, value)


def _recommendations(
    expired_count: int,
    expiring_soon_count: int,
    policy: DataRetentionPolicy,
) -> list[str]:
    recommendations: list[str] = []
    if expired_count:
        recommendations.append(
            "Review expired records and approve archive or erasure through an audited workflow."
        )
    if expiring_soon_count:
        recommendations.append(
            "Schedule owner review for records that will reach retention limits soon."
        )
    if not policy.physical_delete_enabled:
        recommendations.append(
            "Physical deletion is disabled; retention enforcement is report-only."
        )
    return recommendations
