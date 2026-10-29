"""Stable errors that never include connection strings or database payloads."""


class TaskCenterError(RuntimeError):
    code = "task_center_error"


class TaskCenterConfigurationError(TaskCenterError):
    code = "task_center_configuration"


class TaskCenterDisabled(TaskCenterError):
    code = "task_center_disabled"


class TaskCenterUnavailable(TaskCenterError):
    code = "task_center_unavailable"


class TaskCenterPoolBusy(TaskCenterUnavailable):
    code = "task_center_pool_busy"


class TaskCenterStorageError(TaskCenterUnavailable):
    code = "task_center_storage_error"

    def __init__(self, *, sqlstate: str | None = None) -> None:
        super().__init__("task center database operation failed")
        self.sqlstate = sqlstate


class TaskCenterSchemaError(TaskCenterUnavailable):
    code = "task_center_schema_not_ready"


class MigrationDriftError(TaskCenterSchemaError):
    code = "task_center_migration_drift"


class InvalidTaskCenterRequest(TaskCenterError):
    code = "invalid_task_center_request"
    status_code = 400


class SubmissionNotFound(TaskCenterError):
    code = "submission_not_found"
    status_code = 404


class IdempotencyConflict(TaskCenterError):
    code = "idempotency_conflict"
    status_code = 409


class PolicyConflict(TaskCenterError):
    code = "quota_policy_conflict"
    status_code = 409


class QuotaExceeded(TaskCenterError):
    code = "quota_exceeded"
    status_code = 429


class DispatchConflict(TaskCenterError):
    code = "dispatch_conflict"
    status_code = 409
