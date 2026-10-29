"""The single policy/path factory shared by run and model execution."""

from pathlib import Path

from packages.config import Settings
from packages.infrastructure.execution_control import (
    ExecutionPolicy,
    ExecutionUnavailableError,
    SQLiteExecutionCoordinator,
)


def execution_policy(settings: Settings) -> ExecutionPolicy:
    try:
        return ExecutionPolicy(
            global_running_limit=settings.execution_global_running_limit,
            workspace_running_limit=settings.execution_workspace_running_limit,
            global_queue_limit=settings.execution_global_queue_limit,
            workspace_queue_limit=settings.execution_workspace_queue_limit,
            queue_wait_seconds=settings.execution_queue_wait_seconds,
            model_concurrency=settings.llm_max_concurrency,
            model_wait_seconds=settings.execution_model_wait_seconds,
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionUnavailableError("Invalid shared execution policy") from exc


def create_execution_coordinator(
    settings: Settings,
    *,
    journal_path: Path | None = None,
) -> SQLiteExecutionCoordinator | None:
    if not settings.execution_control_enabled:
        return None
    path = Path(settings.execution_control_journal_path)
    if str(path) == ":memory:" or not settings.execution_control_journal_path.strip():
        raise ExecutionUnavailableError("Shared execution requires a file journal")
    if journal_path is not None and (
        str(journal_path) == ":memory:" or journal_path.resolve() != path.resolve()
    ):
        raise ExecutionUnavailableError("Execution and run journal paths differ")
    coordinator = SQLiteExecutionCoordinator(path, execution_policy(settings))
    # Validate storage, locking directory and persisted policy before accepting work.
    with coordinator._transaction():
        pass
    return coordinator
