from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from packages.enterprise.store import (
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_ID,
    EnterpriseRunContext,
    _normalize_key,
    _short_hash,
    _title_from_id,
)
from packages.identity import compute_competitor_set_hash, compute_topic_normalized
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import (
    AuditLogRecord,
    ClaimRecord,
    CompetitorRecord,
    EnterpriseRunProjection,
    EvidenceQualityLabel,
    EvidenceRecord,
    ProjectRecord,
    ReportVersionRecord,
    WorkspaceRecord,
)


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
        self._connect = connect
        self._dict_row = dict_row
        self._jsonb = Jsonb
        if auto_migrate:
            self.migrate()

    def migrate(self) -> None:
        script = _schema_path().read_text(encoding="utf-8")
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                for statement in _split_sql(script):
                    cur.execute(statement)
                self._copy_legacy_claim_records(cur)
            conn.commit()

    def ping(self) -> str:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
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
                        resource_id=f"{project_id}:{competitor_id}",
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
        return ProjectRecord.model_validate(dict(row)) if row else None

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
                        created_by, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        topic = EXCLUDED.topic,
                        topic_normalized = EXCLUDED.topic_normalized,
                        competitor_layer = EXCLUDED.competitor_layer,
                        competitor_set_hash = EXCLUDED.competitor_set_hash,
                        scenario_id = EXCLUDED.scenario_id,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        project.id,
                        project.workspace_id,
                        project.name,
                        project.topic,
                        project.topic_normalized,
                        project.competitor_layer,
                        project.competitor_set_hash,
                        project.scenario_id,
                        project.created_by,
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
                    before=ProjectRecord.model_validate(dict(before_row)).model_dump(mode="json")
                    if before_row
                    else None,
                    after=project.model_dump(mode="json"),
                )
            conn.commit()
        return project

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
                "SELECT * FROM evidence_records WHERE project_id = %s ORDER BY captured_at DESC",
                (project_id,),
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
                self._upsert_evidence(cur, evidence)
                self._append_audit(
                    cur,
                    workspace_id=evidence.workspace_id,
                    actor_id=DEFAULT_USER_ID,
                    action="evidence.upserted",
                    resource_type="evidence",
                    resource_id=evidence.id,
                    before=EvidenceRecord.model_validate(dict(before_row)).model_dump(mode="json")
                    if before_row
                    else None,
                    after=evidence.model_dump(mode="json"),
                )
            conn.commit()
        return evidence

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
                before = EvidenceRecord.model_validate(dict(row))
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
                "SELECT * FROM knowledge_claims WHERE project_id = %s ORDER BY created_at DESC",
                (project_id,),
                ClaimRecord,
            )
        return self._list_models(
            "SELECT * FROM knowledge_claims ORDER BY created_at DESC",
            (),
            ClaimRecord,
        )

    def list_report_versions(self, project_id: str | None = None) -> list[ReportVersionRecord]:
        if project_id:
            return self._list_models(
                """
                SELECT *
                FROM report_versions
                WHERE project_id = %s
                ORDER BY created_at DESC, version_number DESC
                """,
                (project_id,),
                ReportVersionRecord,
            )
        return self._list_models(
            "SELECT * FROM report_versions ORDER BY created_at DESC, version_number DESC",
            (),
            ReportVersionRecord,
        )

    def get_report_version(self, version_id: str) -> ReportVersionRecord | None:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            row = conn.execute(
                "SELECT * FROM report_versions WHERE id = %s",
                (version_id,),
            ).fetchone()
        return ReportVersionRecord.model_validate(dict(row)) if row else None

    def upsert_report_version(self, version: ReportVersionRecord) -> ReportVersionRecord:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                before_row = cur.execute(
                    "SELECT * FROM report_versions WHERE id = %s",
                    (version.id,),
                ).fetchone()
                self._upsert_report_version(cur, version)
                self._append_audit(
                    cur,
                    workspace_id=version.workspace_id,
                    actor_id=DEFAULT_USER_ID,
                    action="report_version.upserted",
                    resource_type="report_version",
                    resource_id=version.id,
                    before=ReportVersionRecord.model_validate(dict(before_row)).model_dump(
                        mode="json"
                    )
                    if before_row
                    else None,
                    after=version.model_dump(mode="json"),
                )
            conn.commit()
        return version

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
        return ReportVersionRecord.model_validate(dict(row)) if row else None

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

    def _list_models(
        self,
        sql: str,
        params: tuple[Any, ...],
        model: type[BaseModel],
    ) -> list[Any]:
        with self._connect(self.database_url, row_factory=self._dict_row) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [model.model_validate(dict(row)) for row in rows]

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
        by_id = {row["id"]: model.model_validate(dict(row)) for row in rows}
        return [by_id[item] for item in ids if item in by_id]

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
            (workspace_id, _title_from_id(workspace_id), "Phase 1 workspace."),
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

    def _upsert_project(
        self,
        cur: Any,
        detail: RunDetail,
        context: EnterpriseRunContext,
        actor_id: str,
    ) -> None:
        cur.execute(
            """
            INSERT INTO projects (
                id, workspace_id, name, topic, topic_normalized,
                competitor_layer, competitor_set_hash, scenario_id,
                created_by, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                topic = EXCLUDED.topic,
                topic_normalized = EXCLUDED.topic_normalized,
                competitor_layer = EXCLUDED.competitor_layer,
                competitor_set_hash = EXCLUDED.competitor_set_hash,
                scenario_id = EXCLUDED.scenario_id,
                updated_at = now()
            """,
            (
                context.project_id,
                context.workspace_id,
                detail.topic,
                detail.topic,
                compute_topic_normalized(detail.topic),
                detail.plan.competitor_layer,
                compute_competitor_set_hash(context.competitor_ids),
                detail.plan.scenario_id,
                actor_id,
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
                name,
                _normalize_key(name),
                detail.plan.competitor_layer,
                detail.plan.homepage_hints.get(name),
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

    def _upsert_run(
        self,
        cur: Any,
        detail: RunDetail,
        context: EnterpriseRunContext,
    ) -> None:
        cur.execute(
            """
            INSERT INTO runs (
                id, workspace_id, project_id, topic, status, execution_mode,
                detail_json, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                status = EXCLUDED.status,
                detail_json = EXCLUDED.detail_json,
                updated_at = EXCLUDED.updated_at
            """,
            (
                detail.id,
                context.workspace_id,
                context.project_id,
                detail.topic,
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
                dimension, source_type, title, url, snippet, content_hash,
                reliability_score, freshness_score, quality_label, captured_at, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                reliability_score = EXCLUDED.reliability_score,
                freshness_score = EXCLUDED.freshness_score,
                quality_label = EXCLUDED.quality_label,
                metadata = EXCLUDED.metadata
            """,
            (
                evidence.id,
                evidence.workspace_id,
                evidence.project_id,
                evidence.run_id,
                evidence.raw_source_id,
                evidence.competitor_id,
                evidence.dimension,
                evidence.source_type,
                evidence.title,
                str(evidence.url) if evidence.url else None,
                evidence.snippet,
                evidence.content_hash,
                evidence.reliability_score,
                evidence.freshness_score,
                evidence.quality_label,
                evidence.captured_at,
                self._json(evidence.metadata),
            ),
        )

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
                claim.claim_type,
                claim.claim_text,
                claim.evidence_ids,
                claim.confidence,
                claim.status,
                claim.created_by_agent,
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
                    claim.claim_type,
                    claim.claim_text,
                    claim.evidence_ids,
                    claim.confidence,
                    claim.status,
                    claim.created_by_agent,
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
                report_md, claim_ids, evidence_ids, created_at, published_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                report_md = EXCLUDED.report_md,
                claim_ids = EXCLUDED.claim_ids,
                evidence_ids = EXCLUDED.evidence_ids
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
                report.report_md,
                report.claim_ids,
                report.evidence_ids,
                report.created_at,
                report.published_at,
            ),
        )
        self._replace_report_version_claim_links(cur, report)
        self._replace_report_version_evidence_links(cur, report)

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
        audit_id = f"audit-{_short_hash(f'{action}|{resource_id}|{after}')}"
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
                action,
                resource_type,
                resource_id,
                self._json(before) if before is not None else None,
                self._json(after),
            ),
        )

    def _json(self, value: dict[str, Any]) -> Any:
        return self._jsonb(value)

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


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "postgres" / "001_enterprise_core.sql"


def _split_sql(script: str) -> list[str]:
    uncommented = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("--")
    )
    return [statement.strip() for statement in uncommented.split(";") if statement.strip()]
