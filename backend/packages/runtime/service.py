from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from packages.auth import EnterpriseUserContext, evaluate_access_policy
from packages.business_intel import evaluate_report_release_gate
from packages.compliance import compliance_policy_from_settings
from packages.config import Settings
from packages.enterprise import (
    EnterpriseStore,
    WorkspaceQuotaExceededError,
    build_report_version_diff,
    report_release_gate_scope,
)
from packages.enterprise.report_lifecycle import (
    mark_report_published,
    report_release_gate_snapshot,
)
from packages.evals import build_enterprise_evalops_report, build_evalops_release_contract
from packages.governance import (
    build_model_policy_report,
    build_runtime_policy_decision,
    model_policy_block_message,
)
from packages.hitl import append_hitl_lifecycle, build_hitl_lifecycle_event, hitl_lifecycle_history
from packages.identity import new_ui_run_idempotency_key, stable_prefixed_id
from packages.memory import PreferenceMemoryStore
from packages.orchestrator.service import RunService
from packages.runtime.commands import (
    ApproveReportCommand,
    CreateMonitorJobCommand,
    CreateRunCommand,
    PauseMonitorJobCommand,
    PublishReportCommand,
    RejectReportCommand,
    RequestApprovalCommand,
    RequestRedoCommand,
    ResumeMonitorJobCommand,
    ResumeReviewCommand,
    ReviseReportCommand,
    RuntimeCommandError,
    RuntimeCommandResult,
    RuntimeCommandRoute,
    RuntimeCommandStatus,
    RuntimeCommandType,
    TriggerMonitorJobCommand,
    UpdateMonitorJobCommand,
)
from packages.schema.api_dto import (
    MonitorStartRequest,
    ReportApprovalSignalRequest,
    RunCreateRequest,
    RunDetail,
    WorkflowStartResponse,
)
from packages.schema.enterprise import (
    ManualReportRevisionRequest,
    MonitorJobRecord,
    MonitorJobUpdateRequest,
    ProjectRecord,
    ReportReleaseGate,
    ReportVersionRecord,
    UserFeedbackRecord,
)
from packages.schema.evals import EvalOpsReleaseContract
from packages.workflows.service import TemporalWorkflowService, decide_temporal_cutover


class RuntimeCommandService:
    def __init__(
        self,
        *,
        settings: Settings,
        run_service: RunService,
        workflow_service: TemporalWorkflowService,
        enterprise_store: EnterpriseStore,
        preference_memory: PreferenceMemoryStore,
    ) -> None:
        self._settings = settings
        self._run_service = run_service
        self._workflow_service = workflow_service
        self._store = enterprise_store
        self._memory = preference_memory

    async def create_run(
        self,
        command: CreateRunCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        request = _with_run_idempotency_key(command.request)
        command_id = _command_id("create_run", actor, request.idempotency_key or request.topic)
        self._require_workspace_access(
            actor,
            request.workspace_id,
            "project:write",
            target_type="run",
            target_id=request.idempotency_key,
        )
        runtime_policy = build_runtime_policy_decision(
            self._settings,
            store=self._store,
            workspace_id=request.workspace_id,
            execution_mode=_resolved_execution_mode(request, self._settings),
        )
        self._ensure_model_policy_allows_execution_mode(request.execution_mode)
        self._ensure_workspace_quota(request.workspace_id)
        cutover = decide_temporal_cutover(self._settings, request)
        metadata = {
            "runtime_policy_decision": runtime_policy.model_dump(mode="json"),
            "temporal_target_percent": cutover.target_percent,
            "temporal_cutover_bucket": cutover.bucket,
            "temporal_cutover_reason": cutover.reason,
        }
        if cutover.route == "temporal":
            try:
                result = await self._workflow_service.start_competitive_intel(request)
            except Exception as exc:  # noqa: BLE001 - command surface explains route failure.
                raise RuntimeCommandError(
                    503,
                    "Temporal workflow service is unavailable.",
                    command_type="create_run",
                ) from exc
            try:
                await self._ensure_temporal_run_visible(result, request)
            except WorkspaceQuotaExceededError as exc:
                raise RuntimeCommandError(
                    429,
                    exc.decision.model_dump(mode="json"),
                    command_type="create_run",
                ) from exc
            except ValueError as exc:
                raise RuntimeCommandError(400, str(exc), command_type="create_run") from exc
            except Exception as exc:  # noqa: BLE001 - preserve existing API behavior.
                raise RuntimeCommandError(
                    500,
                    "Temporal workflow started but run visibility sync failed.",
                    command_type="create_run",
                ) from exc
            return _result(
                command_id=command_id,
                command_type="create_run",
                status="accepted",
                resource_type="run",
                resource_id=result.run_id,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                run_id=result.run_id,
                route="temporal",
                payload=result,
                metadata=metadata,
            )

        try:
            detail = await self._run_service.create_run(request)
        except WorkspaceQuotaExceededError as exc:
            raise RuntimeCommandError(
                429,
                exc.decision.model_dump(mode="json"),
                command_type="create_run",
            ) from exc
        except ValueError as exc:
            raise RuntimeCommandError(400, str(exc), command_type="create_run") from exc
        asyncio.create_task(self._run_service.run_pipeline(detail.id))
        return _result(
            command_id=command_id,
            command_type="create_run",
            status="succeeded",
            resource_type="run",
            resource_id=detail.id,
            workspace_id=detail.workspace_id,
            project_id=detail.project_id,
            run_id=detail.id,
            route="langgraph",
            payload=detail,
            metadata=metadata,
        )

    async def create_monitor_job(
        self,
        command: CreateMonitorJobCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        request = command.request
        project = self._project_or_error(request.project_id, actor, "project:write")
        if project.workspace_id != request.workspace_id:
            raise RuntimeCommandError(
                400,
                "Monitor job workspace does not match project workspace.",
                command_type="create_monitor_job",
            )
        monitor_id = request.monitor_id or stable_prefixed_id(
            "monitor-job",
            request.workspace_id,
            request.project_id,
            request.name,
            request.schedule,
            length=16,
        )
        competitors = self._store.list_competitors(project_id=project.id)
        job = MonitorJobRecord(
            id=monitor_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            name=request.name,
            dimensions=request.dimensions,
            competitor_ids=[item.id for item in competitors],
            schedule=request.schedule,
            interval_seconds=request.interval_seconds,
            max_cycles=request.max_cycles,
            execution_mode=request.execution_mode,
            alert_policy=request.alert_policy,
            release_policy=request.release_policy,
            notification_target=request.notification_target,
            created_by=actor.user_id,
            metadata={
                **request.metadata,
                "project_topic": project.topic,
                "runtime_command_boundary": True,
            },
        )
        stored = self._store.upsert_monitor_job(job, actor_id=actor.user_id)
        command_id = _command_id("create_monitor_job", actor, stored.id)
        return _result(
            command_id=command_id,
            command_type="create_monitor_job",
            status="succeeded",
            resource_type="monitor_job",
            resource_id=stored.id,
            workspace_id=stored.workspace_id,
            project_id=stored.project_id,
            route="enterprise",
            payload=stored,
            metadata={"monitor_job_status": stored.status},
        )

    async def update_monitor_job(
        self,
        command: UpdateMonitorJobCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        job = self._monitor_job_or_error(command.monitor_id, actor, "project:write")
        updated = self._store.update_monitor_job(
            job.id,
            command.request,
            actor_id=actor.user_id,
        )
        if updated is None:
            raise RuntimeCommandError(
                404,
                "Monitor job not found",
                command_type="update_monitor_job",
            )
        command_id = _command_id("update_monitor_job", actor, updated.id)
        return _result(
            command_id=command_id,
            command_type="update_monitor_job",
            status="succeeded",
            resource_type="monitor_job",
            resource_id=updated.id,
            workspace_id=updated.workspace_id,
            project_id=updated.project_id,
            route="enterprise",
            payload=updated,
            metadata={"monitor_job_status": updated.status},
        )

    async def pause_monitor_job(
        self,
        command: PauseMonitorJobCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        return await self.update_monitor_job(
            UpdateMonitorJobCommand(
                monitor_id=command.monitor_id,
                request=MonitorJobUpdateRequest(status="paused"),
            ),
            actor=actor,
        )

    async def resume_monitor_job(
        self,
        command: ResumeMonitorJobCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        return await self.update_monitor_job(
            UpdateMonitorJobCommand(
                monitor_id=command.monitor_id,
                request=MonitorJobUpdateRequest(status="active"),
            ),
            actor=actor,
        )

    async def trigger_monitor_job(
        self,
        command: TriggerMonitorJobCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        job = self._monitor_job_or_error(command.monitor_id, actor, "project:write")
        if job.status != "active":
            raise RuntimeCommandError(
                409,
                f"Monitor job {job.id} is {job.status}; resume it before triggering.",
                command_type="trigger_monitor_job",
            )
        runtime_policy = build_runtime_policy_decision(
            self._settings,
            store=self._store,
            workspace_id=job.workspace_id,
            execution_mode=_resolved_monitor_execution_mode(job, self._settings),
            requested_tools=[
                "web_search",
                "fetch_page",
                "rag_search_evidence",
                "online_gap_fill",
                "claim_validator",
                "source_snapshot",
            ],
        )
        if runtime_policy.status == "deny":
            raise RuntimeCommandError(
                409,
                runtime_policy.model_dump(mode="json"),
                command_type="trigger_monitor_job",
            )
        start_request = _monitor_start_request(job, requested_by=actor.user_id)
        try:
            response = await self._workflow_service.start_monitor(start_request)
        except Exception as exc:  # noqa: BLE001 - command layer owns workflow failures.
            self._store.record_monitor_job_run(
                job.id,
                status="failed",
                error="Temporal workflow service is unavailable.",
                actor_id=actor.user_id,
            )
            raise RuntimeCommandError(
                503,
                "Temporal workflow service is unavailable.",
                command_type="trigger_monitor_job",
            ) from exc
        updated = self._store.record_monitor_job_run(
            job.id,
            status="running",
            workflow_id=response.workflow_id,
            actor_id=actor.user_id,
        )
        command_id = _command_id("trigger_monitor_job", actor, job.id)
        return _result(
            command_id=command_id,
            command_type="trigger_monitor_job",
            status="accepted",
            resource_type="monitor_job",
            resource_id=job.id,
            workspace_id=job.workspace_id,
            project_id=job.project_id,
            route="temporal",
            payload=response,
            metadata={
                "monitor_job_status": updated.status if updated else job.status,
                "runtime_policy_decision": runtime_policy.model_dump(mode="json"),
            },
        )

    async def resume_review(
        self,
        command: ResumeReviewCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        detail = self._run_or_error(command.run_id, actor, "project:write")
        if command.request.decision == "redo" and not self._run_service.has_pending_interrupt(
            command.run_id
        ):
            raise RuntimeCommandError(
                409,
                "Manual scoped redo must use POST /runs/{run_id}/redo",
                command_type="resume_review",
            )
        command_id = _command_id("resume_review", actor, command.run_id)
        updated = await self._run_service.resume(command.run_id, command.request)
        if updated is None:
            raise RuntimeCommandError(404, "Run not found", command_type="resume_review")
        await self._emit_run_command(
            command_id=command_id,
            command_type="resume_review",
            run_id=updated.id,
            message=f"Runtime command accepted HITL decision: {command.request.decision}.",
            metadata={
                "decision": command.request.decision,
                "note_present": bool(command.request.note),
                "dimensions": command.request.dimensions or [],
            },
        )
        return _result(
            command_id=command_id,
            command_type="resume_review",
            status="succeeded",
            resource_type="run",
            resource_id=updated.id,
            workspace_id=updated.workspace_id,
            project_id=updated.project_id,
            run_id=updated.id,
            route="langgraph",
            payload=updated,
            metadata={"previous_status": detail.status, "decision": command.request.decision},
        )

    async def request_redo(
        self,
        command: RequestRedoCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        detail = self._run_or_error(command.run_id, actor, "project:write")
        if self._run_service.has_pending_interrupt(command.run_id):
            raise RuntimeCommandError(
                409,
                "Resolve the active HITL interrupt before manual redo.",
                command_type="request_redo",
            )
        if not self._run_service.can_start_redo(command.run_id):
            raise RuntimeCommandError(
                409,
                "No eligible QA findings or redo limit reached.",
                command_type="request_redo",
            )
        command_id = _command_id("request_redo", actor, command.run_id)
        await self._emit_run_command(
            command_id=command_id,
            command_type="request_redo",
            run_id=detail.id,
            message="Runtime command requested manual scoped redo.",
            metadata={
                "qa_finding_count": len(detail.qa_findings),
                "current_status": detail.status,
            },
        )
        asyncio.create_task(self._run_service.run_scoped_redo(command.run_id))
        return _result(
            command_id=command_id,
            command_type="request_redo",
            status="accepted",
            resource_type="run",
            resource_id=detail.id,
            workspace_id=detail.workspace_id,
            project_id=detail.project_id,
            run_id=detail.id,
            route="langgraph",
            payload=detail,
            metadata={"qa_finding_count": len(detail.qa_findings)},
        )

    async def request_approval(
        self,
        command: RequestApprovalCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        version = self._report_version_or_error(
            command.request.report_version_id,
            actor,
            "report:write",
        )
        command_id = _command_id("request_approval", actor, version.id)
        try:
            response = await self._workflow_service.start_report_approval(command.request)
        except Exception as exc:  # noqa: BLE001 - command surface explains route failure.
            raise RuntimeCommandError(
                503,
                "Temporal report approval workflow service is unavailable.",
                command_type="request_approval",
            ) from exc
        return _result(
            command_id=command_id,
            command_type="request_approval",
            status="accepted",
            resource_type="report_version",
            resource_id=version.id,
            workspace_id=version.workspace_id,
            project_id=version.project_id,
            run_id=version.run_id,
            report_version_id=version.id,
            route="temporal",
            payload=response,
            metadata={
                "workflow_id": response.workflow_id,
                "approver_ids": list(command.request.approver_ids),
            },
        )

    async def approve_report(
        self,
        command: ApproveReportCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        return await self._signal_report_approval(
            command_type="approve_report",
            report_version_id=command.report_version_id,
            request=command.request,
            actor=actor,
        )

    async def reject_report(
        self,
        command: RejectReportCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        return await self._signal_report_approval(
            command_type="reject_report",
            report_version_id=command.report_version_id,
            request=command.request,
            actor=actor,
        )

    async def _signal_report_approval(
        self,
        *,
        command_type: RuntimeCommandType,
        report_version_id: str,
        request: ReportApprovalSignalRequest,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        version = self._report_version_or_error(report_version_id, actor, "report:review")
        command_id = _command_id(command_type, actor, version.id)
        try:
            if command_type == "approve_report":
                response = await self._workflow_service.approve_report(report_version_id, request)
            elif command_type == "reject_report":
                response = await self._workflow_service.reject_report(report_version_id, request)
            else:
                raise RuntimeCommandError(400, "Unsupported approval signal command.")
        except RuntimeCommandError:
            raise
        except Exception as exc:  # noqa: BLE001 - command surface explains route failure.
            raise RuntimeCommandError(
                503,
                "Temporal report approval workflow service is unavailable.",
                command_type=command_type,
            ) from exc
        return _result(
            command_id=command_id,
            command_type=command_type,
            status="accepted",
            resource_type="report_version",
            resource_id=version.id,
            workspace_id=version.workspace_id,
            project_id=version.project_id,
            run_id=version.run_id,
            report_version_id=version.id,
            route="temporal",
            payload=response,
            metadata={
                "workflow_id": response.workflow_id,
                "decision": response.decision,
                "approver_id": request.approver_id,
            },
        )

    def revise_report(
        self,
        command: ReviseReportCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        source = self._report_version_or_error(command.report_version_id, actor, "report:write")
        updated, command_id = self._create_manual_report_revision(source, command.request, actor)
        return _result(
            command_id=command_id,
            command_type="revise_report",
            status="succeeded",
            resource_type="report_version",
            resource_id=updated.id,
            workspace_id=updated.workspace_id,
            project_id=updated.project_id,
            run_id=updated.run_id,
            report_version_id=updated.id,
            route="enterprise",
            payload=updated,
            metadata={
                "source_report_version_id": source.id,
                "source_status": source.status,
                "version_number": updated.version_number,
            },
        )

    def publish_report(
        self,
        command: PublishReportCommand,
        *,
        actor: EnterpriseUserContext,
    ) -> RuntimeCommandResult:
        version = self._report_version_or_error(command.report_version_id, actor, "report:write")
        command_id = _command_id("publish_report", actor, version.id)
        if version.status not in {"approved", "published"}:
            raise RuntimeCommandError(
                409,
                {
                    "status": "blocked",
                    "reason": "report_approval_required",
                    "message": "Report version must be approved before it can be published.",
                    "report_version_id": version.id,
                    "current_status": version.status,
                    "command_id": command_id,
                },
                command_type="publish_report",
            )
        gate = self._enforce_report_release_gate(version, actor)
        evalops_contract = self._evalops_release_contract_for_version(version)
        if self._settings.evalops_release_mode == "blocking" and not evalops_contract.allowed:
            raise RuntimeCommandError(
                409,
                {
                    "status": "blocked",
                    "reason": "evalops_release_contract_blocked",
                    "message": evalops_contract.reason,
                    "report_version_id": version.id,
                    "command_id": command_id,
                    "evalops_release_contract": evalops_contract.model_dump(mode="json"),
                },
                command_type="publish_report",
            )
        updated = mark_report_published(version, actor_id=actor.user_id, gate=gate)
        publication = dict(updated.quality_metadata.get("publication") or {})
        publication["evalops_release_contract"] = evalops_contract.model_dump(mode="json")
        updated = updated.model_copy(
            update={
                "quality_metadata": {
                    **updated.quality_metadata,
                    "publication": publication,
                }
            }
        )
        stored = self._store.upsert_report_version(updated)
        self._store.audit_report_version_transition(
            stored,
            action="report_version.published",
            actor_id=actor.user_id,
            before_status=version.status,
            metadata={
                "command_id": command_id,
                "audit_correlation_id": _audit_correlation_id(command_id),
                "replay_correlation_id": _replay_correlation_id(command_id),
                "publication": stored.quality_metadata.get("publication", {}),
                "hitl_lifecycle": stored.quality_metadata.get("hitl_lifecycle", []),
                "release_gate": report_release_gate_snapshot(gate),
                "evalops_release_contract": evalops_contract.model_dump(mode="json"),
            },
        )
        return _result(
            command_id=command_id,
            command_type="publish_report",
            status="succeeded",
            resource_type="report_version",
            resource_id=stored.id,
            workspace_id=stored.workspace_id,
            project_id=stored.project_id,
            run_id=stored.run_id,
            report_version_id=stored.id,
            route="enterprise",
            payload=stored,
            metadata={
                "release_gate": report_release_gate_snapshot(gate),
                "evalops_release_contract": evalops_contract.model_dump(mode="json"),
            },
        )

    async def _ensure_temporal_run_visible(
        self,
        result: WorkflowStartResponse,
        request: RunCreateRequest,
    ) -> None:
        visible_request = request.model_copy(update={"idempotency_key": result.idempotency_key})
        detail = await self._run_service.ensure_run_visible(visible_request)
        if detail.id != result.run_id:
            raise RuntimeError(
                f"Temporal returned run_id={result.run_id}, but local visibility "
                f"created run_id={detail.id}."
            )

    def _create_manual_report_revision(
        self,
        source: ReportVersionRecord,
        request: ManualReportRevisionRequest,
        actor: EnterpriseUserContext,
    ) -> tuple[ReportVersionRecord, str]:
        next_version = self._store.next_report_version_number(
            project_id=source.project_id,
            topic_normalized=source.topic_normalized,
            competitor_layer=source.competitor_layer,
            competitor_set_hash=source.competitor_set_hash,
        )
        revision_id = stable_prefixed_id(
            "report-version-manual",
            source.id,
            next_version,
            request.report_md,
            length=16,
        )
        metadata = dict(source.quality_metadata)
        metadata["manual_revision"] = {
            "source_report_version_id": source.id,
            "edited_by": actor.user_id,
            "note": request.note,
            "created_at": datetime.utcnow().isoformat(),
        }
        metadata = append_hitl_lifecycle(
            metadata,
            build_hitl_lifecycle_event(
                lifecycle_stage="revision_created",
                review_kind="manual_report_revision",
                stage="manual_report_revision",
                decision="manual_revision",
                actor_id=actor.user_id,
                target_type="report_version",
                target_id=revision_id,
                run_id=source.run_id,
                report_version_id=revision_id,
                result_action="create_draft_report_version",
                note=request.note,
                metadata={
                    "source_report_version_id": source.id,
                    "source_status": source.status,
                    "next_version_number": next_version,
                },
                sequence=len(hitl_lifecycle_history(metadata)) + 1,
            ),
        )
        revision = source.model_copy(
            update={
                "id": revision_id,
                "parent_version_id": source.id,
                "version_number": next_version,
                "status": "draft",
                "report_md": request.report_md,
                "quality_metadata": metadata,
                "created_at": datetime.utcnow(),
                "published_at": None,
            }
        )
        updated = self._store.upsert_report_version(revision)
        diff = build_report_version_diff(updated, base_version=source)
        command_id = _command_id("revise_report", actor, updated.id)
        self._store.audit_report_version_transition(
            updated,
            action="report_version.manual_revision_created",
            actor_id=actor.user_id,
            before_status=source.status,
            note=request.note,
            metadata={
                "command_id": command_id,
                "audit_correlation_id": _audit_correlation_id(command_id),
                "replay_correlation_id": _replay_correlation_id(command_id),
                "manual_revision": updated.quality_metadata.get("manual_revision", {}),
                "hitl_lifecycle": updated.quality_metadata.get("hitl_lifecycle", []),
                "source_report_version_id": source.id,
                "source_status": source.status,
                "diff": {
                    "base_version_id": source.id,
                    "added_lines": diff.added_lines,
                    "removed_lines": diff.removed_lines,
                    "unchanged_lines": diff.unchanged_lines,
                },
            },
        )
        self._capture_manual_report_revision_memory(source, updated, request, actor)
        return updated, command_id

    def _capture_manual_report_revision_memory(
        self,
        source: ReportVersionRecord,
        revision: ReportVersionRecord,
        request: ManualReportRevisionRequest,
        actor: EnterpriseUserContext,
    ) -> None:
        note = request.note.strip()
        message_parts = [
            f"Manual report correction created draft v{revision.version_number}.",
            (
                "Treat reviewer edits as writing and QA policy feedback: keep recommendations "
                "source-backed, decision-ready, and explicit about evidence risk."
            ),
        ]
        if note:
            message_parts.append(note)
        feedback = self._memory.add_feedback(
            UserFeedbackRecord(
                id="",
                workspace_id=revision.workspace_id,
                project_id=revision.project_id,
                user_id=actor.user_id,
                feedback_type="correction",
                target_type="report",
                target_id=revision.id,
                run_id=revision.run_id,
                report_version_id=revision.id,
                message=" ".join(message_parts),
                tags=[
                    "manual_revision",
                    "report",
                    "correction",
                    "writing",
                    "quality_gate",
                    revision.competitor_layer,
                ],
                metadata={
                    "source": "manual_report_revision",
                    "source_report_version_id": source.id,
                    "updated_report_version_id": revision.id,
                    "version_number": revision.version_number,
                    "note": note,
                },
            ),
            policy=compliance_policy_from_settings(self._settings),
        )
        candidates = [candidate for candidate in self._memory.extract_candidates(feedback)]
        for candidate in candidates:
            self._memory.upsert_candidate(candidate)
        self._store.record_memory_feedback_audit(feedback, candidates, actor_id=actor.user_id)

    def _ensure_model_policy_allows_execution_mode(self, execution_mode: str) -> None:
        if execution_mode != "real":
            return
        report = build_model_policy_report(self._settings)
        if report.real_execution_allowed:
            return
        raise RuntimeCommandError(
            400,
            {
                "message": model_policy_block_message(report),
                "policy_version": report.policy_version,
                "blocking_finding_ids": report.blocking_finding_ids,
                "status": report.status,
            },
            command_type="create_run",
        )

    def _ensure_workspace_quota(self, workspace_id: str) -> None:
        try:
            self._run_service.ensure_workspace_quota_allows_run(workspace_id)
        except WorkspaceQuotaExceededError as exc:
            raise RuntimeCommandError(
                429,
                exc.decision.model_dump(mode="json"),
                command_type="create_run",
            ) from exc

    def _run_or_error(
        self,
        run_id: str,
        actor: EnterpriseUserContext,
        action: str,
    ) -> RunDetail:
        detail = self._run_service.get_run(run_id)
        if detail is None:
            raise RuntimeCommandError(404, "Run not found")
        self._require_workspace_access(
            actor,
            detail.workspace_id,
            action,
            target_type="run",
            target_id=detail.id,
        )
        return detail

    def _project_or_error(
        self,
        project_id: str,
        actor: EnterpriseUserContext,
        action: str,
    ) -> ProjectRecord:
        project = self._store.get_project(project_id)
        if project is None:
            raise RuntimeCommandError(404, "Project not found")
        self._require_workspace_access(
            actor,
            project.workspace_id,
            action,
            target_type="project",
            target_id=project.id,
        )
        return project

    def _monitor_job_or_error(
        self,
        monitor_id: str,
        actor: EnterpriseUserContext,
        action: str,
    ) -> MonitorJobRecord:
        job = self._store.get_monitor_job(monitor_id)
        if job is None:
            raise RuntimeCommandError(404, "Monitor job not found")
        self._require_workspace_access(
            actor,
            job.workspace_id,
            action,
            target_type="monitor_job",
            target_id=job.id,
        )
        return job

    def _report_version_or_error(
        self,
        version_id: str,
        actor: EnterpriseUserContext,
        action: str,
    ) -> ReportVersionRecord:
        version = self._store.get_report_version(version_id)
        if version is None:
            raise RuntimeCommandError(404, "Report version not found")
        self._require_workspace_access(
            actor,
            version.workspace_id,
            action,
            target_type="report_version",
            target_id=version.id,
        )
        return version

    def _release_gate_for_version(
        self,
        version: ReportVersionRecord,
        actor: EnterpriseUserContext,
        action: str,
    ) -> ReportReleaseGate:
        project = self._project_or_error(version.project_id, actor, action)
        if project.workspace_id != version.workspace_id:
            raise RuntimeCommandError(400, "Report workspace does not match project")
        competitors, evidence, claims = report_release_gate_scope(
            version,
            project=project,
            store=self._store,
        )
        return evaluate_report_release_gate(
            project=project,
            report_version=version,
            competitors=competitors,
            evidence=evidence,
            claims=claims,
            source_registry=self._store.list_source_registry(workspace_id=project.workspace_id),
        )

    def _enforce_report_release_gate(
        self,
        version: ReportVersionRecord,
        actor: EnterpriseUserContext,
    ) -> ReportReleaseGate:
        gate = self._release_gate_for_version(version, actor, "report:write")
        if gate.allowed:
            return gate
        raise RuntimeCommandError(409, gate.model_dump(mode="json"), command_type="publish_report")

    def _evalops_release_contract_for_version(
        self,
        version: ReportVersionRecord,
    ) -> EvalOpsReleaseContract:
        runs = [
            detail
            for summary in self._run_service.list_runs()
            if (detail := self._run_service.get_run(summary.id)) is not None
            and detail.project_id == version.project_id
        ]
        if version.run_id and all(detail.id != version.run_id for detail in runs):
            detail = self._run_service.get_run(version.run_id)
            if detail is not None:
                runs.append(detail)
        report = build_enterprise_evalops_report(
            runs,
            limit=self._settings.evalops_release_limit,
            judge_mode="heuristic",
            settings=self._settings,
        )
        return build_evalops_release_contract(
            report,
            mode=self._settings.evalops_release_mode,
        )

    def _require_workspace_access(
        self,
        actor: EnterpriseUserContext,
        workspace_id: str,
        action: str,
        *,
        target_type: str = "workspace",
        target_id: str | None = None,
    ) -> None:
        decision = evaluate_access_policy(
            actor,
            workspace_id,
            action,
            target_type=target_type,
            target_id=target_id,
        )
        if decision.allowed:
            return
        raise RuntimeCommandError(403, decision.model_dump(mode="json"))

    async def _emit_run_command(
        self,
        *,
        command_id: str,
        command_type: RuntimeCommandType,
        run_id: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._run_service.emit(
            run_id,
            "runtime.command",
            "runtime",
            None,
            message,
            {
                "command_id": command_id,
                "command_type": command_type,
                "audit_correlation_id": _audit_correlation_id(command_id),
                "replay_correlation_id": _replay_correlation_id(command_id),
                "metadata": metadata or {},
            },
        )


def _with_run_idempotency_key(request: RunCreateRequest) -> RunCreateRequest:
    if request.idempotency_key:
        return request
    return request.model_copy(update={"idempotency_key": new_ui_run_idempotency_key()})


def _resolved_execution_mode(request: RunCreateRequest, settings: Settings) -> str:
    if request.execution_mode in {"demo", "real"}:
        return request.execution_mode
    return "real" if settings.default_execution_mode == "real" else "demo"


def _resolved_monitor_execution_mode(job: MonitorJobRecord, settings: Settings) -> str:
    if job.execution_mode in {"demo", "real"}:
        return job.execution_mode
    return "real" if settings.default_execution_mode == "real" else "demo"


def _monitor_start_request(
    job: MonitorJobRecord,
    *,
    requested_by: str,
) -> MonitorStartRequest:
    return MonitorStartRequest(
        workspace_id=job.workspace_id,
        project_id=job.project_id,
        monitor_id=job.id,
        requested_by=requested_by,
        dimensions=job.dimensions,
        execution_mode=job.execution_mode,
        interval_seconds=job.interval_seconds,
        max_cycles=job.max_cycles,
    )


def _result(
    *,
    command_id: str,
    command_type: RuntimeCommandType,
    status: RuntimeCommandStatus,
    resource_type: str,
    resource_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    run_id: str | None = None,
    report_version_id: str | None = None,
    route: RuntimeCommandRoute = "none",
    payload: Any = None,
    metadata: dict[str, Any] | None = None,
) -> RuntimeCommandResult:
    return RuntimeCommandResult(
        command_id=command_id,
        command_type=command_type,
        status=status,
        resource_type=resource_type,
        resource_id=resource_id,
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        report_version_id=report_version_id,
        audit_correlation_id=_audit_correlation_id(command_id),
        replay_correlation_id=_replay_correlation_id(command_id),
        route=route,
        payload=payload,
        metadata=metadata or {},
    )


def _command_id(
    command_type: RuntimeCommandType,
    actor: EnterpriseUserContext,
    target_id: str | None,
) -> str:
    return stable_prefixed_id(
        "runtime-command",
        command_type,
        actor.user_id,
        target_id or "",
        datetime.utcnow().isoformat(),
        length=16,
    )


def _audit_correlation_id(command_id: str) -> str:
    return stable_prefixed_id("audit-correlation", command_id, length=16)


def _replay_correlation_id(command_id: str) -> str:
    return stable_prefixed_id("replay-correlation", command_id, length=16)
