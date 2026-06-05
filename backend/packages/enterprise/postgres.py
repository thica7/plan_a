from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from packages.enterprise.embedding_index import (
    build_evidence_embedding_record,
    deterministic_embedding,
    vector_literal,
)
from packages.enterprise.postgres_sanitizer import sanitize_postgres_text, sanitize_postgres_value
from packages.enterprise.store import (
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_ID,
    EnterpriseRunContext,
    _memory_feedback_audit_after,
    _title_from_id,
    source_registry_from_evidence,
)
from packages.enterprise.usage import (
    build_quota_decision,
    build_workspace_usage_summary,
    current_month_window,
)
from packages.identity import (
    compute_competitor_id,
    compute_competitor_set_hash,
    compute_project_id,
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
    NotificationRecord,
    ProjectRecord,
    ReportVersionRecord,
    SchemaEvolutionReviewRecord,
    SourceRegistryRecord,
    UserFeedbackRecord,
    WorkspaceMemberRecord,
    WorkspaceQuotaDecision,
    WorkspaceQuotaUpdateRequest,
    WorkspaceRecord,
    WorkspaceUsageSummary,
)
from packages.sources import normalize_report_version_sources


class EnterprisePostgresStore:
    """Postgres-backed enterprise repository for Workspace/Project/Evidence projections."""

    def __init__(self, database_url: str, *, auto_migrate: bool = True) -> None:
        if not database_url:
            raise ValueError("ENTERPRISE_DATABASE_URL is required for postgres enterprise store.")
        try:
            from psycopg import connect
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for ENTERPRISE_STORE_BACKEND=postgres. "
                "Install backend dependencies with `pip install -e .`."
            ) from exc
        self.database_url = database_url
        self._connect_driver = connect
        self._dict_row = dict_row
        self._jsonb = Jsonb
        if auto_migrate:
            self.migrate()

    @contextmanager
    def _connect(
        self,
        *args: Any,
        service_role: bool = True,
        workspace_id: str | None = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        with self._connect_driver(*args, **kwargs) as conn:
            self._apply_rls_context(
                conn,
                workspace_id=workspace_id,
                service_role=service_role,
            )
            yield conn

    @contextmanager
    def _service_connection(self) -> Iterator[Any]:
        with self._connect(
            self.database_url,
            row_factory=self._dict_row,
            service_role=True,
        ) as conn:
            yield conn

    @contextmanager
    def _tenant_connection(self, workspace_id: str) -> Iterator[Any]:
        with self._connect(
            self.database_url,
            row_factory=self._dict_row,
            service_role=False,
            workspace_id=workspace_id,
        ) as conn:
            yield conn

    def _apply_rls_context(
        self,
        conn: Any,
        *,
        workspace_id: str | None,
        service_role: bool,
    ) -> None:
        conn.execute(
            "SELECT set_config('app.service_role', %s, true)",
            ("on" if service_role else "off",),
        )
        conn.execute(
            "SELECT set_config('app.current_workspace_id', %s, true)",
            (workspace_id or "",),
        )

    def migrate(self) -> None:
        script = _schema_path().read_text(encoding="utf-8")
        with self._service_connection() as conn:
            with conn.cursor() as cur:
                for statement in _split_sql(script):
                    cur.execute(statement)
                self._copy_legacy_claim_records(cur)
            conn.commit()

    def ping(self) -> str:
        with self._service_connection() as conn:
            row = conn.execute("SELECT current_database() AS database_name").fetchone()
        database_name = row["database_name"] if row else "unknown"
        return f"backend=postgres database={database_name}"

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

        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._upsert_workspace(cur, workspace_id)
                self._upsert_default_user(cur)
                self._upsert_project(cur, detail, context, actor_id)
                self._append_audit_once(
                    cur,
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
                self._remove_stale_project_competitors(cur, project_id, competitor_ids)
                for name, competitor_id in zip(
                    detail.plan.competitors,
                    competitor_ids,
                    strict=False,
                ):
                    self._upsert_competitor(cur, detail, workspace_id, competitor_id, name)
                    self._upsert_project_competitor(cur, project_id, competitor_id)
                    self._append_audit_once(
                        cur,
                        workspace_id=workspace_id,
                        actor_id=actor_id,
                        action="competitor.upserted",
                        resource_type="competitor",
                        resource_id=competitor_id,
                        after={"name": name, "layer": detail.plan.competitor_layer},
                    )
                    self._append_audit_once(
                        cur,
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
                self._upsert_run(cur, detail, context)
                self._append_audit_once(
                    cur,
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
            conn.commit()
        return context

    def save_projection(self, projection: EnterpriseRunProjection) -> None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                for evidence in projection.evidence_records:
                    self._upsert_evidence(cur, evidence)
                    self._upsert_evidence_embedding(cur, evidence)
                    registry_record = self._upsert_source_registry(
                        cur,
                        source_registry_from_evidence(evidence),
                    )
                    self._append_audit_once(
                        cur,
                        workspace_id=registry_record.workspace_id,
                        actor_id=DEFAULT_USER_ID,
                        action="source_registry.upserted",
                        resource_type="source_registry",
                        resource_id=registry_record.id,
                        after=registry_record.model_dump(mode="json"),
                    )
                for claim in projection.claim_records:
                    self._upsert_claim(cur, claim)
                self._upsert_report_version(cur, projection.report_version)
                if projection.evidence_records:
                    self._append_audit_once(
                        cur,
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
                        cur,
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
                    cur,
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
                    cur,
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
            conn.commit()

    def next_report_version_number(
        self,
        *,
        project_id: str,
        topic_normalized: str,
        competitor_layer: str,
        competitor_set_hash: str,
    ) -> int:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                FROM report_versions
                WHERE project_id = %s
                  AND topic_normalized = %s
                  AND competitor_layer = %s
                  AND competitor_set_hash = %s
                """,
                (project_id, topic_normalized, competitor_layer, competitor_set_hash),
            ).fetchone()
        return int(row["next_version"]) if row else 1

    def project_id_for_run(self, run_id: str) -> str | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute("SELECT project_id FROM runs WHERE id = %s", (run_id,)).fetchone()
        return str(row["project_id"]) if row and row["project_id"] else None

    def get_run_projection(self, run_id: str) -> EnterpriseRunProjection | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            report_row = conn.execute(
                """
                SELECT *
                FROM report_versions
                WHERE run_id = %s
                ORDER BY version_number DESC, created_at DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if report_row is None:
                return None
            report_version = ReportVersionRecord.model_validate(dict(report_row))
            report_claim_ids = self._linked_ids(
                conn,
                table="report_version_claims",
                owner_column="report_version_id",
                related_column="claim_id",
                owner_id=report_version.id,
                fallback=report_version.claim_ids,
            )
            report_evidence_ids = self._linked_ids(
                conn,
                table="report_version_evidence",
                owner_column="report_version_id",
                related_column="evidence_id",
                owner_id=report_version.id,
                fallback=report_version.evidence_ids,
            )
            report_version = report_version.model_copy(
                update={
                    "claim_ids": report_claim_ids,
                    "evidence_ids": report_evidence_ids,
                }
            )
            evidence_records = self._records_by_ids(
                conn,
                table="evidence_records",
                ids=report_evidence_ids,
                model=EvidenceRecord,
            )
            claim_records = self._records_by_ids(
                conn,
                table="knowledge_claims",
                ids=report_claim_ids,
                model=ClaimRecord,
            )
        return EnterpriseRunProjection(
            workspace_id=report_version.workspace_id,
            project_id=report_version.project_id,
            run_id=run_id,
            evidence_records=evidence_records,
            claim_records=claim_records,
            report_version=report_version,
        )

    def list_workspaces(self) -> list[WorkspaceRecord]:
        return self._list_models(
            "SELECT * FROM workspaces ORDER BY created_at",
            (),
            WorkspaceRecord,
        )

    def list_workspace_members(
        self,
        workspace_id: str | None = None,
    ) -> list[WorkspaceMemberRecord]:
        if workspace_id:
            return self._list_models(
                """
                SELECT *
                FROM workspace_members
                WHERE workspace_id = %s
                ORDER BY workspace_id, user_id
                """,
                (workspace_id,),
                WorkspaceMemberRecord,
            )
        return self._list_models(
            "SELECT * FROM workspace_members ORDER BY workspace_id, user_id",
            (),
            WorkspaceMemberRecord,
        )

    def upsert_workspace_member(
        self,
        member: WorkspaceMemberRecord,
    ) -> WorkspaceMemberRecord:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._upsert_workspace(cur, member.workspace_id)
                self._upsert_user_placeholder(cur, member.user_id)
                cur.execute(
                    """
                    INSERT INTO workspace_members (
                        workspace_id, user_id, role, status, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (workspace_id, user_id) DO UPDATE SET
                        role = EXCLUDED.role,
                        status = EXCLUDED.status
                    """,
                    (
                        member.workspace_id,
                        member.user_id,
                        member.role,
                        member.status,
                        member.created_at,
                    ),
                )
                self._append_audit(
                    cur,
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
            conn.commit()
        return member

    def get_workspace_member(
        self,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceMemberRecord | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM workspace_members
                WHERE workspace_id = %s AND user_id = %s
                """,
                (workspace_id, user_id),
            ).fetchone()
        return self._model_from_row(WorkspaceMemberRecord, row) if row else None

    def update_workspace_quota(
        self,
        workspace_id: str,
        update: WorkspaceQuotaUpdateRequest,
        *,
        actor_id: str | None = None,
    ) -> WorkspaceRecord | None:
        update_values = update.model_dump(exclude_none=True)
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                before_row = cur.execute(
                    "SELECT * FROM workspaces WHERE id = %s",
                    (workspace_id,),
                ).fetchone()
                if before_row is None:
                    return None
                before = self._model_from_row(WorkspaceRecord, before_row)
                if update_values:
                    updated = before.model_copy(
                        update={**update_values, "updated_at": datetime.utcnow()}
                    )
                    cur.execute(
                        """
                        UPDATE workspaces
                        SET monthly_run_quota = %s,
                            monthly_token_quota = %s,
                            monthly_cost_quota_usd = %s,
                            quota_enforcement = %s,
                            updated_at = %s
                        WHERE id = %s
                        """,
                        (
                            updated.monthly_run_quota,
                            updated.monthly_token_quota,
                            updated.monthly_cost_quota_usd,
                            updated.quota_enforcement,
                            updated.updated_at,
                            workspace_id,
                        ),
                    )
                    self._append_audit(
                        cur,
                        workspace_id=workspace_id,
                        actor_id=actor_id or DEFAULT_USER_ID,
                        action="workspace.quota_updated",
                        resource_type="workspace",
                        resource_id=workspace_id,
                        before=before.model_dump(mode="json"),
                        after=updated.model_dump(mode="json"),
                    )
                row = cur.execute(
                    "SELECT * FROM workspaces WHERE id = %s",
                    (workspace_id,),
                ).fetchone()
            conn.commit()
        return self._model_from_row(WorkspaceRecord, row) if row else None

    def get_workspace_usage(
        self,
        workspace_id: str,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> WorkspaceUsageSummary:
        period_start, period_end = _usage_period(period_start, period_end)
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._upsert_workspace(cur, workspace_id)
                workspace_row = cur.execute(
                    "SELECT * FROM workspaces WHERE id = %s",
                    (workspace_id,),
                ).fetchone()
                usage_row = cur.execute(
                    """
                    SELECT
                        (COUNT(*))::int AS run_count,
                        (COUNT(*) FILTER (WHERE status = 'completed'))::int
                            AS completed_run_count,
                        (COUNT(*) FILTER (WHERE status = 'failed'))::int
                            AS failed_run_count,
                        (COUNT(*) FILTER (WHERE status = 'interrupted'))::int
                            AS interrupted_run_count,
                        COALESCE(
                            SUM(
                                NULLIF(
                                    detail_json #>> '{metrics,input_tokens_estimate}',
                                    ''
                                )::bigint
                            ),
                            0
                        )::bigint AS input_tokens_estimate,
                        COALESCE(
                            SUM(
                                NULLIF(
                                    detail_json #>> '{metrics,output_tokens_estimate}',
                                    ''
                                )::bigint
                            ),
                            0
                        )::bigint AS output_tokens_estimate,
                        COALESCE(
                            SUM(
                                NULLIF(
                                    detail_json #>> '{metrics,cost_estimate_usd}',
                                    ''
                                )::double precision
                            ),
                            0
                        )::double precision AS cost_estimate_usd
                    FROM runs
                    WHERE workspace_id = %s
                      AND created_at >= %s
                      AND created_at < %s
                    """,
                    (workspace_id, period_start, period_end),
                ).fetchone()
            conn.commit()
        workspace = WorkspaceRecord.model_validate(dict(workspace_row))
        usage = dict(usage_row or {})
        return build_workspace_usage_summary(
            workspace,
            period_start=period_start,
            period_end=period_end,
            run_count=int(usage.get("run_count") or 0),
            completed_run_count=int(usage.get("completed_run_count") or 0),
            failed_run_count=int(usage.get("failed_run_count") or 0),
            interrupted_run_count=int(usage.get("interrupted_run_count") or 0),
            input_tokens_estimate=int(usage.get("input_tokens_estimate") or 0),
            output_tokens_estimate=int(usage.get("output_tokens_estimate") or 0),
            cost_estimate_usd=float(usage.get("cost_estimate_usd") or 0.0),
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
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE id = %s",
                (workspace_id,),
            ).fetchone()
        workspace = self._model_from_row(WorkspaceRecord, row)
        return build_quota_decision(usage, workspace.quota_enforcement)

    def list_notifications(
        self,
        workspace_id: str | None = None,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[NotificationRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if workspace_id:
            clauses.append("workspace_id = %s")
            params.append(workspace_id)
        if status:
            clauses.append("status = %s")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, limit))
        return self._list_models(
            f"""
            SELECT *
            FROM notifications
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
            NotificationRecord,
        )

    def upsert_notification(
        self,
        notification: NotificationRecord,
    ) -> NotificationRecord:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._upsert_workspace(cur, notification.workspace_id)
                if notification.created_by:
                    self._upsert_user_placeholder(cur, notification.created_by)
                before_row = cur.execute(
                    "SELECT * FROM notifications WHERE id = %s",
                    (notification.id,),
                ).fetchone()
                self._upsert_notification(cur, notification)
                self._append_audit(
                    cur,
                    workspace_id=notification.workspace_id,
                    actor_id=notification.created_by or DEFAULT_USER_ID,
                    action="notification.upserted",
                    resource_type="notification",
                    resource_id=notification.id,
                    before=self._model_from_row(NotificationRecord, before_row).model_dump(
                        mode="json"
                    )
                    if before_row
                    else None,
                    after=notification.model_dump(mode="json"),
                )
            conn.commit()
        return notification

    def list_projects(self, workspace_id: str | None = None) -> list[ProjectRecord]:
        if workspace_id:
            return self._list_models(
                "SELECT * FROM projects WHERE workspace_id = %s ORDER BY updated_at DESC",
                (workspace_id,),
                ProjectRecord,
            )
        return self._list_models(
            "SELECT * FROM projects ORDER BY updated_at DESC",
            (),
            ProjectRecord,
        )

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
        return self._model_from_row(ProjectRecord, row) if row else None

    def upsert_project(self, project: ProjectRecord) -> ProjectRecord:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._upsert_workspace(cur, project.workspace_id)
                self._upsert_default_user(cur)
                before_row = cur.execute(
                    "SELECT * FROM projects WHERE id = %s",
                    (project.id,),
                ).fetchone()
                cur.execute(
                    """
                    INSERT INTO projects (
                        id, workspace_id, name, topic, topic_normalized,
                        competitor_layer, competitor_set_hash, scenario_id,
                        created_by, metadata, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        topic = EXCLUDED.topic,
                        topic_normalized = EXCLUDED.topic_normalized,
                        competitor_layer = EXCLUDED.competitor_layer,
                        competitor_set_hash = EXCLUDED.competitor_set_hash,
                        scenario_id = EXCLUDED.scenario_id,
                        metadata = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        project.id,
                        project.workspace_id,
                        self._text(project.name),
                        self._text(project.topic),
                        project.topic_normalized,
                        project.competitor_layer,
                        project.competitor_set_hash,
                        project.scenario_id,
                        project.created_by,
                        self._json(project.metadata),
                        project.created_at,
                        project.updated_at,
                    ),
                )
                self._append_audit(
                    cur,
                    workspace_id=project.workspace_id,
                    actor_id=project.created_by or DEFAULT_USER_ID,
                    action="project.upserted",
                    resource_type="project",
                    resource_id=project.id,
                    before=self._model_from_row(ProjectRecord, before_row).model_dump(mode="json")
                    if before_row
                    else None,
                    after=project.model_dump(mode="json"),
                )
            conn.commit()
        return project

    def audit_schema_evolution_review(
        self,
        project: ProjectRecord,
        review: SchemaEvolutionReviewRecord,
        *,
        actor_id: str | None = None,
    ) -> None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._append_audit(
                    cur,
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
            conn.commit()

    def list_competitors(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> list[CompetitorRecord]:
        sql = "SELECT c.* FROM competitors c"
        params: list[str] = []
        clauses: list[str] = []
        if project_id:
            sql += " JOIN project_competitors pc ON pc.competitor_id = c.id"
            clauses.append("pc.project_id = %s")
            params.append(project_id)
        if workspace_id:
            clauses.append("c.workspace_id = %s")
            params.append(workspace_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY lower(c.name)"
        return self._list_models(sql, tuple(params), CompetitorRecord)

    def list_evidence(self, project_id: str | None = None) -> list[EvidenceRecord]:
        if project_id:
            return self._list_models(
                """
                SELECT *
                FROM evidence_records e
                WHERE e.project_id = %s
                   OR EXISTS (
                       SELECT 1
                       FROM report_version_evidence rve
                       WHERE rve.evidence_id = e.id
                         AND rve.project_id = %s
                   )
                ORDER BY e.captured_at DESC
                """,
                (project_id, project_id),
                EvidenceRecord,
            )
        return self._list_models(
            "SELECT * FROM evidence_records ORDER BY captured_at DESC",
            (),
            EvidenceRecord,
        )

    def upsert_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                before_row = cur.execute(
                    "SELECT * FROM evidence_records WHERE id = %s",
                    (evidence.id,),
                ).fetchone()
                evidence = self._apply_embedding_dedupe(cur, evidence)
                self._upsert_evidence(cur, evidence)
                if evidence.metadata.get("embedding_duplicate_of"):
                    self._delete_evidence_embedding(cur, evidence.id)
                else:
                    self._upsert_evidence_embedding(cur, evidence)
                registry_record = self._upsert_source_registry(
                    cur,
                    source_registry_from_evidence(evidence),
                )
                self._append_audit_once(
                    cur,
                    workspace_id=registry_record.workspace_id,
                    actor_id=DEFAULT_USER_ID,
                    action="source_registry.upserted",
                    resource_type="source_registry",
                    resource_id=registry_record.id,
                    after=registry_record.model_dump(mode="json"),
                )
                self._append_audit(
                    cur,
                    workspace_id=evidence.workspace_id,
                    actor_id=DEFAULT_USER_ID,
                    action="evidence.upserted",
                    resource_type="evidence",
                    resource_id=evidence.id,
                    before=self._model_from_row(EvidenceRecord, before_row).model_dump(mode="json")
                    if before_row
                    else None,
                    after=evidence.model_dump(mode="json"),
                )
            conn.commit()
        return evidence

    def list_evidence_embeddings(
        self,
        workspace_id: str | None = None,
    ) -> list[EvidenceEmbeddingRecord]:
        if workspace_id:
            return self._list_models(
                """
                SELECT
                    id, workspace_id, project_id, evidence_id, embedding_model,
                    embedding_dimensions, embedding_hash, embedding_text,
                    created_at, updated_at, metadata
                FROM evidence_embeddings
                WHERE workspace_id = %s
                ORDER BY workspace_id, evidence_id
                """,
                (workspace_id,),
                EvidenceEmbeddingRecord,
            )
        return self._list_models(
            """
            SELECT
                id, workspace_id, project_id, evidence_id, embedding_model,
                embedding_dimensions, embedding_hash, embedding_text,
                created_at, updated_at, metadata
            FROM evidence_embeddings
            ORDER BY workspace_id, evidence_id
            """,
            (),
            EvidenceEmbeddingRecord,
        )

    def reindex_evidence_embeddings(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> EvidenceReindexResult:
        sql = "SELECT * FROM evidence_records"
        clauses: list[str] = []
        params: list[str] = []
        if workspace_id:
            clauses.append("workspace_id = %s")
            params.append(workspace_id)
        if project_id:
            clauses.append("project_id = %s")
            params.append(project_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                rows = cur.execute(sql, tuple(params)).fetchall()
                target_ids = [str(row["id"]) for row in rows]
                if target_ids:
                    cur.execute(
                        "DELETE FROM evidence_embeddings WHERE evidence_id = ANY(%s)",
                        (target_ids,),
                    )
                indexed_count = 0
                duplicate_count = 0
                for row in rows:
                    evidence = self._apply_embedding_dedupe(
                        cur,
                        self._model_from_row(EvidenceRecord, row),
                    )
                    self._upsert_evidence(cur, evidence)
                    if evidence.metadata.get("embedding_duplicate_of"):
                        duplicate_count += 1
                        continue
                    self._upsert_evidence_embedding(cur, evidence)
                    indexed_count += 1
            conn.commit()
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
        query_vector = vector_literal(deterministic_embedding(query))
        clauses = ["e.workspace_id = %s"]
        filter_params: list[Any] = [workspace_id]
        if project_id:
            clauses.append("e.project_id = %s")
            filter_params.append(project_id)
        params: list[Any] = [query_vector, *filter_params, query_vector, max(1, limit)]
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    e.*,
                    ee.embedding_model AS embedding_model,
                    1 - (ee.embedding <=> %s::vector) AS score
                FROM evidence_embeddings ee
                JOIN evidence_records e ON e.id = ee.evidence_id
                WHERE {" AND ".join(clauses)}
                ORDER BY ee.embedding <=> %s::vector, e.captured_at DESC
                LIMIT %s
                """,
                tuple(params),
            ).fetchall()
        hits: list[EvidenceSearchHit] = []
        for row in rows:
            evidence_data = dict(row)
            embedding_model = str(evidence_data.pop("embedding_model"))
            score = float(evidence_data.pop("score") or 0)
            hits.append(
                EvidenceSearchHit(
                    evidence=self._model_from_mapping(EvidenceRecord, evidence_data),
                    score=score,
                    embedding_model=embedding_model,
                )
            )
        return hits

    def list_artifacts(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[ArtifactRecord]:
        sql = "SELECT * FROM artifacts"
        params: list[str] = []
        clauses: list[str] = []
        if workspace_id:
            clauses.append("workspace_id = %s")
            params.append(workspace_id)
        if project_id:
            clauses.append("project_id = %s")
            params.append(project_id)
        if evidence_id:
            clauses.append("evidence_id = %s")
            params.append(evidence_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        return self._list_models(sql, tuple(params), ArtifactRecord)

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id = %s", (artifact_id,)).fetchone()
        return self._model_from_row(ArtifactRecord, row) if row else None

    def upsert_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._upsert_workspace(cur, artifact.workspace_id)
                before_row = cur.execute(
                    "SELECT * FROM artifacts WHERE id = %s",
                    (artifact.id,),
                ).fetchone()
                self._upsert_artifact(cur, artifact)
                self._append_audit(
                    cur,
                    workspace_id=artifact.workspace_id,
                    actor_id=artifact.created_by or DEFAULT_USER_ID,
                    action="artifact.upserted",
                    resource_type="artifact",
                    resource_id=artifact.id,
                    before=self._model_from_row(ArtifactRecord, before_row).model_dump(mode="json")
                    if before_row
                    else None,
                    after=artifact.model_dump(mode="json"),
                )
            conn.commit()
        return artifact

    def list_source_registry(
        self,
        workspace_id: str | None = None,
    ) -> list[SourceRegistryRecord]:
        if workspace_id:
            return self._list_models(
                """
                SELECT *
                FROM source_registry
                WHERE workspace_id = %s
                ORDER BY domain, source_type
                """,
                (workspace_id,),
                SourceRegistryRecord,
            )
        return self._list_models(
            "SELECT * FROM source_registry ORDER BY domain, source_type",
            (),
            SourceRegistryRecord,
        )

    def upsert_source_registry(
        self,
        record: SourceRegistryRecord,
        *,
        actor_id: str | None = None,
    ) -> SourceRegistryRecord:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._upsert_workspace(cur, record.workspace_id)
                before_row = self._select_source_registry_by_key(cur, record)
                updated = self._upsert_source_registry(cur, record)
                self._append_audit(
                    cur,
                    workspace_id=updated.workspace_id,
                    actor_id=actor_id or DEFAULT_USER_ID,
                    action="source_registry.upserted",
                    resource_type="source_registry",
                    resource_id=updated.id,
                    before=self._model_from_row(SourceRegistryRecord, before_row).model_dump(
                        mode="json"
                    )
                    if before_row
                    else None,
                    after=updated.model_dump(mode="json"),
                )
            conn.commit()
        return updated

    def update_evidence_quality(
        self,
        evidence_id: str,
        quality_label: EvidenceQualityLabel,
        *,
        actor_id: str | None = None,
        note: str = "",
    ) -> EvidenceRecord | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                row = cur.execute(
                    "SELECT * FROM evidence_records WHERE id = %s",
                    (evidence_id,),
                ).fetchone()
                if row is None:
                    return None
                before = self._model_from_row(EvidenceRecord, row)
                metadata = dict(before.metadata)
                metadata["quality_note"] = note
                metadata["quality_reviewed_at"] = datetime.utcnow().isoformat()
                updated = before.model_copy(
                    update={
                        "quality_label": quality_label,
                        "metadata": metadata,
                    },
                )
                cur.execute(
                    """
                    UPDATE evidence_records
                    SET quality_label = %s, metadata = %s
                    WHERE id = %s
                    """,
                    (quality_label, self._json(metadata), evidence_id),
                )
                self._append_audit(
                    cur,
                    workspace_id=before.workspace_id,
                    actor_id=actor_id or DEFAULT_USER_ID,
                    action="evidence.quality_updated",
                    resource_type="evidence",
                    resource_id=evidence_id,
                    before=before.model_dump(mode="json"),
                    after=updated.model_dump(mode="json"),
                )
            conn.commit()
        return updated

    def list_claims(self, project_id: str | None = None) -> list[ClaimRecord]:
        if project_id:
            return self._list_models(
                """
                SELECT *
                FROM knowledge_claims c
                WHERE c.project_id = %s
                   OR EXISTS (
                       SELECT 1
                       FROM report_version_claims rvc
                       WHERE rvc.claim_id = c.id
                         AND rvc.project_id = %s
                   )
                ORDER BY c.created_at DESC
                """,
                (project_id, project_id),
                ClaimRecord,
            )
        return self._list_models(
            "SELECT * FROM knowledge_claims ORDER BY created_at DESC",
            (),
            ClaimRecord,
        )

    def list_report_versions(self, project_id: str | None = None) -> list[ReportVersionRecord]:
        if project_id:
            return sort_report_versions(
                self._list_models(
                    """
                SELECT *
                FROM report_versions
                WHERE project_id = %s
                """,
                    (project_id,),
                    ReportVersionRecord,
                )
            )
        return sort_report_versions(
            self._list_models(
                "SELECT * FROM report_versions",
                (),
                ReportVersionRecord,
            )
        )

    def get_report_version(self, version_id: str) -> ReportVersionRecord | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute(
                "SELECT * FROM report_versions WHERE id = %s",
                (version_id,),
            ).fetchone()
        return self._model_from_row(ReportVersionRecord, row) if row else None

    def upsert_report_version(self, version: ReportVersionRecord) -> ReportVersionRecord:
        version = normalize_report_version_sources(
            version,
            self._report_scope_evidence(version),
        )
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                before_row = cur.execute(
                    "SELECT * FROM report_versions WHERE id = %s",
                    (version.id,),
                ).fetchone()
                before_record = (
                    self._model_from_row(ReportVersionRecord, before_row) if before_row else None
                )
                self._upsert_report_version(cur, version)
                self._append_audit(
                    cur,
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
                        cur,
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
            conn.commit()
        return version

    def _report_scope_evidence(self, version: ReportVersionRecord) -> list[EvidenceRecord]:
        if not version.evidence_ids:
            return self.list_evidence(project_id=version.project_id)
        placeholders = ", ".join(["%s"] * len(version.evidence_ids))
        params = [version.project_id, *version.evidence_ids]
        return self._list_models(
            f"""
            SELECT *
            FROM evidence_records
            WHERE project_id = %s
               OR id IN ({placeholders})
            ORDER BY captured_at DESC
            """,
            tuple(params),
            EvidenceRecord,
        )

    def get_previous_report_version(
        self,
        version: ReportVersionRecord,
    ) -> ReportVersionRecord | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM report_versions
                WHERE project_id = %s
                  AND topic_normalized = %s
                  AND competitor_layer = %s
                  AND competitor_set_hash = %s
                  AND version_number < %s
                ORDER BY version_number DESC, created_at DESC
                LIMIT 1
                """,
                (
                    version.project_id,
                    version.topic_normalized,
                    version.competitor_layer,
                    version.competitor_set_hash,
                    version.version_number,
                ),
            ).fetchone()
        return self._model_from_row(ReportVersionRecord, row) if row else None

    def list_audit_logs(self, workspace_id: str | None = None) -> list[AuditLogRecord]:
        if workspace_id:
            return self._list_models(
                "SELECT * FROM audit_logs WHERE workspace_id = %s ORDER BY created_at DESC",
                (workspace_id,),
                AuditLogRecord,
            )
        return self._list_models(
            "SELECT * FROM audit_logs ORDER BY created_at DESC",
            (),
            AuditLogRecord,
        )

    def record_memory_feedback_audit(
        self,
        feedback: UserFeedbackRecord,
        candidates: list[MemoryCandidate],
        *,
        actor_id: str | None = None,
    ) -> None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                self._append_audit(
                    cur,
                    workspace_id=feedback.workspace_id,
                    actor_id=actor_id or feedback.user_id or DEFAULT_USER_ID,
                    action="memory.feedback_captured",
                    resource_type="memory_feedback",
                    resource_id=feedback.id,
                    after=_memory_feedback_audit_after(feedback, candidates),
                )
            conn.commit()

    def _list_models(
        self,
        sql: str,
        params: tuple[Any, ...],
        model: type[BaseModel],
    ) -> list[Any]:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._model_from_row(model, row) for row in rows]

    def _records_by_ids(
        self,
        conn: Any,
        *,
        table: str,
        ids: list[str],
        model: type[BaseModel],
    ) -> list[Any]:
        if not ids:
            return []
        rows = conn.execute(f"SELECT * FROM {table} WHERE id = ANY(%s)", (ids,)).fetchall()
        by_id = {row["id"]: self._model_from_row(model, row) for row in rows}
        return [by_id[item] for item in ids if item in by_id]

    def _model_from_row(self, model: type[BaseModel], row: Any) -> Any:
        return self._model_from_mapping(model, dict(row))

    @staticmethod
    def _model_from_mapping(model: type[BaseModel], data: dict[str, Any]) -> Any:
        allowed_fields = set(model.model_fields)
        return model.model_validate(
            {key: value for key, value in data.items() if key in allowed_fields}
        )

    def _linked_ids(
        self,
        conn: Any,
        *,
        table: str,
        owner_column: str,
        related_column: str,
        owner_id: str,
        fallback: list[str],
    ) -> list[str]:
        rows = conn.execute(
            f"""
            SELECT {related_column}
            FROM {table}
            WHERE {owner_column} = %s
            ORDER BY ordinal, {related_column}
            """,
            (owner_id,),
        ).fetchall()
        ids = [str(row[related_column]) for row in rows]
        return ids or list(fallback)

    def _upsert_workspace(self, cur: Any, workspace_id: str) -> None:
        cur.execute(
            """
            INSERT INTO workspaces (id, name, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (workspace_id, self._text(_title_from_id(workspace_id)), "Phase 1 workspace."),
        )
        self._upsert_default_user(cur)
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, user_id, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (workspace_id, user_id) DO NOTHING
            """,
            (workspace_id, DEFAULT_USER_ID, "owner"),
        )

    def _upsert_default_user(self, cur: Any) -> None:
        cur.execute(
            """
            INSERT INTO users (id, email, display_name, role)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (DEFAULT_USER_ID, "system@local", "System", "owner"),
        )

    def _upsert_user_placeholder(self, cur: Any, user_id: str) -> None:
        cur.execute(
            """
            INSERT INTO users (id, email, display_name, role)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (user_id, f"{user_id}@local", self._text(_title_from_id(user_id)), "viewer"),
        )

    def _upsert_project(
        self,
        cur: Any,
        detail: RunDetail,
        context: EnterpriseRunContext,
        actor_id: str,
    ) -> None:
        metadata = {
            "last_run_id": detail.id,
            "scenario_id": detail.plan.scenario_id,
            "qa_rule_ids": detail.plan.qa_rule_ids,
        }
        cur.execute(
            """
            INSERT INTO projects (
                id, workspace_id, name, topic, topic_normalized,
                competitor_layer, competitor_set_hash, scenario_id,
                created_by, metadata, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                topic = EXCLUDED.topic,
                topic_normalized = EXCLUDED.topic_normalized,
                competitor_layer = EXCLUDED.competitor_layer,
                competitor_set_hash = EXCLUDED.competitor_set_hash,
                scenario_id = EXCLUDED.scenario_id,
                metadata = projects.metadata || EXCLUDED.metadata,
                updated_at = now()
            """,
            (
                context.project_id,
                context.workspace_id,
                self._text(detail.topic),
                self._text(detail.topic),
                compute_topic_normalized(detail.topic),
                detail.plan.competitor_layer,
                compute_competitor_set_hash(context.competitor_ids),
                detail.plan.scenario_id,
                actor_id,
                self._json(metadata),
                detail.created_at,
            ),
        )

    def _upsert_competitor(
        self,
        cur: Any,
        detail: RunDetail,
        workspace_id: str,
        competitor_id: str,
        name: str,
    ) -> None:
        cur.execute(
            """
            INSERT INTO competitors (
                id, workspace_id, name, normalized_name, layer, homepage_url, metadata,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                layer = EXCLUDED.layer,
                homepage_url = EXCLUDED.homepage_url,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            """,
            (
                competitor_id,
                workspace_id,
                self._text(name),
                normalize_key(name),
                detail.plan.competitor_layer,
                self._text(detail.plan.homepage_hints.get(name)),
                self._json(
                    {
                        "scenario_id": detail.plan.scenario_id,
                        "qa_rule_ids": detail.plan.qa_rule_ids,
                        "homepage_verified": detail.plan.homepage_verified.get(name, False),
                    }
                ),
                detail.created_at,
            ),
        )

    def _upsert_project_competitor(
        self,
        cur: Any,
        project_id: str,
        competitor_id: str,
    ) -> None:
        cur.execute(
            """
            INSERT INTO project_competitors (project_id, competitor_id)
            VALUES (%s, %s)
            ON CONFLICT (project_id, competitor_id) DO NOTHING
            """,
            (project_id, competitor_id),
        )

    def _remove_stale_project_competitors(
        self,
        cur: Any,
        project_id: str,
        competitor_ids: list[str],
    ) -> None:
        if not competitor_ids:
            cur.execute(
                "DELETE FROM project_competitors WHERE project_id = %s",
                (project_id,),
            )
            return
        cur.execute(
            """
            DELETE FROM project_competitors
            WHERE project_id = %s
              AND NOT (competitor_id = ANY(%s))
            """,
            (project_id, competitor_ids),
        )

    def _upsert_run(
        self,
        cur: Any,
        detail: RunDetail,
        context: EnterpriseRunContext,
    ) -> None:
        cur.execute(
            """
            INSERT INTO runs (
                id, idempotency_key, workspace_id, project_id, topic, status, execution_mode,
                detail_json, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                status = EXCLUDED.status,
                detail_json = EXCLUDED.detail_json,
                updated_at = EXCLUDED.updated_at
            """,
            (
                detail.id,
                detail.idempotency_key or detail.id,
                context.workspace_id,
                context.project_id,
                self._text(detail.topic),
                detail.status,
                detail.execution_mode,
                self._json(detail.model_dump(mode="json")),
                detail.created_at,
                detail.updated_at,
            ),
        )

    def _upsert_evidence(self, cur: Any, evidence: EvidenceRecord) -> None:
        cur.execute(
            """
            INSERT INTO evidence_records (
                id, workspace_id, project_id, run_id, raw_source_id, competitor_id,
                dimension, source_type, title, url, canonical_url, snippet, content_hash,
                reliability_score, freshness_score, quality_label, first_seen_run_id,
                last_seen_run_id, seen_count, captured_at, metadata
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO UPDATE SET
                reliability_score = EXCLUDED.reliability_score,
                freshness_score = EXCLUDED.freshness_score,
                quality_label = EXCLUDED.quality_label,
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                seen_count = CASE
                    WHEN evidence_records.last_seen_run_id
                        IS DISTINCT FROM EXCLUDED.last_seen_run_id
                    THEN evidence_records.seen_count + 1
                    ELSE evidence_records.seen_count
                END,
                metadata = (
                    (evidence_records.metadata || EXCLUDED.metadata)
                    || jsonb_build_object(
                        'raw_source_aliases',
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT alias), '[]'::jsonb)
                            FROM jsonb_array_elements_text(
                                COALESCE(
                                    evidence_records.metadata->'raw_source_aliases',
                                    '[]'::jsonb
                                )
                                || COALESCE(
                                    EXCLUDED.metadata->'raw_source_aliases',
                                    '[]'::jsonb
                                )
                                || jsonb_build_array(
                                    evidence_records.raw_source_id,
                                    EXCLUDED.raw_source_id
                                )
                            ) AS raw_source_alias(alias)
                            WHERE alias <> ''
                        )
                    )
                )
            """,
            (
                evidence.id,
                evidence.workspace_id,
                evidence.project_id,
                evidence.run_id,
                evidence.raw_source_id,
                evidence.competitor_id,
                self._text(evidence.dimension),
                self._text(evidence.source_type),
                self._text(evidence.title),
                self._text(str(evidence.url) if evidence.url else None),
                self._text(evidence.canonical_url),
                self._text(evidence.snippet),
                evidence.content_hash,
                evidence.reliability_score,
                evidence.freshness_score,
                evidence.quality_label,
                evidence.first_seen_run_id or evidence.run_id,
                evidence.last_seen_run_id or evidence.run_id,
                evidence.seen_count,
                evidence.captured_at,
                self._json(evidence.metadata),
            ),
        )

    def _upsert_artifact(self, cur: Any, artifact: ArtifactRecord) -> None:
        cur.execute(
            """
            INSERT INTO artifacts (
                id, workspace_id, project_id, evidence_id, run_id, artifact_type,
                filename, media_type, storage_backend, uri, byte_size, content_hash,
                source_url, created_by, created_at, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                filename = EXCLUDED.filename,
                media_type = EXCLUDED.media_type,
                storage_backend = EXCLUDED.storage_backend,
                uri = EXCLUDED.uri,
                byte_size = EXCLUDED.byte_size,
                content_hash = EXCLUDED.content_hash,
                source_url = EXCLUDED.source_url,
                metadata = EXCLUDED.metadata
            """,
            (
                artifact.id,
                artifact.workspace_id,
                artifact.project_id,
                artifact.evidence_id,
                artifact.run_id,
                self._text(artifact.artifact_type),
                self._text(artifact.filename),
                self._text(artifact.media_type),
                self._text(artifact.storage_backend),
                self._text(artifact.uri),
                artifact.byte_size,
                artifact.content_hash,
                self._text(str(artifact.source_url) if artifact.source_url else None),
                artifact.created_by,
                artifact.created_at,
                self._json(artifact.metadata),
            ),
        )

    def _upsert_evidence_embedding(self, cur: Any, evidence: EvidenceRecord) -> None:
        if evidence.metadata.get("embedding_duplicate_of"):
            self._delete_evidence_embedding(cur, evidence.id)
            return
        record = build_evidence_embedding_record(evidence)
        embedding = vector_literal(deterministic_embedding(record.embedding_text))
        cur.execute(
            """
            INSERT INTO evidence_embeddings (
                id, workspace_id, project_id, evidence_id, embedding_model,
                embedding_dimensions, embedding_hash, embedding_text, embedding,
                created_at, updated_at, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, now(), %s)
            ON CONFLICT (evidence_id, embedding_model) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                embedding_dimensions = EXCLUDED.embedding_dimensions,
                embedding_hash = EXCLUDED.embedding_hash,
                embedding_text = EXCLUDED.embedding_text,
                embedding = EXCLUDED.embedding,
                updated_at = now(),
                metadata = EXCLUDED.metadata
            """,
            (
                record.id,
                record.workspace_id,
                record.project_id,
                record.evidence_id,
                self._text(record.embedding_model),
                record.embedding_dimensions,
                record.embedding_hash,
                self._text(record.embedding_text),
                embedding,
                record.created_at,
                self._json(record.metadata),
            ),
        )

    def _delete_evidence_embedding(self, cur: Any, evidence_id: str) -> None:
        cur.execute(
            "DELETE FROM evidence_embeddings WHERE evidence_id = %s",
            (evidence_id,),
        )

    def _apply_embedding_dedupe(
        self,
        cur: Any,
        evidence: EvidenceRecord,
    ) -> EvidenceRecord:
        duplicate = self._find_embedding_duplicate(cur, evidence)
        metadata = dict(evidence.metadata)
        if duplicate is None:
            metadata.pop("embedding_duplicate_of", None)
            metadata.pop("embedding_dedupe_key", None)
            metadata.pop("embedding_dedupe_strategy", None)
            metadata["embedding_indexed"] = True
            return evidence.model_copy(update={"metadata": metadata})
        duplicate_id, dedupe_key = duplicate
        metadata["embedding_duplicate_of"] = duplicate_id
        metadata["embedding_dedupe_key"] = dedupe_key
        metadata["embedding_dedupe_strategy"] = _embedding_dedupe_strategy(dedupe_key)
        metadata["embedding_indexed"] = False
        return evidence.model_copy(update={"metadata": metadata})

    def _find_embedding_duplicate(
        self,
        cur: Any,
        evidence: EvidenceRecord,
    ) -> tuple[str, str] | None:
        keys = _embedding_dedupe_keys(evidence)
        if not keys:
            return None
        content_hash = evidence.content_hash.casefold().strip()
        canonical_url = _evidence_dedupe_url(evidence)
        rows = cur.execute(
            """
            SELECT *
            FROM evidence_records
            WHERE workspace_id = %s
              AND project_id = %s
              AND competitor_id = %s
              AND lower(dimension) = lower(%s)
              AND (
                lower(content_hash) = lower(%s)
                OR (
                    %s <> ''
                    AND COALESCE(NULLIF(lower(canonical_url), ''), lower(url), '') = lower(%s)
                )
              )
            ORDER BY captured_at ASC, id ASC
            """,
            (
                evidence.workspace_id,
                evidence.project_id,
                evidence.competitor_id,
                evidence.dimension,
                content_hash,
                canonical_url,
                canonical_url,
            ),
        ).fetchall()
        candidates = [self._model_from_row(EvidenceRecord, row) for row in rows]
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
        return canonical.id, matching_keys[0]

    def _select_source_registry_by_key(
        self,
        cur: Any,
        record: SourceRegistryRecord,
    ) -> Any | None:
        return cur.execute(
            """
            SELECT *
            FROM source_registry
            WHERE workspace_id = %s AND domain = %s AND source_type = %s
            """,
            (record.workspace_id, record.domain, record.source_type),
        ).fetchone()

    def _upsert_source_registry(
        self,
        cur: Any,
        record: SourceRegistryRecord,
    ) -> SourceRegistryRecord:
        row = cur.execute(
            """
            INSERT INTO source_registry (
                id, workspace_id, domain, source_type, display_name, homepage_url,
                trust_level, robots_status, policy_review_status, policy_review_reason,
                is_active, first_seen_run_id,
                last_seen_run_id, first_seen_at, last_seen_at, seen_count, metadata
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (workspace_id, domain, source_type) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                homepage_url = COALESCE(EXCLUDED.homepage_url, source_registry.homepage_url),
                trust_level = CASE
                    WHEN source_registry.trust_level = 'official'
                         OR EXCLUDED.trust_level = 'official'
                    THEN 'official'
                    WHEN source_registry.trust_level = 'verified'
                         OR EXCLUDED.trust_level = 'verified'
                    THEN 'verified'
                    WHEN source_registry.trust_level = 'community'
                         OR EXCLUDED.trust_level = 'community'
                    THEN 'community'
                    WHEN source_registry.trust_level = 'synthetic'
                         OR EXCLUDED.trust_level = 'synthetic'
                    THEN 'synthetic'
                    ELSE 'unknown'
                END,
                robots_status = CASE
                    WHEN EXCLUDED.robots_status <> 'unknown'
                    THEN EXCLUDED.robots_status
                    ELSE source_registry.robots_status
                END,
                policy_review_status = CASE
                    WHEN EXCLUDED.policy_review_status <> 'not_required'
                    THEN EXCLUDED.policy_review_status
                    ELSE source_registry.policy_review_status
                END,
                policy_review_reason = COALESCE(
                    NULLIF(EXCLUDED.policy_review_reason, ''),
                    source_registry.policy_review_reason
                ),
                is_active = source_registry.is_active,
                first_seen_run_id = COALESCE(
                    source_registry.first_seen_run_id,
                    EXCLUDED.first_seen_run_id
                ),
                last_seen_run_id = COALESCE(
                    EXCLUDED.last_seen_run_id,
                    source_registry.last_seen_run_id
                ),
                first_seen_at = LEAST(source_registry.first_seen_at, EXCLUDED.first_seen_at),
                last_seen_at = GREATEST(source_registry.last_seen_at, EXCLUDED.last_seen_at),
                seen_count = CASE
                    WHEN EXCLUDED.last_seen_run_id IS NOT NULL
                         AND source_registry.last_seen_run_id
                             IS DISTINCT FROM EXCLUDED.last_seen_run_id
                    THEN GREATEST(source_registry.seen_count + 1, EXCLUDED.seen_count)
                    ELSE GREATEST(source_registry.seen_count, EXCLUDED.seen_count)
                END,
                metadata = source_registry.metadata || EXCLUDED.metadata
            RETURNING *
            """,
            (
                record.id,
                record.workspace_id,
                self._text(record.domain),
                self._text(record.source_type),
                self._text(record.display_name),
                self._text(str(record.homepage_url) if record.homepage_url else None),
                record.trust_level,
                record.robots_status,
                record.policy_review_status,
                self._text(record.policy_review_reason),
                record.is_active,
                record.first_seen_run_id,
                record.last_seen_run_id,
                record.first_seen_at,
                record.last_seen_at,
                record.seen_count,
                self._json(record.metadata),
            ),
        ).fetchone()
        return self._model_from_row(SourceRegistryRecord, row)

    def _upsert_claim(self, cur: Any, claim: ClaimRecord) -> None:
        cur.execute(
            """
            INSERT INTO knowledge_claims (
                id, workspace_id, project_id, run_id, competitor_id, claim_type,
                claim_text, evidence_ids, confidence, status, created_by_agent, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                evidence_ids = EXCLUDED.evidence_ids,
                confidence = EXCLUDED.confidence,
                status = EXCLUDED.status
            """,
            (
                claim.id,
                claim.workspace_id,
                claim.project_id,
                claim.run_id,
                claim.competitor_id,
                self._text(claim.claim_type),
                self._text(claim.claim_text),
                claim.evidence_ids,
                claim.confidence,
                claim.status,
                self._text(claim.created_by_agent),
                claim.created_at,
            ),
        )
        if self._relation_exists(cur, "claim_records"):
            cur.execute(
                """
                INSERT INTO claim_records (
                    id, workspace_id, project_id, run_id, competitor_id, claim_type,
                    claim_text, evidence_ids, confidence, status, created_by_agent, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    evidence_ids = EXCLUDED.evidence_ids,
                    confidence = EXCLUDED.confidence,
                    status = EXCLUDED.status
                """,
                (
                    claim.id,
                    claim.workspace_id,
                    claim.project_id,
                    claim.run_id,
                    claim.competitor_id,
                    self._text(claim.claim_type),
                    self._text(claim.claim_text),
                    claim.evidence_ids,
                    claim.confidence,
                    claim.status,
                    self._text(claim.created_by_agent),
                    claim.created_at,
                ),
            )
        self._replace_claim_evidence_links(cur, claim)

    def _upsert_report_version(self, cur: Any, report: ReportVersionRecord) -> None:
        cur.execute(
            """
            INSERT INTO report_versions (
                id, workspace_id, project_id, run_id, parent_version_id, version_number,
                topic_normalized, competitor_layer, competitor_set_hash, status,
                report_md, claim_ids, evidence_ids, quality_metadata, created_at, published_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                report_md = EXCLUDED.report_md,
                claim_ids = EXCLUDED.claim_ids,
                evidence_ids = EXCLUDED.evidence_ids,
                quality_metadata = EXCLUDED.quality_metadata,
                published_at = EXCLUDED.published_at
            """,
            (
                report.id,
                report.workspace_id,
                report.project_id,
                report.run_id,
                report.parent_version_id,
                report.version_number,
                report.topic_normalized,
                report.competitor_layer,
                report.competitor_set_hash,
                report.status,
                self._text(report.report_md),
                report.claim_ids,
                report.evidence_ids,
                self._json(report.quality_metadata),
                report.created_at,
                report.published_at,
            ),
        )
        self._replace_report_version_claim_links(cur, report)
        self._replace_report_version_evidence_links(cur, report)

    def _upsert_notification(self, cur: Any, notification: NotificationRecord) -> None:
        cur.execute(
            """
            INSERT INTO notifications (
                id, workspace_id, project_id, notification_type, channel, severity, status,
                title, body, resource_type, resource_id, created_by, created_at,
                sent_at, read_at, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                notification_type = EXCLUDED.notification_type,
                channel = EXCLUDED.channel,
                severity = EXCLUDED.severity,
                status = EXCLUDED.status,
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                resource_type = EXCLUDED.resource_type,
                resource_id = EXCLUDED.resource_id,
                sent_at = EXCLUDED.sent_at,
                read_at = EXCLUDED.read_at,
                metadata = EXCLUDED.metadata
            """,
            (
                notification.id,
                notification.workspace_id,
                notification.project_id,
                notification.notification_type,
                notification.channel,
                notification.severity,
                notification.status,
                self._text(notification.title),
                self._text(notification.body),
                self._text(notification.resource_type),
                notification.resource_id,
                notification.created_by,
                notification.created_at,
                notification.sent_at,
                notification.read_at,
                self._json(notification.metadata),
            ),
        )

    def _replace_claim_evidence_links(self, cur: Any, claim: ClaimRecord) -> None:
        cur.execute("DELETE FROM claim_evidence WHERE claim_id = %s", (claim.id,))
        for evidence_id in claim.evidence_ids:
            cur.execute(
                """
                INSERT INTO claim_evidence (
                    claim_id, evidence_id, workspace_id, project_id
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (claim_id, evidence_id) DO NOTHING
                """,
                (claim.id, evidence_id, claim.workspace_id, claim.project_id),
            )

    def _replace_report_version_claim_links(
        self,
        cur: Any,
        report: ReportVersionRecord,
    ) -> None:
        cur.execute(
            "DELETE FROM report_version_claims WHERE report_version_id = %s",
            (report.id,),
        )
        for ordinal, claim_id in enumerate(report.claim_ids):
            cur.execute(
                """
                INSERT INTO report_version_claims (
                    report_version_id, claim_id, workspace_id, project_id, ordinal
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (report_version_id, claim_id) DO UPDATE SET
                    ordinal = EXCLUDED.ordinal
                """,
                (report.id, claim_id, report.workspace_id, report.project_id, ordinal),
            )

    def _replace_report_version_evidence_links(
        self,
        cur: Any,
        report: ReportVersionRecord,
    ) -> None:
        cur.execute(
            "DELETE FROM report_version_evidence WHERE report_version_id = %s",
            (report.id,),
        )
        for ordinal, evidence_id in enumerate(report.evidence_ids):
            cur.execute(
                """
                INSERT INTO report_version_evidence (
                    report_version_id, evidence_id, workspace_id, project_id, ordinal
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (report_version_id, evidence_id) DO UPDATE SET
                    ordinal = EXCLUDED.ordinal
                """,
                (report.id, evidence_id, report.workspace_id, report.project_id, ordinal),
            )

    def _audit_exists(
        self,
        cur: Any,
        action: str,
        resource_id: str,
        *,
        resource_type: str | None = None,
    ) -> bool:
        clauses = ["action = %s", "resource_id = %s"]
        params: list[str] = [action, resource_id]
        if resource_type is not None:
            clauses.append("resource_type = %s")
            params.append(resource_type)
        row = cur.execute(
            f"""
            SELECT 1
            FROM audit_logs
            WHERE {" AND ".join(clauses)}
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        return row is not None

    def _relation_exists(self, cur: Any, relation_name: str) -> bool:
        row = cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = %s
            LIMIT 1
            """,
            (relation_name,),
        ).fetchone()
        return row is not None

    def _copy_legacy_claim_records(self, cur: Any) -> None:
        if not self._relation_exists(cur, "claim_records"):
            return
        cur.execute(
            """
            INSERT INTO knowledge_claims (
                id, workspace_id, project_id, run_id, competitor_id, claim_type,
                claim_text, evidence_ids, confidence, status, created_by_agent, created_at
            )
            SELECT
                id, workspace_id, project_id, run_id, competitor_id, claim_type,
                claim_text, evidence_ids, confidence, status, created_by_agent, created_at
            FROM claim_records
            ON CONFLICT (id) DO NOTHING
            """
        )

    def _append_audit_once(
        self,
        cur: Any,
        *,
        workspace_id: str,
        actor_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str,
        after: dict[str, Any],
        before: dict[str, Any] | None = None,
    ) -> None:
        if self._audit_exists(
            cur,
            action,
            resource_id,
            resource_type=resource_type,
        ):
            return
        self._append_audit(
            cur,
            workspace_id=workspace_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
        )

    def _append_audit(
        self,
        cur: Any,
        *,
        workspace_id: str,
        actor_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str,
        after: dict[str, Any],
        before: dict[str, Any] | None = None,
    ) -> None:
        audit_id = stable_prefixed_id("audit", action, resource_id, after, length=16)
        cur.execute(
            """
            INSERT INTO audit_logs (
                id, workspace_id, actor_type, actor_id, action,
                resource_type, resource_id, before, after
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                audit_id,
                workspace_id,
                "system",
                actor_id,
                self._text(action),
                self._text(resource_type),
                resource_id,
                self._json(before) if before is not None else None,
                self._json(after),
            ),
        )

    def _json(self, value: dict[str, Any]) -> Any:
        return self._jsonb(sanitize_postgres_value(value))

    def _text(self, value: str | None) -> str | None:
        return sanitize_postgres_text(value)

    def _competitor_id(self, workspace_id: str, name: str) -> str:
        return compute_competitor_id(workspace_id, name)

    def _project_id(self, workspace_id: str, topic: str, competitor_ids: list[str]) -> str:
        return compute_project_id(workspace_id, topic, competitor_ids)


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "postgres" / "001_enterprise_core.sql"


def _usage_period(
    period_start: datetime | None,
    period_end: datetime | None,
) -> tuple[datetime, datetime]:
    default_start, default_end = current_month_window()
    return period_start or default_start, period_end or default_end


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


def _split_sql(script: str) -> list[str]:
    uncommented = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("--")
    )
    return [statement.strip() for statement in uncommented.split(";") if statement.strip()]
